# Pipeline Upgrade — Phase 4 Plan
## Input-Quality + Recovery Cascade for the Wave Orchestrator

**Date:** 2026-04-26
**Scope:** Closing the 13-risk inventory (Risks #18-30; see §C) exposed by the M1 hardening smoke at HEAD `1c46445`. Builds on Phase 1-3.5 audit-fix-loop guardrails (`docs/plans/2026-04-26-audit-fix-guardrails-phase1-3.md`).
**Smoke evidence root:** `v18 test runs/m1-hardening-smoke-20260426-173745/`
**Smoke landing memory:** `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/smoke_2026-04-26_landing.md`
**Source-of-truth status:** This document is the authoritative Phase 4 source. All open questions are RESOLVED in §M; new ambiguity discovered during implementation must be added as a `[NEW — Phase 4.<N>]` halt memo at end of doc (see §0.10).

---

## Section 0 — Execution Plan (READ FIRST)

This plan ships in **seven phases**, one phase per session, in dependency order. The phases are grouped:

* **Group A — Input quality** (Phases 4.1, 4.2, 4.3): fix the upstream pipeline that's producing un-passable briefs and grading-on-others'-work. Highest leverage.
* **Group B — Forensics + observability** (Phase 4.4): close the wave-fail forensics gap so post-mortems actually distinguish failure modes.
* **Group C — Recovery wiring** (Phases 4.5, 4.6): the cascade that handles failures when input-quality fixes still aren't enough.
* **Group D — Boundaries** (Phase 4.7): scaffold + wave-prompt template upgrades. Needs design care; ship last.

Each phase is run by ONE focused implementer agent. The implementer must follow the cross-phase invariants in §0.1 and the per-phase brief in §0.2..§0.8. Phases are dependency-ordered; later phases cannot start until earlier ones have shipped clean.

**Cost budget per phase (rough estimate):**
* Phase 4.1, 4.2, 4.3, 4.4: ~$5-15 each in implementer-agent dispatch tokens (TDD + small surface area). No mandatory full-smoke before merge.
* Phase 4.5: ~$10-25 + a full M1 smoke (~$5-10 if clean, more if recovery cascade exercised).
* Phase 4.6: ~$10-20 + a full M1 smoke + a 2-milestone synthetic smoke (~$10-20).
* Phase 4.7: ~$10-25 + a full M1 smoke (validates new prompts + scaffold convention).

**Total estimated Phase 4 cost: $80-180 over 22-35 days of focused work.** Surface budget to user before each phase begins; if a phase's actual cost trends ≥2x estimate, surface immediately.

**Out-of-strict-order shipping:** Phase 4.6 (anchor-on-complete + retry flag) is implementation-INDEPENDENT of Phase 4.5 (Risk #1 lift). Test composition prefers 4.5 → 4.6 because Phase 4.5's FAILED→COMPLETE transition would trigger Phase 4.6's anchor-on-complete capture (testable composition). But if 4.6 ships before 4.5, the retry-milestone flag still works for milestones that originally completed naturally. **Default order is the one in §0.0; deviations require user approval and a memo.**

### 0.0 Kickoff prompt templates (copy-paste verbatim per phase)

**Phase 4.1 kickoff prompt:**
```
You are Phase 4.1 of the pipeline-upgrade implementation.

Read docs/plans/2026-04-26-pipeline-upgrade-phase4.md top-to-bottom — Section 0 first.
Then read ~/.claude/projects/C--Projects-agent-team-v18-codex/memory/MEMORY.md
AND ~/.claude/projects/C--Projects-agent-team-v18-codex/memory/smoke_2026-04-26_landing.md.

Confirm Phase 1.6 is at HEAD (commit 1c46445 or later) with `git log --oneline -1` and that
`tests/test_audit_fix_guardrails_phase{1,1_5,1_6,2,3,3_5}.py` are all green before starting.

Follow §0.1 (cross-phase invariants — all 22 rules) and §0.2 (Phase 4.1 brief).
Implement Section D. When done, write phase_4_1_landing.md per §0.9.

Use mcp__sequential-thinking__sequentialthinking when:
  - Two primitives interact in a non-obvious way
  - You discover a gap not in §C
  - You're about to design something that wasn't explicitly resolved in §M

Use mcp__context7__query-docs (after resolve-library-id) for ANY library/SDK question listed
in §0.2 "Required Context7 lookups." Never trust training data. Never guess.

Stop conditions are §0.10. NEVER paper over a halt.

Use the smoke run-dir at `v18 test runs/m1-hardening-smoke-20260426-173745/` as ground truth.
Specifically cite WAVE_FINDINGS.json, telemetry/*.json, and the codex-captures/ when designing
test fixtures. The data is gold; use it.
```

**Phase 4.2 kickoff prompt:**
```
You are Phase 4.2 of the pipeline-upgrade implementation.

Read docs/plans/2026-04-26-pipeline-upgrade-phase4.md top-to-bottom.
Then read MEMORY.md, smoke_2026-04-26_landing.md, and phase_4_1_landing.md.

Confirm Phase 4.1 is merged + smoke clean before starting (its commit on master).

Follow §0.1 (cross-phase invariants) and §0.3 (Phase 4.2 brief).
Implement Section E. Write phase_4_2_landing.md per §0.9.

Use mcp__sequential-thinking__sequentialthinking and mcp__context7 as required by §0.3.

Stop conditions are §0.10.
```

**Phase 4.3 kickoff prompt:**
```
You are Phase 4.3 of the pipeline-upgrade implementation.

Read docs/plans/2026-04-26-pipeline-upgrade-phase4.md top-to-bottom.
Then read MEMORY.md + smoke_2026-04-26_landing.md + phase_4_1_landing.md + phase_4_2_landing.md.

Confirm Phases 4.1 + 4.2 are merged + smoke clean.

Follow §0.1 and §0.4. Implement Section F. Write phase_4_3_landing.md per §0.9.
```

**Phase 4.4 kickoff prompt:**
```
You are Phase 4.4 of the pipeline-upgrade implementation.

Read the plan top-to-bottom. Read MEMORY.md + smoke_2026-04-26_landing.md +
phase_4_{1,2,3}_landing.md. Confirm Group A merged + smoke clean.

Follow §0.1 and §0.5. Implement Section G. Write phase_4_4_landing.md per §0.9.
```

**Phase 4.5 kickoff prompt:**
```
You are Phase 4.5 of the pipeline-upgrade implementation.

Read the plan top-to-bottom. Read MEMORY.md + smoke_2026-04-26_landing.md +
phase_4_{1,2,3,4}_landing.md. Confirm Phases 4.1-4.4 merged + smoke clean.

Follow §0.1 and §0.6. Implement Section H. Write phase_4_5_landing.md per §0.9.

Phase 4.5 LIFTS Phase 1 Risk #1 conditionally — read phase_1_landing.md carefully and
understand the original safety argument for Risk #1 before lifting it. Surface to user
if you discover Risk #1's reasoning was sounder than this plan represents.
```

**Phase 4.6 kickoff prompt:**
```
You are Phase 4.6 of the pipeline-upgrade implementation.

Read the plan top-to-bottom. Read MEMORY.md + smoke_2026-04-26_landing.md +
phase_4_{1,2,3,4,5}_landing.md. Confirm Phases 4.1-4.5 merged + smoke clean.

Follow §0.1 and §0.7. Implement Section I. Write phase_4_6_landing.md per §0.9.

Phase 4.6 EXTENDS the Phase 1 anchor primitive. Read phase_1_landing.md "Anchor primitive API"
section verbatim before extending. The single-slot semantic must survive; per-milestone
chain is additive.
```

**Phase 4.7 kickoff prompt:**
```
You are Phase 4.7 of the pipeline-upgrade implementation.

Read the plan top-to-bottom. Read MEMORY.md + smoke_2026-04-26_landing.md +
phase_4_{1..6}_landing.md. Confirm all prior phases merged + smoke clean.

Follow §0.1 and §0.8. Implement Section J. Write phase_4_7_landing.md per §0.9.

Phase 4.7 touches PROMPT TEMPLATES and the SCAFFOLD CONVENTION. These are load-bearing for
every future build. Maximum care: every change must be backward-compat for stock smokes.
If you discover the scaffold convention reform requires deeper redesign than §J describes,
STOP and surface to user before implementing.
```

### 0.0a Branching workflow — direct-to-master (continued from Phase 1-3.5)

**No branching. No PRs. All phases commit and push directly to `master`.** Same workflow as Phase 1-3.5. Per-phase commit format: `feat(pipeline-upgrade): Phase 4.<N> — <one-line summary>`. Use HEREDOC for messages. Push immediately. Write the post-merge memory file (§0.9) AFTER push lands.

Rollback: `git revert <sha>` if a phase breaks the pipeline. Surface to user; do NOT auto-restart.

### 0.1 Cross-phase invariants — apply to EVERY phase

These are load-bearing. Skipping any one re-introduces the failure modes Phase 4 exists to prevent.

**Pre-flight before any code:**
1. Re-read this ENTIRE plan top-to-bottom (Section 0 → M), not just your phase.
2. Re-read user auto-memory at `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/MEMORY.md`. Read every `phase_<N>_landing.md` from prior phases (1, 1.5, 1.6, 2, 3, 3.5, and any Phase 4 prior to yours). Read `smoke_2026-04-26_landing.md` and any newer smoke landings.
3. Read `feedback_structural_vs_containment.md`, `feedback_verification_before_completion.md`, `feedback_inflight_fixes_need_authorization.md`. These memories codify the user's collaboration norms; violating them is a halt condition.
4. Verify editable install: `python -c "import agent_team_v15; print(agent_team_v15.__file__)"` — must resolve under repo `src/`. If not, `pip install -e .` first.
5. **Verify every cited file:line in this plan still matches current source.** Citations are timestamped 2026-04-26. The codebase mutates between sessions. Use Read with the cited line + context. If ANY citation is stale: STOP. Update the plan with new line numbers before implementing. Document the drift in your end-of-phase memory.
6. Run the broader test slice covering touched files BEFORE starting work — must be green. If red, STOP and surface.
7. Confirm prior phase's smoke gate is green (or explicitly accept-failed by user).

**During implementation:**
8. **TDD discipline (NON-NEGOTIABLE):** write the failing test FIRST. Run it. Confirm it fails with the EXPECTED error — not a typo, not an import error. THEN implement. Per `superpowers:test-driven-development`.
9. **One phase per session.** No spillover. If a phase isn't done in a session, ship synthetic test fixtures as `pytest.mark.xfail` and pause. Memory-write the cliff edge so the next session can resume cleanly.
10. **Investigate yourself, do not trust the plan blindly.** When the plan says "modify file X at line Y" — go read X line Y, confirm the surrounding context still matches the plan's narrative. The plan was synthesized from the 2026-04-26 smoke; ground-truth always wins.
11. **Use Context7** (`mcp__context7__resolve-library-id`, then `mcp__context7__query-docs`) for ANY library / SDK / CLI / framework question. Never trust training data — APIs drift between minor versions. Required Context7 lookups are listed in §0.2..§0.8 below; you may add more.
12. **Use sequential-thinking MCP** (`mcp__sequential-thinking__sequentialthinking`) when:
    - Two primitives interact in a non-obvious way (e.g., audit-fix scope vs Phase 3 hook allowlist).
    - You discover a NEW gap not in the §C register.
    - The plan's approach hits unexpected friction (e.g., a precondition you assumed turns out to not hold).
    - You're about to make a design decision that wasn't explicitly resolved in §M.
13. **If you discover a NEW risk/gap:** STOP. Add it to §C with `[NEW — Phase 4.<N>]` annotation. Surface it to the user. Do NOT proceed silently.
14. **If a citation is stale or a primitive doesn't behave as the plan describes:** STOP. Update the plan. Document the drift in your end-of-phase memory.
15. **Use the smoke run-dir as ground truth.** `v18 test runs/m1-hardening-smoke-20260426-173745/` is gold. Cite specific artifacts in test fixtures (`WAVE_FINDINGS.json` for retry context, `telemetry/*.json` for wave success state, `codex-captures/*.log` for actual Codex behavior). Don't synthesize fixture data when real data is available.
16. **UPGRADE-only.** Every change must be either additive (new functions/fields with defaults preserving old behavior) OR config-gated (opt-in via `AuditTeamConfig` field with default = old behavior). NEVER ship a change that downgrades any existing test slice. Run `pytest tests/test_audit_fix_guardrails_phase{1,1_5,1_6,2,3,3_5}.py tests/test_wave_d_path_guard.py tests/test_agent_teams_backend.py` after every commit; all must stay green.

**Pre-merge gate (per phase):**
17. All ACs for the phase have a passing test that targets them.
18. Existing test slices (broader than touched files) still green.
19. Run the fast-forward harness: `& .\scripts\run-m1-fast-forward.ps1` — all 6 gates pass, `ready_for_full_smoke: true` in `fast-forward-report.json`.
20. Run the phase-specific verification gate listed in §K. If any gate fails, ROLL BACK per the phase's rollback plan.
21. Diff review: `git diff master~1...HEAD` — read every line you wrote one more time, looking specifically for: leftover debug logs, hardcoded values that should be config, error handlers that swallow context, accidental edits to files outside the phase's declared file list.

**Post-merge memory write (NON-NEGOTIABLE):**
22. Write `phase_4_<N>_landing.md` to `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/` capturing:
    - Actual function signatures shipped (may differ from plan).
    - Anything new you learned about the existing code.
    - Surprises: anything the plan got wrong.
    - Risks now closed (with how they were verified).
    - What the next phase MUST know.
    - Add the index entry to `MEMORY.md`.

### 0.2 Phase 4.1 — Wave self-verify scope-narrowing + per-wave service grading

**Goal:** §D — Wave B's self-verify runs `docker compose build api` only (not the full compose). Wave D's self-verify runs `docker compose build web` only. Wave T (full e2e) is the wave that runs the FULL stack. Each wave is graded on its OWN deliverable, not downstream waves' deliverables.

**Why this is the highest-leverage single fix:**
The 2026-04-26 smoke (`m1-hardening-smoke-20260426-173745`) shows Wave B retried 3 times, ALL graded on the FULL `docker compose build` (api + web). Retry 2 actually got `service=api` passing but failed on `service=web` because Wave D's frontend chassis (i18n, locales, components) didn't exist yet. Wave B should NEVER have been responsible for Wave D's deliverable.

**Pre-flight (in addition to §0.1):**
1. Verified citations as of 2026-04-26 (drift expected; grep to re-verify):
   * `src/agent_team_v15/wave_b_self_verify.py:98` — function `run_wave_b_acceptance_test(cwd, *, autorepair=True, timeout_seconds=600)` is the actual Wave B self-verify entry point.
   * `src/agent_team_v15/wave_b_self_verify.py:171` — calls `docker_build(cwd_path, compose_file, timeout=...)` which builds ALL services from the compose file. **Phase 4.1 must extend `docker_build`** with an optional `services: list[str] | None = None` argument (when set, passes the service list to `docker compose build <services>`).
   * **Wave D self-verify does NOT exist today.** Phase 4.1 must CREATE it: a NEW `src/agent_team_v15/wave_d_self_verify.py` module with `run_wave_d_acceptance_test`. Reuse `wave_b_self_verify.py` shape (compose sanity → docker_build → result with retry suffix). The Wave D dispatch site in `cli.py` (grep `wave_letter == "D"` or similar) must invoke it post-Wave-D.
   * `src/agent_team_v15/runtime_verification.py` Phase 6 functions — these are the post-all-waves runtime probe. NOT the same as per-wave self-verify; do NOT change Phase 6 semantics in this phase.
   * `src/agent_team_v15/cli.py` Wave B / Wave D / Wave T dispatch sites — grep for `wave_letter` in cli.py.
2. Read `v18 test runs/m1-hardening-smoke-20260426-173745/.agent-team/milestones/milestone-1/WAVE_FINDINGS.json` — ground-truth showing per-service `(file: api|web)` failure attribution. The system already CAPTURES per-service info; Phase 4.1 just gates the SPAWNED command on the wave's own service.
3. Read the Wave B prompt at `v18 test runs/m1-hardening-smoke-20260426-173745/.agent-team/codex-captures/milestone-1-wave-B-prompt.txt` — confirm "Wave D" appears 0 times. This is Phase 4.7's domain; Phase 4.1 coexists with the unfixed prompt.
4. **CRITICAL — fixture preservation:** Before any code change, copy load-bearing smoke artifacts to `tests/fixtures/smoke_2026_04_26/`. Phase 4.1 implementer is responsible for this (subsequent phases inherit the frozen copies). Specifically copy:
   * `WAVE_FINDINGS.json`
   * `STATE.json` (excerpt — `milestone_progress` + `milestone_anchor_path` keys)
   * `AUDIT_REPORT.json` (full)
   * `telemetry/milestone-1-wave-A.json` and `milestone-1-wave-B.json`
   * `codex-captures/milestone-1-wave-B-prompt.txt`
   * `codex-captures/milestone-1-wave-B-protocol.log` (if size permits, else excerpt of turn/start payloads)
   * `apps/web/src/middleware.ts` (the canonical scaffold-stub example for Phase 4.7)
   These become the test-fixture root. Plan-level invariant: never delete the smoke run-dir without first verifying `tests/fixtures/smoke_2026_04_26/` has frozen copies of every artifact referenced by `test_replay_smoke_*` fixtures.
5. Run baseline tests: `pytest tests/wave_executor/ tests/test_v18_phase2_wave_engine.py tests/test_v18_specialist_prompts.py tests/test_runtime_verification_block.py tests/test_v18_wave_t.py -p no:cacheprovider --tb=short` — green baseline.

**Required Context7 lookups:**
* `/docker/compose` — `docker compose build` per-service argument syntax (`docker compose build <service-name>`); `docker compose up <service-name>`; the `--no-deps` flag for excluding healthcheck deps. Lock the canonical CLI shape so Phase 4.1's spawned commands don't break on minor docker-compose version drift.
* `/docker/buildx` — confirm `docker buildx build` vs `docker compose build` differences (Phase 4.1 may want to drop down to `docker buildx` for per-service builds if compose-based per-service has hidden dependency-pull behavior).

**TDD sequence (strict order):**
1. Create `tests/test_pipeline_upgrade_phase4_1.py` with these fixtures (all initially fail with `AttributeError` on the not-yet-existing functions):
   * `test_wave_b_self_verify_runs_only_api_service` — mock `subprocess.run`; call `wave_b_self_verify`; assert the spawned command is `["docker", "compose", "build", "api"]` (or equivalent), NOT the full compose build.
   * `test_wave_d_self_verify_runs_only_web_service` — symmetric for Wave D.
   * `test_wave_t_self_verify_runs_full_stack` — Wave T (e2e) MUST still build everything; ensure the existing full-stack behavior is preserved.
   * `test_wave_b_self_verify_failure_message_includes_service_attribution` — the `<previous_attempt_failed>` payload (consumed by Phase 4.2) must already carry `service=api` so retry feedback can be wave-specific.
   * `test_wave_b_self_verify_skipped_when_wave_b_did_not_run` — if wave_result.success is None (didn't run), self-verify is no-op (defensive).
   * `test_per_wave_self_verify_respects_stack_contract_ports` — pull `STACK_CONTRACT.json`'s service names; if a non-default service name is configured, the per-wave command uses it.
2. Implement files in this order (each file's tests should flip green after that file's commit):
   1. `src/agent_team_v15/wave_b_self_verify.py` — extract module-level helper `_resolve_per_wave_service_target(wave_letter: str, stack_contract: dict | None) -> list[str]` (returns the list of compose services this wave is responsible for; e.g. `["api"]` for B, `["web"]` for D, `["api", "web"]` for T). The current `docker_build(cwd_path, compose_file, timeout=...)` utility (in this same module or a sibling — grep for `def docker_build`) extends to `docker_build(cwd_path, compose_file, *, timeout=..., services: list[str] | None = None)`. When `services` is non-None, it's passed verbatim as positional args to `docker compose build`. `run_wave_b_acceptance_test` calls it with `services=_resolve_per_wave_service_target("B", stack_contract)`.
   2. `src/agent_team_v15/wave_d_self_verify.py` (**NEW MODULE**) — mirror `wave_b_self_verify.py`'s shape: `WaveDVerifyResult` dataclass + `run_wave_d_acceptance_test(cwd, *, autorepair=True, timeout_seconds=600) -> WaveDVerifyResult` + a `_build_retry_prompt_suffix` for Wave-D-specific retry feedback (Phase 4.2 will replace this with the structured payload). Calls the same `docker_build` with `services=["web"]`.
   3. `src/agent_team_v15/cli.py` — Wave D dispatch site invokes `run_wave_d_acceptance_test` post-Wave-D-completion. Grep for the existing Wave D handling (e.g., `_load_wave_d_failure_roots` at ~line 948 — the post-Wave-D path lives nearby).
   4. `src/agent_team_v15/config.py` — add `AuditTeamConfig.per_wave_self_verify_enabled: bool = True` (kill-switch; default True). When False, restore old full-compose behavior (preserves rollback).
   5. `tests/test_pipeline_upgrade_phase4_1.py` — fixtures flip green.
3. After each file commit, run `pytest tests/test_pipeline_upgrade_phase4_1.py tests/wave_executor/ -x --tb=short` — STOP at first unexpected red.

**Pre-merge gate (Phase 4.1 specific, in addition to §0.1 §17-21):**
1. All 6 fixtures + existing test slice green.
2. Fast-forward harness all 6 gates pass.
3. **Replay smoke evidence:** Use a unit test that loads `WAVE_FINDINGS.json` from the 2026-04-26 smoke and asserts: (a) the new `_resolve_per_wave_service_target("B", ...) == ["api"]`; (b) had Phase 4.1 been live, retry 2 of Wave B (which got `service=api` passing) would have been declared Wave-B-self-verify-passed and the milestone would have advanced to Wave D.
4. **No full M1 smoke required for Phase 4.1** — but a partial run-dir simulation (Wave A + Scaffold + Wave B with Phase 4.1's narrowed self-verify) should land cleanly.

**Memory write after Phase 4.1 merge (`phase_4_1_landing.md`):**
* Actual `_resolve_per_wave_service_target` signature shipped (may differ from plan).
* Whether `docker compose build <service>` actually skips dep services or pulls them (Context7 finding).
* Any STACK_CONTRACT field used for service-name resolution.
* Risks now closed: #23 (self-verify scope mismatch).
* Note for Phase 4.2: the `<previous_attempt_failed>` payload now carries `service=api` (or `web`); Phase 4.2 must consume this attribution.
* Any NEW risks discovered (annotate §C with `[NEW — Phase 4.1]`).

### 0.3 Phase 4.2 — Strong deterministic retry feedback

**Pre-condition:** Phase 4.1 merged + smoke clean. `phase_4_1_landing.md` exists.

**Goal:** §E — Replace the one-line `<previous_attempt_failed>` payload with a structured, deterministic, LLM-cost-zero feedback block containing: full stderr (truncated), parsed compile errors with file:line, unresolved-import scan from modified files, files_modified list, and progressive-learning markers (e.g., "your previous retry got `service=api` passing; now `service=web` fails").

**Why:**
The 2026-04-26 smoke's retry payload (per `codex-captures/milestone-1-wave-B-protocol.log`) was literally:
```
<previous_attempt_failed>
Docker build failures (per service):
target api: failed to solve: process "/bin/sh -c pnpm --filter api build" did not complete successfully: exit code: 1
</previous_attempt_failed>
```
That's the entire actionable feedback. Codex retried twice with this binary signal and failed both times. Its `final_agent_message` in retry-2 says it couldn't even run `docker compose build` in its sandbox due to a Windows lock-file conflict, so it was completely blind to what failed.

**Pre-flight (in addition to §0.1):**
1. Verified citations as of 2026-04-26 (drift expected; grep to re-verify):
   * `src/agent_team_v15/wave_b_self_verify.py:83-95` — function `_build_retry_prompt_suffix(error_summary: str) -> str` is the ACTUAL builder of the `<previous_attempt_failed>` block. Phase 4.2's primary work is to REPLACE this with `retry_feedback.build_retry_payload(...)` (or augment it to call the new module). Phase 4.1 may have already touched this file (for Wave D self-verify creation) — coordinate with phase_4_1_landing.md.
   * Phase 4.1 created `src/agent_team_v15/wave_d_self_verify.py` with its own `_build_retry_prompt_suffix`; Phase 4.2 must replace BOTH (Wave B's and Wave D's) with calls to the new shared `retry_feedback.build_retry_payload`.
   * `src/agent_team_v15/fix_executor.py` — `_parse_playwright_failures_detailed` (Phase 2 lock) is the canonical structured-error parser. Phase 4.2 may reuse its regex shapes.
   * `src/agent_team_v15/fix_executor.py` `_classify_fix_features` (Phase 3.5) — the path-shape regex `_PATH_SHAPED_RE` is reusable for unresolved-import scanning.
2. Read the actual smoke retry prompts: `tests/fixtures/smoke_2026_04_26/codex-captures/milestone-1-wave-B-protocol.log` (frozen by Phase 4.1) — find the `OUT` lines for `turn/start` and grep for `<previous_attempt_failed>`. 3 turns: turn 0 is original (no retry block); turns 1+2 are retries with the thin block. The current payload is ~150 bytes — observed verbatim:
   ```
   <previous_attempt_failed>
   Your previous Wave B output failed acceptance testing. ...
   Docker build failures (per service):
   target api: failed to solve: process "/bin/sh -c pnpm --filter api build" did not complete successfully: exit code: 1
   Requirements for this retry:
   </previous_attempt_failed>
   ```
   Phase 4.2's new payload must be ≥10x richer (≥1.5 KB) but bounded at 12 KB.
3. Read `tests/fixtures/smoke_2026_04_26/WAVE_FINDINGS.json` — per-attempt failure messages already carry `service=api` / `service=web` attribution. Phase 4.2 threads these into the new payload's progressive-signal computation.
4. Run baseline: `pytest tests/test_pipeline_upgrade_phase4_1.py tests/wave_executor/ tests/test_v18_phase2_wave_engine.py tests/test_runtime_verification_block.py` — green.

**Required Context7 lookups:**
* `/microsoft/typescript` — the canonical `tsc --noEmit --pretty false` output format for parsing `(file):(line):(col) error TSXXXX: <message>`. Lock the regex against current TypeScript version. Do NOT trust training data — check the latest minor.
* `/microsoft/vscode-eslint` (or `/eslint/eslint`) — `eslint --format json` schema; rules out Phase 4.2 reusing eslint output as one of the structured-error sources.
* `/nestjs/docs` — confirm Nest's compile error format if different from raw tsc.
* `/vercel/next.js` — Next.js build error format (the `next build` command's stderr structure when frontend compilation fails).
* `/docker/buildkit` — buildkit's stderr format on `RUN <command>` failures (the actual structure of the "failed to solve: process X did not complete successfully" line, which Phase 4.2 must extract the inner command's stderr from).

**TDD sequence:**
1. Create `tests/test_pipeline_upgrade_phase4_2.py`:
   * `test_retry_payload_includes_full_stderr_truncated_to_5kb` — synthesize a 50KB stderr; payload contains the last 5KB with a "...(truncated, full N bytes)" marker.
   * `test_retry_payload_extracts_typescript_errors_with_file_line` — feed canonical tsc output; payload contains `[{"file": "...", "line": N, "message": "..."}]` for each.
   * `test_retry_payload_lists_unresolved_imports_from_modified_files` — synthesize a TS file that imports `../missing/file`; payload contains `unresolved_imports: [...]`.
   * `test_retry_payload_includes_progressive_signal_when_partial_progress` — when retry-1 had `service=api` failing and retry-2 has `service=web` failing, payload says "Previous retry: api FAILED. This retry: api PASSED, web FAILED. Focus on: web."
   * `test_retry_payload_passes_through_when_first_attempt` — first dispatch has no retry block (regression-safe).
   * `test_retry_payload_respects_max_size_limit` — total payload bounded at e.g. 12KB so prompt doesn't bloat.
   * `test_retry_payload_handles_codex_sandbox_could_not_run_docker_case` — the smoke showed Codex's sandbox can't run docker compose build; payload must give Codex enough signal to fix WITHOUT re-running the failing command itself.
2. Implement files:
   1. `src/agent_team_v15/retry_feedback.py` (**NEW**) — module with:
      * `extract_typescript_errors(stderr: str) -> list[dict]` — regex-based; tested against Context7-confirmed tsc format.
      * `extract_buildkit_inner_stderr(stderr: str) -> str` — strips the "failed to solve: process X did not complete successfully" wrapper to expose the inner command's output.
      * `extract_nextjs_build_errors(stderr: str) -> list[dict]` — Context7-locked Next.js build error format.
      * `scan_unresolved_imports(modified_files: list[str], project_root: str) -> list[dict]` — AST-light walker (regex on `import ... from '...'`); checks each import target exists on disk. Reuses `_PATH_SHAPED_RE` from `fix_executor.py` (Phase 3.5).
      * `compute_progressive_signal(this_attempt: dict, prior_attempts: list[dict]) -> str` — produces the "previous: X. now: Y. focus: Z." line.
      * `build_retry_payload(*, stderr: str, modified_files: list[str], project_root: str, prior_attempts: list[dict], wave_letter: str, max_size_bytes: int = 12000) -> str` — composes the new `<previous_attempt_failed>` block. Single source of truth; both Wave B and Wave D self-verify call it.
   2. `src/agent_team_v15/wave_b_self_verify.py` — replace the body of `_build_retry_prompt_suffix(error_summary)` with a thin shim: when `config.audit_team.strong_retry_feedback_enabled` is True, build a `RetryContext` from the existing `WaveBVerifyResult` (violations, build_failures, error_summary, modified_files from telemetry, prior attempts) and call `retry_feedback.build_retry_payload`. When False, fall back to the original ~150-byte string (preserves rollback for one release cycle).
   3. `src/agent_team_v15/wave_d_self_verify.py` (NEW from Phase 4.1) — same shim treatment as Wave B.
   4. `src/agent_team_v15/config.py` — add `AuditTeamConfig.strong_retry_feedback_enabled: bool = True`.
3. After each file commit, run `pytest tests/test_pipeline_upgrade_phase4_2.py tests/test_pipeline_upgrade_phase4_1.py -x --tb=short`.

**Pre-merge gate (Phase 4.2 specific):**
1. All Phase 4.2 fixtures green; Phase 4.1 + earlier fixtures still green.
2. **Replay smoke evidence:** Unit test loads the actual retry payload from `codex-captures/milestone-1-wave-B-protocol.log` and runs the new `build_retry_payload` over what WOULD have been available at retry-1 time; assert the new payload is at least 10x richer (>2KB vs current ~150B) and includes specific actionable items (file paths from buildkit stderr).
3. **Fast-forward harness gate** — all 6 gates pass.
4. **Phase 4.1 fixtures** — `pytest tests/test_pipeline_upgrade_phase4_1.py` green.
5. **No full M1 smoke required.** Synthetic stress test is sufficient; full smoke happens after Group A complete (post Phase 4.3).

**Memory write (`phase_4_2_landing.md`):**
* Actual `retry_feedback` API surface shipped.
* Context7-confirmed TypeScript / buildkit / Next.js error formats (with version checked).
* Risks now closed: #24 (one-line retry feedback). Risk #29 (Codex sandbox locking) classified as KNOWN LIMITATION mitigated by feedback richness.
* Note for Phase 4.3: the new payload structure is consumed by retry; Phase 4.3's audit wave-awareness should NOT duplicate the structured extraction — instead, audit findings should reference the same `extract_typescript_errors` / `scan_unresolved_imports` outputs where applicable.

### 0.4 Phase 4.3 — Audit wave-awareness (owner_wave tagging + DEFERRED status)

**Pre-condition:** Phases 4.1 + 4.2 merged + smoke clean.

**Goal:** §F — Tag every audit finding with `owner_wave` (B/D/C/T/scaffold/wave-agnostic). Findings whose `owner_wave` hasn't executed get DEFERRED status, not FAIL. Convergence ratio computed only over executed waves' findings. Audit-fix dispatch (when Phase 4.5 lifts Risk #1) only fires for findings where `owner_wave` HAS executed AND failed — never for findings whose owner-wave is still pending.

**Why:**
The 2026-04-26 smoke produced 46 findings (11 critical, 17 high). Reclassifying by ownership:
* **Findings #1-4 (critical, frontend chassis):** middleware stub, layout hardcoded `lang='en'`, missing `i18n/index.ts`, missing locale files. Owner = **Wave D**, never ran.
* **Finding #5 (critical):** `packages/api-client/` missing. Owner = **Wave C**, never ran.
* **Finding #10 (critical):** apps/web Dockerfile build fails. Owner = downstream of Wave D missing.
* **5/11 critical findings are downstream of "later wave never ran."** The audit graded them as FAIL when they should have been DEFERRED (Wave D / Wave C never executed for milestone-1).

The convergence ratio of 0/1 in this smoke is inflated. With Phase 4.3, the convergence ratio would be computed over (executed waves' findings only) = (Wave A + Scaffold + Wave B) findings = 3 critical findings (duplicate prisma, shadow d.ts, bcrypt declaration). Still a fail, but with a much narrower fix-PRD.

**Pre-flight (in addition to §0.1):**
1. Re-verify citations: `audit_team.py` `_score_findings` / convergence ratio computation; `audit_models.py` `Finding` / `AuditFinding` dataclass; `cli.py` `_convert_findings`; `fix_executor.py` `_classify_fix_features` (Phase 3.5 grouping).
2. Read `v18 test runs/m1-hardening-smoke-20260426-173745/.agent-team/AUDIT_REPORT.json` — load all 46 findings; manually tag each with owner_wave; this becomes Phase 4.3's primary test fixture.
3. Read `v18 test runs/m1-hardening-smoke-20260426-173745/.agent-team/MASTER_PLAN.json` — the wave-split design (which waves SHOULD run for milestone-1's full_stack template). This is the source-of-truth for "which waves should produce which paths."
4. Run baseline: `pytest tests/test_audit_fix_guardrails_phase{2,3,3_5}.py tests/test_evidence_ledger.py tests/test_pipeline_upgrade_phase4_1.py tests/test_pipeline_upgrade_phase4_2.py` — green.

**Required Context7 lookups:**
* No new library lookups required for Phase 4.3 (pure-Python pipeline logic). But VERIFY by re-checking `/anthropics/claude-code` for any updates to the audit team's prompt templates that may have shipped between Phase 3 and now.

**TDD sequence:**
1. Create `tests/test_pipeline_upgrade_phase4_3.py`:
   * `test_owner_wave_resolver_apps_api_to_wave_b` — `resolve_owner_wave("apps/api/src/foo.ts") == "B"`.
   * `test_owner_wave_resolver_apps_web_to_wave_d` — apps/web/* → Wave D.
   * `test_owner_wave_resolver_packages_api_client_to_wave_c` — packages/api-client/* → Wave C.
   * `test_owner_wave_resolver_apps_web_locales_to_wave_d` — apps/web/locales/* → Wave D (NOT Wave B even though locales is in the Wave B "Allowed file globs").
   * `test_owner_wave_resolver_prisma_to_wave_b` — prisma/* → Wave B.
   * `test_owner_wave_resolver_e2e_tests_to_wave_t` — e2e/tests/* → Wave T.
   * `test_owner_wave_resolver_falls_back_to_wave_agnostic` — paths not matching any wave (e.g., `.gitignore`, root `package.json`) → "wave-agnostic".
   * `test_finding_status_DEFERRED_when_owner_wave_did_not_run` — given a finding with owner_wave="D" and a wave_state where Wave D status is "PENDING", finding.status = DEFERRED.
   * `test_finding_status_FAIL_when_owner_wave_ran_and_failed` — owner_wave="B" + Wave B status "FAILED" → finding.status = FAIL (today's behavior).
   * `test_convergence_ratio_excludes_deferred_findings` — synthesize 46 findings (10 critical, 5 deferred); convergence over (10 - 5) = 5 only.
   * `test_replay_smoke_2026_04_26_findings_classification` — load real `AUDIT_REPORT.json`; assert ≥4 of 11 critical findings get `owner_wave="D"` (Wave D never ran in this smoke); assert convergence_ratio_filtered > 0 (since the 3 real Codex bugs are not all of M1 scope).
2. Implement files:
   1. `src/agent_team_v15/wave_ownership.py` (NEW) — module with:
      * `WAVE_PATH_OWNERSHIP: dict[str, str]` — module-level constant. Key = path glob (e.g., `"apps/api/**"`); value = wave letter (e.g., `"B"`).
      * `resolve_owner_wave(path: str) -> str` — returns wave letter or `"wave-agnostic"`.
      * `is_owner_wave_executed(wave_letter: str, run_state: RunState) -> bool` — checks STATE.json's wave-completion tracking.
   2. `src/agent_team_v15/audit_models.py` — `Finding` and `AuditFinding` gain `owner_wave: str = "wave-agnostic"` (default preserves backward-compat). `from_dict` populates from `wave_ownership.resolve_owner_wave(primary_file)` if owner_wave not present.
   3. `src/agent_team_v15/audit_team.py` — convergence ratio computation filters deferred findings.
   4. `src/agent_team_v15/fix_executor.py` — `_classify_fix_features` skips features whose every member finding has owner_wave deferred. Logs `[FIX-DEFERRED] feature N (name) all findings deferred to wave <X>`.
   5. `src/agent_team_v15/cli.py` `_convert_findings` — propagates owner_wave into Finding.
   6. `src/agent_team_v15/config.py` — `AuditTeamConfig.audit_wave_awareness_enabled: bool = True`.
3. After each file commit, run `pytest tests/test_pipeline_upgrade_phase4_3.py tests/test_audit_fix_guardrails_phase{2,3,3_5}.py -x`.

**Pre-merge gate (Phase 4.3 specific):**
1. All Phase 4.3 fixtures green; Phase 1-3.5 + 4.1 + 4.2 fixtures still green.
2. **Replay smoke evidence:** Unit test loads `AUDIT_REPORT.json`, runs Phase 4.3's wave-aware classifier, asserts ≥4 critical findings get owner_wave="D" or "C" and become DEFERRED. Compute new convergence ratio; assert > 0.0 (strictly better than the smoke's 0.0).
3. **Fast-forward harness** all 6 gates pass.
4. **Full M1 smoke recommended:** Phase 4.3 changes how convergence is computed; this affects the audit team's terminate-or-continue decision. A fresh M1 smoke confirms no regression on the convergence-fail path.

**Memory write (`phase_4_3_landing.md`):**
* `WAVE_PATH_OWNERSHIP` table shipped (the master ownership map).
* Whether `_classify_fix_features` skip semantics chose "skip whole feature" vs "skip per-finding."
* Risks now closed: #25 (audit wave-blindness), #30 (convergence ratio over un-run waves).
* Note for Phase 4.5: when Risk #1 is lifted, the audit-fix dispatch must respect DEFERRED status — never dispatch for a finding whose owner_wave is DEFERRED. Phase 4.3 sets up this gating; Phase 4.5 enforces it.

### 0.5 Phase 4.4 — failure_reason on wave-fail + deterministic forensics

**Pre-condition:** Phases 4.1 + 4.2 + 4.3 merged + smoke clean.

**Goal:** §G — Close Risks #18 and #19. Risk #18: pass `failure_reason="wave_failed"` (or wave-letter-specific) at the wave-fail FAILED-mark site (`cli.py:4959`), symmetric to Phase 1.6's audit-fail wiring at `cli.py:7631`. Risk #19: gate `_run_failed_milestone_audit_if_enabled` on `wave_result.success` — on wave-fail, emit a deterministic `WAVE_FAILURE_FORENSICS.json` from already-captured signal (Phase 4.1's per-service self-verify error + Phase 4.2's structured retry feedback + Phase 4.3's owner_wave-tagged findings) and skip the LLM forensics audit.

**Why:**
The 2026-04-26 smoke's `STATE.json::milestone_progress.milestone-1` is `{"status": "FAILED"}` — no `failure_reason`. Operators reading STATE post-mortem can't distinguish wave-fail from audit-fail. Phase 1.6 added the field but only wired it via `_handle_audit_failure_milestone_anchor`; the wave-fail path doesn't pass it.

The smoke also burned ~$5-8 on the failed-milestone forensics audit + 14-min Phase 6 repair Bash + 2 review-recovery cycles, producing low-signal forensics whose verdict ("M1 still FAILED") was foregone from the wave-fail itself. This is wasted spend.

**Pre-flight (in addition to §0.1):**
1. Verified citations as of 2026-04-26 (LINE NUMBERS DRIFT; grep is canonical):
   * Wave-fail FAILED-mark site — grep `update_milestone_progress.*FAILED` in `cli.py`. As of 2026-04-26 the wave-fail call lived around `cli.py:4959` but Phase 1.6 + later commits moved it. Find the call inside the per-milestone wave-execution loop where `wave_result.success is False`.
   * `cli.py` `_run_failed_milestone_audit_if_enabled` — at line 7559 as of 2026-04-26 commit `1c46445`. Grep canonical.
   * `cli.py` `_run_audit_fix_unified` — at line 7116. Grep canonical.
   * `cli.py` `_handle_audit_failure_milestone_anchor` — at line 7602. Grep canonical.
2. Read `tests/fixtures/smoke_2026_04_26/STATE.json` (Phase 4.1 froze) — confirm `milestone_progress.milestone-1 = {"status": "FAILED"}` with NO `failure_reason`.
3. Read `phase_1_6_landing.md` "Reason values that flow into the field today" table — Phase 4.4 adds a fourth value: `"wave_failed"` (or wave-letter-specific like `"wave_b_failed"`).
4. Read `phase_1_landing.md` "Open follow-ups" — note item: "audit_max_reaudit_cycles=2 fires 2 cycles by default." Phase 4.4 must skip BOTH cycles on wave-fail (not just cycle 1).
5. Run baseline: all prior phase tests + `tests/test_audit_fix_guardrails_phase1_6.py`.

**Required Context7 lookups:**
* No new library lookups for Phase 4.4 (pure-Python orchestration logic).

**TDD sequence:**
1. Create `tests/test_pipeline_upgrade_phase4_4.py`:
   * `test_update_milestone_progress_wave_fail_writes_failure_reason` — call `update_milestone_progress(state, "milestone-1", "FAILED", failure_reason="wave_b_failed")`; assert `state.milestone_progress["milestone-1"]["failure_reason"] == "wave_b_failed"`.
   * `test_wave_fail_mark_site_passes_failure_reason` — mock the wave-fail FAILED-mark in cli.py; assert it calls `update_milestone_progress` with the wave letter.
   * `test_run_failed_milestone_audit_if_enabled_skipped_on_wave_fail` — mock wave_result.success=False; assert the audit pass is NOT invoked; assert `WAVE_FAILURE_FORENSICS.json` IS written.
   * `test_wave_failure_forensics_json_schema` — load the synthesized forensics JSON; assert it has the canonical schema (failed_wave_letter, retry_count, self_verify_error, files_modified, codex_protocol_log_tail, docker_compose_ps_state, owner_wave_findings_count_per_wave).
   * `test_wave_failure_forensics_includes_phase4_3_owner_wave_attribution` — owner_wave-tagged finding counts are part of the forensics output.
   * `test_run_failed_milestone_audit_if_enabled_still_fires_on_convergence_fail` — wave_result.success=True (no wave-fail) → audit pass IS invoked (unchanged behavior).
   * `test_replay_smoke_2026_04_26_skips_audit_pass_on_wave_fail` — using the smoke's actual STATE.json + WAVE_FINDINGS.json, simulate Phase 4.4's gating; assert the audit pass would NOT have been dispatched, saving ~$5-8.
2. Implement files:
   1. `src/agent_team_v15/wave_failure_forensics.py` (NEW) — module with:
      * `WaveFailureForensics: dataclass` — schema for the JSON.
      * `build_wave_failure_forensics(*, run_state: RunState, wave_findings: dict, telemetry: dict, codex_protocol_path: pathlib.Path | None, docker_compose_ps: str | None) -> WaveFailureForensics` — composes the forensics from already-captured signal.
      * `write_wave_failure_forensics(forensics: WaveFailureForensics, agent_team_dir: pathlib.Path) -> pathlib.Path` — writes to `.agent-team/WAVE_FAILURE_FORENSICS.json`.
   2. `src/agent_team_v15/cli.py:4959` — pass `failure_reason="wave_b_failed"` (or letter-specific) to `update_milestone_progress`.
   3. `src/agent_team_v15/cli.py:7437` `_run_failed_milestone_audit_if_enabled` — gate on `wave_result.success`. On wave-fail, call `wave_failure_forensics.build_wave_failure_forensics` + `write_wave_failure_forensics` and return early.
   4. `src/agent_team_v15/config.py` — `AuditTeamConfig.failed_milestone_audit_on_wave_fail_enabled: bool = False` (kill-switch; default OFF means we DO skip on wave-fail). Flip to True to restore old behavior.
3. After each file commit, run all Phase 4.x + Phase 1.6 fixtures.

**Pre-merge gate (Phase 4.4 specific):**
1. All Phase 4.4 fixtures green.
2. **Replay smoke:** the synthesized `WAVE_FAILURE_FORENSICS.json` for the 2026-04-26 smoke must contain:
   * `failed_wave_letter == "B"`
   * `retry_count == 3`
   * `self_verify_error` matching the WAVE_FINDINGS retry=2 entry (`service=web` after Phase 4.1's narrowing)
   * `owner_wave_findings_count_per_wave: {"B": 3, "D": 4, "C": 1, "wave-agnostic": 3, ...}` (using Phase 4.3's classification)
3. **Fast-forward harness** all 6 gates pass.
4. **No full M1 smoke required** — synthesized forensics is sufficient verification.

**Memory write (`phase_4_4_landing.md`):**
* `WaveFailureForensics` schema shipped.
* Cost savings observed (estimated $5-8 per wave-fail).
* Risks now closed: #18 (failure_reason on wave-fail), #19 (deterministic forensics).
* Note for Phase 4.5: when Phase 4.5 lifts Risk #1 to allow audit-fix on wave-fail, the wave-fail forensics path becomes a fallback for runs where the audit-fix lift is config-disabled OR audit-fix loop fails to recover.

### 0.6 Phase 4.5 — Lift Risk #1 + re-self-verify after audit-fix (the recovery cascade)

**Pre-condition:** Phases 4.1-4.4 merged + smoke clean.

**Goal:** §H — Conditionally lift Phase 1 Risk #1 (skip audit-fix on wave-fail) when ALL safety nets are armed (Phase 1 anchor + Phase 2 lock + Phase 3 hook + Phase 3.5 ship-block + Phase 4.3 wave-awareness). When lifted, audit-fix runs on wave-fail with strict guardrails. After audit-fix loop terminates non-FAILED, **re-run self-verify** (Phase 4.1's narrowed self-verify); if passes, transition milestone FAILED→COMPLETE/DEGRADED; if still fails, anchor restore + final FAILED-mark.

**Why:**
The 2026-04-26 smoke produced 46 specific actionable audit findings (3-5 of which are real Codex bugs after Phase 4.3 wave-aware filtering). Audit-fix could attempt fixes on these 3-5 findings UNDER guardrails (Phase 1 anchor protects against divergence; Phase 3 hook scopes each dispatch). With Phase 4.1's narrowed self-verify, the audit-fix recovery only needs to fix the 3 real Codex bugs to pass `docker compose build api`. Then milestone advances, Wave D runs, Wave C runs, milestone passes.

But Phase 1 Risk #1 short-circuits this entire path. It was correct stop-gap protection in early Phase 1 (before anchor + lock + hook were live). After Phase 3.5 + Phase 4.3, it's obsolete — the safety nets ARE the recovery enabler.

**Pre-flight (in addition to §0.1):**
1. Re-verify citations: `cli.py` `_run_audit_fix_unified` Risk #1 short-circuit (grep for `wave_result.success is False`); Phase 1's `_handle_audit_failure_milestone_anchor` (line drift expected).
2. Read `phase_1_landing.md` "Risks closed by Phase 1" — Risk #1 fixture is locked at `tests/test_audit_fix_guardrails_phase1.py::test_run_audit_fix_unified_skipped_when_wave_failed`. This fixture asserts the OLD behavior (unconditional short-circuit on wave-fail). Phase 4.5 contract for this fixture:
   * **Rename** it to `test_run_audit_fix_unified_short_circuits_when_safety_nets_disabled` (the OLD behavior is now the degraded-config branch).
   * **Update** the body to set `config.audit_team.lift_risk_1_when_nets_armed = True` AND `config.audit_team.milestone_anchor_enabled = False` (one safety net disabled → degraded config → short-circuit fires). Assert the same `([], 0.0)` return as before.
   * **Add** the two new fixtures (`test_run_audit_fix_unified_skipped_when_safety_nets_disabled`, `test_run_audit_fix_unified_runs_on_wave_fail_when_safety_nets_armed`) listed in §0.6.
   * The Phase 1 landing memory's "Risks closed by Phase 1 — Risk #1" entry needs an update note: "Phase 4.5 conditionally lifted Risk #1 when all safety nets armed; old behavior preserved as degraded-config fallback."
   * Run `pytest tests/test_audit_fix_guardrails_phase1.py -k test_run_audit_fix_unified` after the rename — must pass.
3. Read `phase_3_landing.md` "Multi-matcher resolution observed" — confirm the deny>ask>allow contract still holds. Phase 4.5's lift relies on Phase 3 hook DENYING out-of-scope writes.
4. Read `tests/test_hook_multimatcher_conflict.py` — Phase 4.5 must NOT break this fixture.
5. Run baseline: ALL Phase 1-3.5 + Phase 4.1-4.4 fixtures.

**Required Context7 lookups:**
* `/anthropics/claude-code` — re-verify the multi-matcher deny>ask>allow contract still holds at the current Claude Code version. Phase 4.5's safety argument depends on Phase 3 hook denying out-of-scope writes; if Claude Code's resolution semantics changed, the lift is unsafe.

**TDD sequence:**
1. Create `tests/test_pipeline_upgrade_phase4_5.py`:
   * `test_run_audit_fix_unified_skipped_when_safety_nets_disabled` — when `milestone_anchor_enabled=False` OR audit-fix-path-guard not in `.claude/settings.json`, Risk #1 short-circuit STILL fires (preserves Phase 1 behavior in degraded config).
   * `test_run_audit_fix_unified_runs_on_wave_fail_when_safety_nets_armed` — anchor + lock + hook all armed → audit-fix runs on wave_result.success=False.
   * `test_audit_fix_dispatch_skips_features_whose_findings_are_DEFERRED` — Phase 4.3 wave-awareness gate: features whose ALL findings have owner_wave_deferred get `[FIX-DEFERRED]` log line, no dispatch.
   * `test_re_self_verify_after_audit_fix_terminates_non_failed` — mock audit-fix loop terminating with COMPLETE; assert `wave_b_self_verify` is re-invoked (Phase 4.1 narrowed); if passes, milestone FAILED→COMPLETE.
   * `test_re_self_verify_failure_triggers_anchor_restore` — mock audit-fix terminating COMPLETE but re-self-verify failing; assert anchor restore fires + `failure_reason="audit_fix_did_not_recover_build"`.
   * `test_audit_fix_on_wave_fail_writes_failure_reason_audit_fix_recovery_attempt` — `failure_reason` at audit-fix entry = `"wave_fail_recovery_attempt"`; on success `"wave_fail_recovered"`; on failure `"audit_fix_did_not_recover_build"`.
   * `test_replay_smoke_2026_04_26_audit_fix_dispatches_only_3_real_codex_features` — using smoke's AUDIT_REPORT + Phase 4.3 owner_wave classification, assert audit-fix would dispatch only the 3 real Codex bug features (duplicate prisma, shadow d.ts, bcrypt declaration); 4 frontend chassis features are DEFERRED (Wave D's job, never ran).
2. Implement files:
   1. `src/agent_team_v15/cli.py` `_run_audit_fix_unified` — replace Risk #1 short-circuit with conditional gate.
   2. `src/agent_team_v15/wave_b_self_verify.py` and `src/agent_team_v15/wave_d_self_verify.py` (created by Phase 4.1) — expose `run_wave_b_acceptance_test` and `run_wave_d_acceptance_test` as callable from cli.py for re-self-verify after audit-fix loop terminates non-FAILED.
   3. `src/agent_team_v15/cli.py` `_run_audit_loop` — after loop terminates non-FAILED with `wave_result.success` having been False on entry, re-invoke per-wave self-verify; on pass, update milestone status COMPLETE; on fail, anchor restore + FAILED-mark.
   4. `src/agent_team_v15/fix_executor.py` `_classify_fix_features` — skip features all-DEFERRED (Phase 4.3 wired the field; Phase 4.5 gates the dispatch).
   5. `src/agent_team_v15/config.py` — `AuditTeamConfig.lift_risk_1_when_nets_armed: bool = True` (kill-switch).
3. After each file commit, run all Phase 1-3.5 + 4.1-4.4 + 4.5 fixtures. Pay special attention to `test_run_audit_fix_unified_skipped_when_safety_nets_disabled` — if Phase 1's old fixture breaks, you've over-lifted.

**Pre-merge gate (Phase 4.5 specific):**
1. ALL prior phase fixtures + Phase 4.5 fixtures green.
2. **Replay smoke:** synthesize a "Phase 4.5 timeline" for the 2026-04-26 smoke: Wave B fails → audit runs → 3 Codex features classified for fix → dispatch with anchor armed → re-audit → re-self-verify (api only) → if passes, milestone advances. Assert the simulated path reaches "milestone advances" (NOT "milestone FAILED with failure_reason=audit_fix_did_not_recover_build").
3. **Fast-forward harness** all 6 gates pass.
4. **Multi-matcher hook fixture:** `pytest tests/test_hook_multimatcher_conflict.py` MUST stay green (Phase 4.5 safety argument depends on it).
5. **Full M1 smoke REQUIRED** — Phase 4.5 changes the audit-fix path on wave-fail, the most-exercised recovery path. Need empirical proof on a real run.

**Memory write (`phase_4_5_landing.md`):**
* Conditional gate logic shipped (the boolean condition that lifts Risk #1).
* Re-self-verify integration shape.
* Risks now closed: #26 (Risk #1 obsolete after Phase 3.5), #27 (verification gap between audit-fix and self-verify), #28 (STATE.json + milestone_progress.json reconciliation in `_run_audit_loop` epilogue).
* Note for Phase 4.6: Phase 4.5's recovery path may move milestone status FAILED→COMPLETE multiple times across cycles. Phase 4.6's anchor-on-COMPLETE checkpoint must use the FINAL COMPLETE state, not an intermediate.

### 0.7 Phase 4.6 — Anchor-as-checkpoint chain + `--retry-milestone <id>` flag

**Pre-condition:** Phases 4.1-4.5 merged + smoke clean.

**Goal:** §I — Promote Phase 1 anchor primitive from "single-slot, wiped on next IN_PROGRESS" to "per-milestone snapshot chain on COMPLETE." Add `--retry-milestone <id>` flag that restores M(id-1)'s COMPLETE anchor + resets M(id)..M(N) to PENDING + resumes orchestration. The M25-disaster ceiling.

**Why:**
The 2026-04-26 smoke had 5 milestones in MASTER_PLAN. M1 wave-failed; M2-M5 never ran but blocked indefinitely by `milestone_manager.get_ready_milestones` requiring all deps COMPLETE. On a real 25-30 milestone build, M25 wave-fail discards M1-M24's effort. Phase 4.6 enables `--retry-milestone milestone-25 --resume-from <run-dir>` to preserve M1-M24 and retry only M25.

**Pre-flight (in addition to §0.1):**
1. Re-verify citations: Phase 1's `_capture_milestone_anchor` / `_restore_milestone_anchor` in `wave_executor.py`; `milestone_manager.py:74-82` `get_ready_milestones`; `cli.py` `--reset-failed-milestones` handler (reads about line 3990; drift expected); `cli.py:6160` (sequential PRD path post-COMPLETE).
2. Read `phase_1_landing.md` "Anchor primitive API" verbatim. Phase 4.6 EXTENDS, never replaces. The IN_PROGRESS-entry capture (single-slot) survives; the COMPLETE-entry capture is ADDITIVE.
3. Read `phase_1_landing.md` "Open follow-ups" — anchor pruning was Open Question #1. Phase 4.6 also designs the prune policy (prune-all-but-last-5 default).
4. Run baseline: all prior phase fixtures.

**Required Context7 lookups:**
* `/python/cpython` — re-verify `shutil.copytree` exception classes (Phase 1 already locked this; Phase 4.6 doesn't touch the internals but the prune policy involves `shutil.rmtree` whose Windows behavior we should re-verify since 4.6's prune may run on a stale anchor with locked files).
* `/python/cpython` — `pathlib.Path.glob` performance characteristics on large trees (Phase 4.6's prune walks per-milestone anchor dirs to compute total disk usage).

**TDD sequence:**
1. Create `tests/test_pipeline_upgrade_phase4_6.py`:
   * `test_anchor_capture_on_complete_writes_to_complete_subdir` — `_capture_milestone_anchor_on_complete(cwd, "milestone-1")` writes to `.agent-team/milestones/milestone-1/_anchor/_complete/` (separate from `_inprogress/`).
   * `test_anchor_chain_preserves_prior_milestone_complete_when_next_inprogress_fires` — capture M1 COMPLETE → start M2 IN_PROGRESS → M1's `_complete/` survives, only M2's `_inprogress/` is fresh.
   * `test_anchor_prune_policy_keeps_last_5_milestones` — capture COMPLETE for milestones 1-10; prune; assert milestones 1-5's `_complete/` are deleted, 6-10 retained.
   * `test_retry_milestone_flag_restores_prior_complete_anchor` — `--retry-milestone milestone-3` restores `.agent-team/milestones/milestone-2/_anchor/_complete/`; resets M3-M5 status to PENDING in STATE.json; resumes orchestration from M3.
   * `test_retry_milestone_flag_fails_when_prior_complete_anchor_missing` — `--retry-milestone milestone-3` when M2 was never COMPLETE → exits with clear error, no state mutation.
   * `test_retry_milestone_with_resume_from_run_dir` — operator workflow: previous run failed; new invocation with `--resume-from <run-dir> --retry-milestone milestone-25` restores M24's complete anchor in the run-dir.
   * `test_replay_smoke_2026_04_26_no_anchor_on_complete_for_milestone_1_failed` — the smoke's M1 wave-failed; assert `_complete/` was NOT written (only `_inprogress/`).
   * `test_disk_quota_warning_when_anchor_chain_exceeds_threshold` — when sum(anchor sizes) > 2GB, log a WARNING (not a hard fail).
2. Implement files:
   1. `src/agent_team_v15/wave_executor.py`:
      * `_capture_milestone_anchor_on_complete(cwd: str, milestone_id: str) -> Path` — new function; mirrors `_capture_milestone_anchor` but writes to `_complete/` subdir.
      * `_restore_milestone_anchor_from_complete(cwd: str, milestone_id: str) -> dict` — restores from `_complete/` subdir.
      * `_prune_anchor_chain(cwd: str, retain_last_n: int = 5) -> dict` — prunes `_complete/` dirs older than the last N completed milestones.
   2. `src/agent_team_v15/cli.py:6160` (post-COMPLETE in sequential PRD path) — invoke `_capture_milestone_anchor_on_complete`.
   3. `src/agent_team_v15/cli.py` argparse — add `--retry-milestone <id>` flag.
   4. `src/agent_team_v15/cli.py` `_run_prd_milestones` startup — when `--retry-milestone` set: validate, find prior milestone's `_complete/` anchor, restore, reset STATE.json, resume.
   5. `src/agent_team_v15/state.py` — `RunState.last_completed_milestone_id: str = ""` to track which milestone's COMPLETE-anchor is the resume point.
   6. `src/agent_team_v15/config.py` — `AuditTeamConfig.anchor_chain_retain_last_n: int = 5` (prune policy, configurable).
3. After each file, run all prior phase fixtures + Phase 4.6 fixtures.

**Pre-merge gate (Phase 4.6 specific):**
1. ALL prior phase fixtures + Phase 4.6 fixtures green.
2. **Two-milestone synthetic smoke:** craft a 2-milestone PRD (M1 trivial, M2 trivial). Run it. Confirm M1 captures `_complete/` anchor. Run it again with `--retry-milestone milestone-2 --resume-from <prior-run-dir>` — confirm M1's COMPLETE anchor restores M2 to PENDING and re-runs only M2.
3. **Disk quota smoke:** craft a 6-milestone PRD; after M6 completes, prune triggers; assert `_complete/` dirs for M1 are gone, M2-M6 retained.
4. **Fast-forward harness** all 6 gates pass.
5. **Full M1 smoke REQUIRED** — Phase 4.6 touches the anchor primitive; need empirical proof.

**Memory write (`phase_4_6_landing.md`):**
* Actual `_capture_milestone_anchor_on_complete` signature shipped.
* Anchor disk size on M1 COMPLETE (sizing input — different from IN_PROGRESS-entry size).
* Prune policy chosen (default 5).
* Operator workflow documented.
* Risks now closed: #20 (no resume-from-failed).

### 0.8 Phase 4.7 — Wave prompt explicit boundaries + scaffold convention reform

**Pre-condition:** Phases 4.1-4.6 merged + smoke clean.

**Goal:** §J — Two upstream input-quality fixes:
* **4.7a:** Wave B and Wave D prompts gain an explicit boundary block: "You are the BACKEND wave. Wave D handles the FRONTEND chassis (i18n, locales, components, layouts). Files in `apps/web/` requiring next-intl wiring or RTL setup are NOT yours — Wave D will create them." Symmetric for Wave D ("Wave B handles backend; you don't touch apps/api/").
* **4.7b:** Scaffold convention reform: stub files get a machine-readable header `// @scaffold-stub: finalized-by-wave-D` (or appropriate wave). Audit team reads this header and treats matching findings as DEFERRED if the named wave hasn't executed. Alternative: drop scaffold stubs entirely; let Wave D create from scratch (cleaner; bigger refactor).

**Why:**
The 2026-04-26 smoke shows scaffold pre-created `apps/web/src/middleware.ts` with the literal comment `// SCAFFOLD STUB — Wave D finalizes with JWT cookie forwarding.` The audit found this and graded it as F-001 critical "middleware no-op stub." The audit didn't read the comment. Wave B saw the file existed and didn't modify it (correctly; it's Wave D's job per the comment, even though the prompt didn't explicitly say so).

The Wave B prompt has 0 mentions of "Wave D" across 52KB. Codex had no way to know which side of the line frontend chassis fell on.

**Pre-flight (in addition to §0.1):**
1. Verified citations as of 2026-04-26 (drift expected; grep is canonical):
   * Scaffold templates live under `src/agent_team_v15/templates/` — confirmed dirs `pnpm_monorepo/` and `scaffold_assets/`. Scaffold runner is `src/agent_team_v15/scaffold_runner.py`. Stub files are emitted from these templates; "SCAFFOLD STUB" markers grep-confirmed in `scaffold_runner.py` (1 hit; Phase 4.7 must follow the actual emit path).
   * Wave B / Wave D prompt construction — `prompt_builder.py` does NOT exist. The actual prompt builder is split across:
     - `src/agent_team_v15/codex_prompts.py` (Codex/Wave-B prompt assembly)
     - `src/agent_team_v15/audit_prompts.py` (audit team prompts)
     - `src/agent_team_v15/codex_fix_prompts.py` (Codex fix-mode prompts)
     - `src/agent_team_v15/template_renderer.py` (Jinja-style render layer)
     - `src/agent_team_v15/wave_a5_t5.py` (Wave A5 / T5 prompts)
     - Possibly `src/agent_team_v15/v18_specialist_prompts.py` (per the targeted test file `tests/test_v18_specialist_prompts.py`)
   * **Phase 4.7 implementer's first task: `grep -rn "Allowed file globs" src/agent_team_v15/` to find the actual source of Wave B's prompt. Then `grep -rn "FRAMEWORK INSTRUCTIONS" src/agent_team_v15/`. The Wave-D prompt builder is similar but separate.** Document the actual source files in `phase_4_7_landing.md`.
2. Read the actual Wave B prompt at `tests/fixtures/smoke_2026_04_26/codex-captures/milestone-1-wave-B-prompt.txt` (Phase 4.1 froze) — find every section that mentions `apps/web` (38 hits per the smoke landing). Phase 4.7a updates the SOURCE templates, NOT the captured fixture.
3. Read every scaffold-stub file in the smoke run-dir: `grep -rln "SCAFFOLD STUB" v18 test runs/m1-hardening-smoke-20260426-173745/apps` — enumerate the actual stubs to inform Phase 4.7b's header design. Confirmed at least: `apps/web/src/middleware.ts`. Find any others.
4. Run baseline: ALL prior phase fixtures + `tests/test_v18_specialist_prompts.py` + `tests/test_scaffold_runner.py` + `tests/test_scaffold_m1_correctness.py`.

**Required Context7 lookups:**
* `/anthropics/claude-code` and `/openai/codex` (or whatever Codex's documented prompt format is) — verify both providers handle the new `<wave_boundary>` block correctly (no quirks on either side).
* Check whether either provider has a documented "I shouldn't touch this file" semantic; some have specific markers (`// @copilot-ignore` etc.).

**TDD sequence:**
1. Create `tests/test_pipeline_upgrade_phase4_7.py`:
   * `test_wave_b_prompt_includes_wave_d_boundary_block` — render Wave B prompt for M1; assert it contains `<wave_boundary>` block listing Wave D's responsibilities.
   * `test_wave_b_prompt_excludes_apps_web_from_allowed_globs_when_wave_d_in_milestone` — Wave B's allowed-globs no longer include `apps/web/**` if Wave D is part of the milestone's wave-set. (Subtle: `apps/web/Dockerfile` and `apps/web/.env.example` may still be backend-touchable; lock these as exceptions.)
   * `test_wave_d_prompt_includes_wave_b_boundary_block` — symmetric.
   * `test_scaffold_stub_header_marker_recognized_by_audit` — synthesize a scaffold file with `// @scaffold-stub: finalized-by-wave-D` header; audit team's finding generation reads the header and tags `owner_wave="D"` for findings on this file (composes with Phase 4.3).
   * `test_scaffold_stub_files_carry_machine_readable_header` — every scaffold-emitted stub MUST have the header. Walk all scaffolded files (Phase 4.1's `_resolve_per_wave_service_target` map can identify which files are scaffolded); assert each has the header (or fail loudly if not).
   * `test_replay_smoke_2026_04_26_middleware_finding_classified_as_deferred` — using Phase 4.7b's header awareness + Phase 4.3's classifier, the F-001 finding ("middleware no-op stub") gets owner_wave="D" + status=DEFERRED. Convergence ratio improves.
2. Implement files (Phase 4.7a — wave prompt boundaries):
   1. **The actual Wave B / Wave D prompt source file** (Phase 4.7 implementer locates via `grep -rn "Allowed file globs" src/agent_team_v15/` — candidates: `codex_prompts.py`, `audit_prompts.py`, `template_renderer.py`, `wave_a5_t5.py`, `v18_specialist_prompts.py`). Add `<wave_boundary>` block. Include MASTER_PLAN-derived list of "files NOT yours."
   2. The same file (or the wave-dispatch site that consumes the rendered prompt) — narrow the Wave B `allowed_file_globs` when Wave D is in the milestone's wave-set (don't include `apps/web/**` blanketly; include only `apps/web/Dockerfile` + `apps/web/.env.example` as backend-touchable). Symmetrically narrow Wave D's allowed globs.
3. Implement files (Phase 4.7b — scaffold convention):
   1. `src/agent_team_v15/scaffold_runner.py` and `src/agent_team_v15/templates/pnpm_monorepo/` (and any other template tree under `src/agent_team_v15/templates/`) — every scaffold template that emits a stub file gets a `@scaffold-stub: finalized-by-wave-<X>` header (language-appropriate comment glyph; see §J for the language-agnostic marker spec).
   2. `src/agent_team_v15/audit_models.py` — `AuditFinding.from_dict` (or a new helper `_read_scaffold_stub_owner`) reads the file's first 8 lines on disk; if `_SCAFFOLD_STUB_RE` matches, the finding gets `owner_wave=X` (overrides path-based classification).
4. After each file, run all prior phase fixtures + `tests/test_v18_specialist_prompts.py` + `tests/test_scaffold_runner.py`.

**Pre-merge gate (Phase 4.7 specific):**
1. ALL prior phase fixtures + Phase 4.7 fixtures green.
2. **Replay smoke:** load the 2026-04-26 smoke's middleware.ts; simulate Phase 4.7b header awareness; assert F-001 finding gets owner_wave="D" + DEFERRED status.
3. **Re-render Wave B prompt:** synthesize a fresh Wave B prompt for the same M1; confirm the new prompt contains explicit `<wave_boundary>` block, narrowed allowed-globs, and 0 ambiguity about frontend chassis ownership.
4. **Fast-forward harness** all 6 gates pass.
5. **Full M1 smoke REQUIRED** — Phase 4.7 touches prompt construction and scaffold output, the most-load-bearing input layer. Empirical proof essential.

**Memory write (`phase_4_7_landing.md`):**
* Actual `<wave_boundary>` block content shipped (the verbatim prose).
* Scaffold stub header format chosen (`@scaffold-stub` recommended; document why if different).
* Risks now closed: #21 (scaffold stubs not machine-readable), #22 (wave prompt scope ambiguity).
* Final post-Phase-4 state of the orchestrator's input + recovery layers.

### 0.9 Inter-phase signal — what each memory file MUST contain

| Memory file | Required keys | Consumer |
|---|---|---|
| `phase_4_1_landing.md` | actual `_resolve_per_wave_service_target` signature, Context7-confirmed docker compose syntax, narrowed self-verify behavior | Phase 4.2 + 4.5 |
| `phase_4_2_landing.md` | retry_feedback API surface, Context7-confirmed tsc/buildkit/Next error formats | Phase 4.3 + 4.5 |
| `phase_4_3_landing.md` | WAVE_PATH_OWNERSHIP table, owner_wave classification rules, convergence ratio computation | Phase 4.4 + 4.5 + 4.7 |
| `phase_4_4_landing.md` | WaveFailureForensics schema, cost savings observed | Phase 4.5 |
| `phase_4_5_landing.md` | conditional Risk #1 lift logic, re-self-verify integration shape | Phase 4.6 + 4.7 |
| `phase_4_6_landing.md` | anchor-on-complete signature, prune policy, retry-milestone flag UX | Phase 4.7 + future maintainers |
| `phase_4_7_landing.md` | wave_boundary block content, scaffold stub header format, end-state safety + input-quality summary | future maintainers |

### 0.10 Halting conditions (when to STOP and surface to user)

Stop and surface if ANY of:
* A citation is stale and the new line cannot be confidently identified.
* A test fixture passes for the wrong reason (e.g., implementation accidentally satisfies the assertion via a side effect).
* The fast-forward harness regresses on previously-clean gates.
* A new risk surfaces that the §C register doesn't cover.
* Context7 returns a doc snippet that contradicts a load-bearing assumption in this plan.
* The smoke gate fails after merge.
* You discover a phase's design conflicts with a phase landed previously (e.g., Phase 4.5 lift breaks Phase 1 Risk #1's fixture in an unexpected way).
* The user's "UPGRADE only, never downgrade" invariant (§0.1 #16) would be violated by your proposed change.

NEVER paper over a halt with "good enough." The M25-disaster scenario IS the cumulative effect of papering over halts.

**Halt protocol — what to do when halting:**

1. **Do NOT commit any code.** If you have uncommitted local changes, leave them in the worktree (don't push, don't stash).
2. **Append a halt memo to the END of THIS plan document** as a new section: `## Phase 4.<N> Halt Memo — <YYYY-MM-DD>`. Include:
   * What you were doing when you halted (which step in §0.<N>).
   * Why you halted (cite §0.10 condition).
   * What you discovered (file:line, error, conflicting Context7 snippet, etc.).
   * What you considered as remediation.
   * Open question for the user (specific decision needed).
3. **Write a memory entry** `phase_4_<N>_halt_<YYYY-MM-DD>.md` in user auto-memory with the same content + a `type: project` frontmatter.
4. **Surface to the user** in your terminal output: cite the halt memo path + memory file + brief one-paragraph summary.
5. **Do not auto-restart.** Wait for the user to read, decide, and re-dispatch.

**Halt memo example skeleton (in plan doc):**

```markdown
## Phase 4.<N> Halt Memo — 2026-XX-XX

**Halted at:** §0.<N> step <K>: "<step description>"
**Halt reason (§0.10 condition):** Citation stale / new risk / Context7 contradiction / etc.
**Discovery:** <what you found, with file:line>
**Remediation considered:** <options>
**Open question for user:** <specific decision needed>
```

---

## Section A — Executive Summary

The 2026-04-26 M1 hardening smoke (HEAD `1c46445`) failed at Wave B self-verify after 3 retries. Diagnosis revealed the failure is NOT a Codex competence issue or a Docker problem — it's a **5-layer input-quality cascade** that gives Codex an un-passable brief and grades it on others' deliverables.

Confirmed by reading the actual 52KB Wave B prompt: zero mentions of "Wave D"; framework instructions are NestJS-only; allowed globs include `apps/web/**` and `locales/**`; milestone description includes "next-intl with en/ar locales"; the prompt asks Codex to disambiguate frontend chassis ownership with no signal.

Reclassifying the 46 audit findings by ownership: **5/11 critical findings are downstream of "later wave never ran" (Wave D's frontend chassis, Wave C's api-client). Only 3/11 are real Codex bugs.** The audit graded the partial output as if all waves had executed.

Phase 4 ships SEVEN dependency-ordered phases addressing the entire input-quality + recovery cascade:

* **Group A — Input quality** (4.1-4.3): per-wave self-verify scoping, structured retry feedback, audit wave-awareness. Highest leverage. Even without recovery wiring, these prevent ~70% of the wave-fails this smoke exposed.
* **Group B — Forensics** (4.4): close Risks #18 + #19. Save ~$5-8 per wave-fail; gain wave-fail-vs-audit-fail post-mortem distinguishability.
* **Group C — Recovery cascade** (4.5-4.6): conditional lift of Phase 1 Risk #1 with all safety nets armed; re-self-verify after audit-fix; resume-from-failed via anchor-as-checkpoint chain. The M25-disaster ceiling.
* **Group D — Boundaries** (4.7): wave prompt explicit boundary block; scaffold stub header convention. Stops the cascade at its source.

Together: input garbage stops being produced (Group A + D); when it IS produced, recovery is automatic (Group C); when recovery doesn't suffice, operator has a real escape hatch (Phase 4.6).

---

## Section B — Evidence Pack (verbatim citations from smoke run-dir)

All paths relative to `v18 test runs/m1-hardening-smoke-20260426-173745/`.

### B.1 Wave B retry feedback (the "smoking gun")

`v18 test runs/m1-hardening-smoke-20260426-173745/.agent-team/codex-captures/milestone-1-wave-B-protocol.log` line ~14:11:55 (turn/start of retry-1):

```
<previous_attempt_failed>
Your previous Wave B output failed acceptance testing. You MUST fix these issues in this retry. Do NOT repeat the same mistakes.
Docker build failures (per service):
target api: failed to solve: process "/bin/sh -c pnpm --filter api build" did not complete successfully: exit code: 1
Requirements for this retry:
</previous_attempt_failed>
```

This is the ENTIRE actionable feedback Codex got across 2 retries. Phase 4.2 replaces this with structured payload. Phase 4.4 captures the same information deterministically into `WAVE_FAILURE_FORENSICS.json`.

### B.2 Wave B prompt — frontend/backend ambiguity

`.agent-team/codex-captures/milestone-1-wave-B-prompt.txt`, sections:

```
### Allowed file globs — only produce files matching these patterns
- apps/api/**
- apps/web/**          ← frontend allowed
- packages/api-client/**
- prisma/**
- locales/**           ← frontend allowed
- docker-compose.yml
- .env.example
- package.json
```

```
### Allowed feature / AC references for this milestone
- Merge-Surfaces: package.json
- apps/api/src/app.module.ts
- apps/api/src/main.ts
- apps/web/src/app/layout.tsx        ← frontend listed
- apps/web/src/i18n/index.ts          ← frontend listed
- apps/web/locales/en/common.json     ← frontend listed
- apps/web/locales/ar/common.json     ← frontend listed
- prisma/schema.prisma
- docker-compose.yml
- .env.example
```

But framework instructions are NestJS-only:
```
[FRAMEWORK INSTRUCTIONS: TypeScript/NestJS]
DI (CRITICAL): Every module using JwtAuthGuard MUST import AuthModule. ...
Database (Prisma): ...
Health: GET /health via HealthController. ...
Structure: src/main.ts, src/app.module.ts, src/auth/, src/health/, src/{domain}/
Testing: jest + @nestjs/testing + supertest for NestJS, ...
```

Mentions of "Wave D" in the entire 52KB prompt: **0**. Phase 4.7 adds the boundary block.

### B.3 Scaffold stub example — middleware.ts

`apps/web/src/middleware.ts` content:
```typescript
// SCAFFOLD STUB — Wave D finalizes with JWT cookie forwarding.
import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';

export function middleware(_request: NextRequest): NextResponse {
  return NextResponse.next();
}

export const config = {
  matcher: [],
};
```

Audit graded this as F-001 critical "middleware no-op stub." The literal comment names Wave D as the finalizer, but the audit doesn't read it. Phase 4.7b adds machine-readable `@scaffold-stub: finalized-by-wave-D` header that audit (Phase 4.3) reads.

### B.4 Per-service self-verify failure attribution (already in artifacts!)

`.agent-team/milestones/milestone-1/WAVE_FINDINGS.json`:
```json
{"wave": "B", "code": "WAVE-B-SELF-VERIFY", "file": "api",
 "message": "retry=0 violations=0 build_failures=1: ... target api: failed to solve: ... exit code: 1"}
{"wave": "B", "code": "WAVE-B-SELF-VERIFY", "file": "api",
 "message": "retry=1 violations=0 build_failures=1: ..."}
{"wave": "B", "code": "WAVE-B-SELF-VERIFY", "file": "web",
 "message": "retry=2 violations=0 build_failures=1: ... target web: failed to solve: ... exit code: 1"}
```

The system ALREADY KNOWS which service failed per retry (`file: "api"` vs `file: "web"`). Phase 4.1 just gates self-verify on the wave's own service.

### B.5 STATE.json missing failure_reason

`.agent-team/STATE.json::milestone_progress`:
```json
{"milestone-1": {"status": "FAILED"}}
```

No `failure_reason` field. Phase 1.6 added the field but only wired audit-fail. Phase 4.4 wires wave-fail.

### B.6 Audit findings by owner_wave (Phase 4.3 input)

Manual classification of 11 critical findings:
* Owner = Wave B (real Codex bugs): #6 (duplicate prisma), #8 (shadow d.ts), #11 (bcrypt undeclared) — **3/11**
* Owner = Wave B Dockerfile (Codex Dockerfile bug): #9 — **1/11**
* Owner = Wave D (never ran): #1, #2, #3, #4 — **4/11**
* Owner = Wave C (never ran): #5 — **1/11**
* Owner = downstream of Wave D: #10 — **1/11**
* Owner = scaffold path mismatch: #7 — **1/11**

Phase 4.3 implements `wave_ownership.resolve_owner_wave(path)` to do this classification automatically.

---

## Section C — Risk Register (extending Phase 1-3.5's §C)

Phase 1-3.5 closed Risks #1-17. Phase 4 closes 13 risks (#18-30) surfaced by the 2026-04-26 smoke + design analysis:

| # | Title | Closer | Status |
|---|---|---|---|
| 18 | `failure_reason` not persisted on wave-fail (Phase 1.6 only wired audit-fail path) | Phase 4.4 | OPEN → CLOSE |
| 19 | Failed-milestone forensics audit fires unconditionally on wave-fail (~$5-8 wasted per wave-fail) | Phase 4.4 | OPEN → CLOSE |
| 20 | No resume-from-failed milestone path (M(N) FAIL discards M1..M(N-1)) | Phase 4.6 | OPEN → CLOSE |
| 21 | Scaffold stubs not machine-readable (audit can't tell stub from missing feature) | Phase 4.7b | OPEN → CLOSE |
| 22 | Wave B/D prompt scope ambiguity (allowed-globs include frontend, framework instructions backend-only, no Wave D mention) | Phase 4.7a | OPEN → CLOSE |
| 23 | Wave self-verify scope mismatch (full `docker compose build` vs per-service) | Phase 4.1 | OPEN → CLOSE |
| 24 | Retry feedback is one-line summary; Codex retries blind | Phase 4.2 | OPEN → CLOSE |
| 25 | Audit grades all findings without owner-wave awareness; convergence ratio inflated | Phase 4.3 | OPEN → CLOSE |
| 26 | Phase 1 Risk #1 obsolete after Phase 3.5; gates audit-fix off when safety nets are armed | Phase 4.5 | OPEN → CLOSE (conditional lift) |
| 27 | No re-self-verify after audit-fix terminates; verification gap between "audit score improved" and "build passes" | Phase 4.5 | OPEN → CLOSE |
| 28 | STATE.json + milestone_progress.json disagree on `interrupted_milestone` (split-write inconsistency) | Phase 4.5 epilogue | OPEN → CLOSE |
| 29 | Codex sandbox cannot reproduce parent's `docker compose build` (Windows buildx lock conflict) | Phase 4.2 (mitigates) | KNOWN LIMITATION (out of agent-team's domain) |
| 30 | Convergence ratio computed over total requirements when only some waves ran | Phase 4.3 | OPEN → CLOSE |

**Risk #29 classification rationale:** Codex's sandbox CAN'T run `docker compose build` due to a Docker Desktop / Windows buildx lock conflict (`C:\Users\<user>\.docker\buildx\.lock: Access is denied`). This is OUTSIDE agent-team's domain — it's a Docker Desktop infrastructure issue. Phase 4.2's richer retry feedback REMOVES the NEED for Codex to re-run the failing command (it gets enough signal from parsed errors + unresolved imports), so the limitation is mitigated. The underlying lock issue is logged as a known-limitation rather than closed. If Docker Desktop's buildx locking changes upstream, revisit.

`[NEW — Phase 4.<N>]` annotations expected as phases land and discover unforeseen issues. Each phase agent appends to this table; never renumbers.

---

## Section D — Phase 4.1 Detail (Wave self-verify scope-narrowing)

**Files touched (estimated ~5):**
* `src/agent_team_v15/wave_b_self_verify.py` (extract resolver, extend `docker_build` with services arg, gate on flag)
* `src/agent_team_v15/wave_d_self_verify.py` (**NEW MODULE** mirroring wave_b_self_verify.py shape)
* `src/agent_team_v15/cli.py` (Wave D dispatch site invokes new acceptance test)
* `src/agent_team_v15/config.py` (`per_wave_self_verify_enabled` flag)
* `tests/test_pipeline_upgrade_phase4_1.py` (NEW)
* `tests/fixtures/smoke_2026_04_26/...` (NEW — Phase 4.1 freezes load-bearing smoke artifacts here for downstream phases)

**Function signatures to add:**

```python
# wave_b_self_verify.py (NEW module-level helper)
def _resolve_per_wave_service_target(
    wave_letter: str,
    stack_contract: dict | None = None,
) -> list[str]:
    """Map wave letter to compose service names this wave is responsible for.

    Returns ["api"] for B, ["web"] for D, ["api", "web"] for T (full e2e),
    [] for waves that don't run docker self-verify (A, A5, C, scaffold).
    Honors STACK_CONTRACT.json's service-name overrides if present.
    """

# wave_b_self_verify.py (extends existing docker_build call)
def docker_build(
    cwd_path: Path,
    compose_file: Path,
    *,
    timeout: int = 600,
    services: list[str] | None = None,  # NEW
) -> list[BuildResult]:
    """When services is None, builds entire compose (existing behavior).
    When non-None, passes the list to `docker compose build <services...>`."""

# wave_b_self_verify.py (run_wave_b_acceptance_test stays at line 98 in pre-Phase-4.1
# source; Phase 4.1 changes its docker_build call to pass services=_resolve_per_wave_service_target("B", ...))

# wave_d_self_verify.py (NEW module — mirrors wave_b_self_verify.py shape)
def run_wave_d_acceptance_test(
    cwd: Path,
    *,
    autorepair: bool = True,
    timeout_seconds: int = 600,
) -> WaveDVerifyResult:
    """Runs `docker compose build web` only (per Phase 4.1 scope-narrowing)."""
```

**ACs:**
* AC1: Wave B self-verify spawns `docker compose build api` (not full).
* AC2: Wave D self-verify spawns `docker compose build web`.
* AC3: Wave T self-verify still runs full stack (preserves e2e semantics).
* AC4: Per-wave self-verify failure attribution carries `service=api` or `service=web` (already does; Phase 4.2 consumes).
* AC5: Config flag `per_wave_self_verify_enabled: bool = True` allows rollback to old behavior.
* AC6: Replay test on smoke evidence: had Phase 4.1 been live, retry 2 of Wave B would have been declared self-verify-passed (api passing was sufficient), milestone advances to Wave D.

**Rollback plan:** Flip `per_wave_self_verify_enabled = False` in config — restores full-compose behavior.

---

## Section E — Phase 4.2 Detail (Strong deterministic retry feedback)

**Files touched (~4):**
* `src/agent_team_v15/retry_feedback.py` (NEW module)
* `src/agent_team_v15/wave_executor.py` (call new module)
* `src/agent_team_v15/config.py` (flag)
* `tests/test_pipeline_upgrade_phase4_2.py` (NEW)

**Function signatures:**

```python
# retry_feedback.py (NEW)
def extract_typescript_errors(stderr: str) -> list[dict[str, Any]]:
    """Regex-based extraction of tsc errors. Returns
    [{"file": str, "line": int, "col": int, "code": str, "message": str}].
    Tested against current TypeScript stable per Context7 lookup.
    """

def extract_buildkit_inner_stderr(stderr: str) -> str:
    """Strips 'failed to solve: process X did not complete successfully'
    wrapper to expose the inner command's actual stderr."""

def scan_unresolved_imports(
    modified_files: list[str], project_root: str
) -> list[dict[str, str]]:
    """Walks modified TS/JS files; for each `import ... from '...'`,
    checks the target exists on disk. Returns
    [{"file": str, "line": int, "import_target": str, "kind": "missing"|"ambiguous"}]."""

def compute_progressive_signal(
    this_attempt: dict, prior_attempts: list[dict]
) -> str:
    """Generates the 'previous: X. now: Y. focus: Z.' line that signals
    progress across retries."""

def build_retry_payload(
    *,
    stderr: str,
    modified_files: list[str],
    project_root: str,
    prior_attempts: list[dict],
    wave_letter: str,
    max_size_bytes: int = 12000,
) -> str:
    """Composes the new <previous_attempt_failed> block."""
```

**ACs:**
* AC1: Payload includes full stderr (truncated to 5KB with marker).
* AC2: Payload includes `[{file, line, message}]` for parsed errors.
* AC3: Payload lists unresolved imports from modified files.
* AC4: Progressive signal across retries.
* AC5: First-attempt has no retry block (regression-safe).
* AC6: Bounded at 12KB.
* AC7: Replay smoke evidence: new payload would have given Codex retry-1 enough actionable signal to fix prisma-in-deps issue.

**Rollback:** Flip `strong_retry_feedback_enabled = False`.

---

## Section F — Phase 4.3 Detail (Audit wave-awareness)

**Files touched (~6):**
* `src/agent_team_v15/wave_ownership.py` (NEW)
* `src/agent_team_v15/audit_models.py` (Finding gains owner_wave field)
* `src/agent_team_v15/audit_team.py` (convergence ratio filter)
* `src/agent_team_v15/fix_executor.py` (`_classify_fix_features` skip-DEFERRED)
* `src/agent_team_v15/cli.py` (`_convert_findings` propagates owner_wave)
* `src/agent_team_v15/config.py` (`audit_wave_awareness_enabled` flag)
* `tests/test_pipeline_upgrade_phase4_3.py` (NEW)

**Function signatures:**

```python
# wave_ownership.py (NEW)
WAVE_PATH_OWNERSHIP: dict[str, str] = {
    "apps/api/**": "B",
    "apps/web/**": "D",
    "packages/api-client/**": "C",
    "prisma/**": "B",
    "e2e/tests/**": "T",
    "tests/**": "T",
    "docker-compose.yml": "wave-agnostic",
    ".env.example": "wave-agnostic",
    "package.json": "wave-agnostic",
    # ... full table built from MASTER_PLAN-derived semantics
}

def resolve_owner_wave(path: str) -> str:
    """Returns wave letter (A|B|C|D|T|...) or 'wave-agnostic'."""

def is_owner_wave_executed(wave_letter: str, run_state: RunState) -> bool:
    """Did this wave actually execute (regardless of pass/fail)?"""

def compute_filtered_convergence_ratio(
    findings: list[Finding],
    run_state: RunState,
) -> float:
    """Convergence over executed-wave findings only."""
```

**ACs:**
* AC1: `resolve_owner_wave` returns correct wave for each path class.
* AC2: Finding gets `owner_wave` field auto-populated by `from_dict`.
* AC3: Convergence ratio excludes findings whose owner_wave is DEFERRED.
* AC4: `_classify_fix_features` skips features all-DEFERRED.
* AC5: Replay smoke: ≥4 critical findings get owner_wave="D" or "C" + DEFERRED.
* AC6: Backward-compat: existing callers without owner_wave info get "wave-agnostic" default.

**Rollback:** Flip `audit_wave_awareness_enabled = False`.

---

## Section G — Phase 4.4 Detail (failure_reason on wave-fail + deterministic forensics)

**Files touched (~4):**
* `src/agent_team_v15/wave_failure_forensics.py` (NEW)
* `src/agent_team_v15/cli.py` (wave-fail mark site + failed-milestone audit gate)
* `src/agent_team_v15/config.py` (flag)
* `tests/test_pipeline_upgrade_phase4_4.py` (NEW)

**Function signatures:**

```python
# wave_failure_forensics.py (NEW)
@dataclass
class WaveFailureForensics:
    failed_wave_letter: str
    retry_count: int
    self_verify_error: dict  # service-attributed (Phase 4.1 wired)
    structured_retry_feedback: dict  # Phase 4.2's payload
    files_modified: list[str]
    codex_protocol_log_tail: str
    docker_compose_ps: str
    owner_wave_findings_count_per_wave: dict[str, int]  # Phase 4.3 wired
    failure_reason: str  # e.g. "wave_b_failed"
    timestamp: str

def build_wave_failure_forensics(
    *,
    run_state: RunState,
    wave_findings: dict,
    telemetry: dict,
    codex_protocol_path: pathlib.Path | None,
    docker_compose_ps: str | None,
) -> WaveFailureForensics: ...

def write_wave_failure_forensics(
    forensics: WaveFailureForensics,
    agent_team_dir: pathlib.Path,
) -> pathlib.Path: ...
```

**ACs:**
* AC1: Wave-fail FAILED-mark site passes `failure_reason="wave_<X>_failed"`.
* AC2: `_run_failed_milestone_audit_if_enabled` gates on `wave_result.success`; on wave-fail, writes forensics JSON and skips the LLM audit.
* AC3: WaveFailureForensics schema covers Phase 4.1 + 4.2 + 4.3 outputs.
* AC4: Convergence-fail path (wave_result.success=True) preserved (LLM audit still fires).
* AC5: Replay smoke: ~$5-8 saved on simulated wave-fail.

**Rollback:** Flip `failed_milestone_audit_on_wave_fail_enabled = True` to restore old (always-fire) behavior.

---

## Section H — Phase 4.5 Detail (Lift Risk #1 + re-self-verify)

**Files touched (~5):**
* `src/agent_team_v15/cli.py` (`_run_audit_fix_unified` conditional gate at the Risk #1 short-circuit; `_run_audit_loop` re-self-verify epilogue; `STATE.json` + `milestone_progress.json` reconciliation closing Risk #28)
* `src/agent_team_v15/wave_b_self_verify.py` and `src/agent_team_v15/wave_d_self_verify.py` (Phase 4.1's modules; Phase 4.5 calls `run_wave_b_acceptance_test` / `run_wave_d_acceptance_test` for re-self-verify after audit-fix loop terminates)
* `src/agent_team_v15/fix_executor.py` (`_classify_fix_features` skip all-DEFERRED features — Phase 4.3 sets the field; Phase 4.5 enforces the gate; verify Phase 4.3 already did this and dedupe if so)
* `src/agent_team_v15/config.py` (`lift_risk_1_when_nets_armed` flag)
* `tests/test_pipeline_upgrade_phase4_5.py` (NEW)
* `tests/test_audit_fix_guardrails_phase1.py` (UPDATE — rename + extend the Risk #1 fixture per §0.6 step 2)

**Conditional lift logic:**

```python
# cli.py _run_audit_fix_unified
if wave_result is not None and wave_result.success is False:
    if config.audit_team.lift_risk_1_when_nets_armed:
        nets_armed = (
            config.audit_team.milestone_anchor_enabled
            and config.audit_team.test_surface_lock_enabled
            and config.audit_team.audit_wave_awareness_enabled
            and audit_fix_path_guard_settings_present(cwd)
        )
        if nets_armed:
            log("[AUDIT-FIX] wave_result.success=False; recovery attempt with safety nets armed")
            # fall through to audit-fix loop with anchor armed
        else:
            log("[AUDIT-FIX] wave_result.success=False; safety nets degraded — short-circuiting (Phase 1 Risk #1 fallback)")
            return ([], 0.0)
    else:
        # config explicitly disabled the lift
        return ([], 0.0)
```

**Re-self-verify after loop:**

```python
# cli.py _run_audit_loop epilogue
if wave_was_originally_failed and milestone_status == "COMPLETE":
    self_verify_result = wave_b_self_verify(cwd, ...)  # Phase 4.1 narrowed
    if not self_verify_result.success:
        # rollback
        _restore_milestone_anchor(...)
        update_milestone_progress(state, mid, "FAILED",
            failure_reason="audit_fix_did_not_recover_build")
    else:
        # genuine recovery — milestone graduates from FAILED to COMPLETE
        update_milestone_progress(state, mid, "COMPLETE",
            failure_reason="")  # clear any prior reason
```

**ACs (per §0.6):**
* AC1: When safety nets disabled, Risk #1 short-circuit STILL fires.
* AC2: When safety nets armed, audit-fix runs on wave-fail.
* AC3: Audit-fix dispatch skips all-DEFERRED features.
* AC4: Re-self-verify after loop terminates non-FAILED.
* AC5: Re-self-verify failure → anchor restore + FAILED with `failure_reason="audit_fix_did_not_recover_build"`.
* AC6: Re-self-verify success → milestone FAILED→COMPLETE/DEGRADED.
* AC7: Replay smoke: only 3 real Codex bugs would be dispatched (not 46); 4 frontend findings DEFERRED.

**Rollback:** Flip `lift_risk_1_when_nets_armed = False`.

---

## Section I — Phase 4.6 Detail (Anchor-as-checkpoint chain)

**Files touched (~5):**
* `src/agent_team_v15/wave_executor.py` (anchor-on-complete capture, prune)
* `src/agent_team_v15/cli.py` (--retry-milestone flag; resume orchestration)
* `src/agent_team_v15/state.py` (RunState.last_completed_milestone_id)
* `src/agent_team_v15/config.py` (anchor_chain_retain_last_n)
* `tests/test_pipeline_upgrade_phase4_6.py` (NEW)

**Function signatures:**

```python
# wave_executor.py (NEW)
def _capture_milestone_anchor_on_complete(
    cwd: str, milestone_id: str
) -> Path:
    """Mirrors _capture_milestone_anchor but writes to
    .agent-team/milestones/<id>/_anchor/_complete/.
    Coexists with the existing _inprogress/ slot."""

def _restore_milestone_anchor_from_complete(
    cwd: str, milestone_id: str
) -> dict[str, list[str]]:
    """Restores from _complete/ subdir."""

def _prune_anchor_chain(
    cwd: str, retain_last_n: int = 5
) -> dict[str, Any]:
    """Prunes _complete/ dirs older than the last N completed milestones.
    Returns {'pruned_milestones': [...], 'bytes_freed': N}."""
```

**CLI flag (mutually exclusive with `--reset-failed-milestones`):**

```bash
agent-team-v15 \
    --prd PRD.md --config config.yaml \
    --resume-from "v18 test runs/m1-hardening-smoke-20260426-173745" \
    --retry-milestone milestone-25
```

**Mutex enforcement:** argparse mutually-exclusive group `[--retry-milestone | --reset-failed-milestones]`. Different recovery semantics:
* `--reset-failed-milestones` (existing): unlocks FAILED milestones for re-run from M1 (does NOT preserve prior milestone state).
* `--retry-milestone <id>` (NEW Phase 4.6): restores M(id-1)'s COMPLETE anchor + resets M(id)..M(end) to PENDING + resumes from M(id) (PRESERVES M1..M(id-1) state).

If both passed, fail loudly with: `error: --retry-milestone and --reset-failed-milestones are mutually exclusive`.

Add fixture `test_retry_milestone_and_reset_failed_milestones_mutex` to verify.

**Resume orchestration logic:**

```python
# cli.py _run_prd_milestones startup
if args.retry_milestone:
    target_id = args.retry_milestone
    prior_id = _find_immediately_prior_milestone(plan, target_id)
    prior_anchor = run_dir / ".agent-team" / "milestones" / prior_id / "_anchor" / "_complete"
    if not prior_anchor.exists():
        sys.exit(f"--retry-milestone {target_id}: prior milestone {prior_id} has no COMPLETE anchor")
    _restore_milestone_anchor_from_complete(run_dir, prior_id)
    # reset target_id..end to PENDING in STATE.json
    for mid in milestones_from(target_id):
        update_milestone_progress(state, mid, "PENDING")
    # resume orchestration from target_id
```

**ACs:**
* AC1: M1 COMPLETE → `_anchor/_complete/` written.
* AC2: M2 IN_PROGRESS → M1's `_complete/` survives.
* AC3: After M6 COMPLETE with retain_last_n=5, M1's `_complete/` is pruned.
* AC4: `--retry-milestone M3` restores M2's `_complete/`, resets M3-M(end) to PENDING.
* AC5: `--retry-milestone M3` when M2 has no `_complete/` → clean exit, no state mutation.
* AC6: Disk WARNING when chain exceeds 2GB.
* AC7: Replay smoke: M1 was wave-failed → `_complete/` was NOT written (only `_inprogress/`).

**Rollback:** Flip `anchor_chain_retain_last_n = 0` to disable on-complete capture; existing single-slot Phase 1 behavior survives.

---

## Section J — Phase 4.7 Detail (Wave prompt boundaries + scaffold convention)

**Files touched (~7+, exact count depends on Phase 4.7 implementer's grep findings):**
* The actual Wave B / Wave D prompt source file(s) — Phase 4.7 implementer locates via grep. Likely candidates: `src/agent_team_v15/codex_prompts.py`, `audit_prompts.py`, `template_renderer.py`, `wave_a5_t5.py`, `v18_specialist_prompts.py`. Document actual files in `phase_4_7_landing.md`.
* Scaffold templates under `src/agent_team_v15/templates/pnpm_monorepo/` and any other template tree (stub headers)
* `src/agent_team_v15/scaffold_runner.py` (if stub-emit logic lives here vs in templates directly)
* `src/agent_team_v15/audit_models.py` (`from_dict` reads stub header via new `_read_scaffold_stub_owner` helper)
* `src/agent_team_v15/wave_ownership.py` (Phase 4.3 module — header overrides path-based classification when both apply)
* `src/agent_team_v15/config.py` (`wave_boundary_block_enabled` flag, defaults True)
* `tests/test_pipeline_upgrade_phase4_7.py` (NEW)

**Wave boundary block (Phase 4.7a):**

```
<wave_boundary>
You are Wave B (BACKEND). Your scope:
- apps/api/**
- prisma/** (root)
- packages/shared/**
- docker-compose.yml (backend service additions only)
- root package.json (workspace declarations only)

The following are NOT yours — Wave D will create them:
- apps/web/src/i18n/**
- apps/web/locales/**
- apps/web/src/app/** (except layout.tsx infrastructure stubs)
- apps/web/src/components/**
- apps/web/src/middleware.ts
- next-intl wiring
- RTL direction switcher
- Locale files (en/ar common.json, etc.)

If your work appears to require touching a Wave D file, return BLOCKED:
<reason> instead of editing it.
</wave_boundary>
```

**Scaffold stub header (Phase 4.7b) — language-agnostic marker:**

The marker `@scaffold-stub: finalized-by-wave-<X>` is comment-syntax-INDEPENDENT. Comment glyph varies by file type:

* TypeScript / JavaScript / Next.js / NestJS:
  ```typescript
  // @scaffold-stub: finalized-by-wave-D
  // purpose: locale-aware middleware (next-intl); Wave D adds JWT cookie forwarding
  // allowed-modifications-by-wave-B: none
  // allowed-modifications-by-wave-D: full
  ```
* Python (if any scaffold targets Python apps):
  ```python
  # @scaffold-stub: finalized-by-wave-D
  # purpose: ...
  ```
* YAML / `.env.example`:
  ```yaml
  # @scaffold-stub: finalized-by-wave-D
  ```
* Prisma / SQL: `--` (e.g., `-- @scaffold-stub: finalized-by-wave-B`)
* JSON does NOT support comments — for JSON stub files (e.g., locale `common.json`), use a sibling `<filename>.scaffold-stub.txt` marker file containing the metadata.

The audit reader must accept ALL leading comment glyphs (`//`, `#`, `--`) before `@scaffold-stub:`.

**Audit reads header:**

```python
# audit_models.py (extends from_dict)
_SCAFFOLD_STUB_RE = re.compile(
    r"^\s*(?://|#|--|\*|/\*\*?)\s*@scaffold-stub:\s*finalized-by-wave-(?P<wave>[A-Z]\d?)",
    re.MULTILINE,
)

def _read_scaffold_stub_owner(file_path: str, project_root: str) -> str | None:
    """Reads first 8 lines of file; if @scaffold-stub: finalized-by-wave-X
    found, returns 'X'; else None. Handles all comment-syntax variations."""
    # Reads 8 lines (not 5) to allow license headers + spacing before stub marker.
```

**ACs:**
* AC1: Wave B prompt contains `<wave_boundary>` block.
* AC2: Wave B allowed_globs do NOT blanket-include `apps/web/**` when Wave D in milestone wave-set.
* AC3: Scaffold-emitted stubs have machine-readable header.
* AC4: Audit `from_dict` reads header and overrides path-based owner_wave.
* AC5: Replay smoke: F-001 finding gets owner_wave="D" + DEFERRED.
* AC6: Wave B prompt for the same M1 has 0 mentions of i18n/locales/components in allowed-globs (narrowed).

**Rollback:** New `<wave_boundary>` block is additive; if it confuses providers, gate on `wave_boundary_block_enabled = True` flag (default True). Scaffold header is also additive; old finding-classification path falls back when header absent.

---

## Section K — Per-Phase Verification Scripts (gates)

**Phase 4.1 promote-gate:**
1. `pytest tests/test_pipeline_upgrade_phase4_1.py` — all 6 fixtures green.
2. Replay smoke: load `WAVE_FINDINGS.json`; assert `_resolve_per_wave_service_target("B", ...) == ["api"]`.
3. Synthetic 1-milestone smoke with Phase 4.1 active: Wave B passes if api builds.
4. Existing `tests/wave_executor/` + `tests/test_v18_phase2_wave_engine.py` green.
5. Rollback: flip `per_wave_self_verify_enabled = False`; existing test_v18_phase2_wave_engine fixtures still green.

**Phase 4.2 promote-gate:**
1. `pytest tests/test_pipeline_upgrade_phase4_2.py` — all 7 fixtures green.
2. Context7-locked tsc/buildkit/Next error format unit tests included.
3. Replay smoke: synthesize new payload from real codex-captures stderr; assert ≥10x richer than current.
4. Rollback: flip `strong_retry_feedback_enabled = False`.

**Phase 4.3 promote-gate:**
1. `pytest tests/test_pipeline_upgrade_phase4_3.py` — all 11 fixtures green.
2. Replay smoke: 4+ critical findings get DEFERRED status; convergence ratio improves.
3. Phase 1-3.5 fixtures still green (audit-fix dispatch correctly skips DEFERRED).
4. Rollback: flip `audit_wave_awareness_enabled = False`.

**Phase 4.4 promote-gate:**
1. `pytest tests/test_pipeline_upgrade_phase4_4.py` — all 7 fixtures green.
2. Replay smoke: simulated `WAVE_FAILURE_FORENSICS.json` matches expected schema.
3. Cost savings simulated: ~$5-8 saved on synthetic wave-fail.
4. Rollback: flip `failed_milestone_audit_on_wave_fail_enabled = True`.

**Phase 4.5 promote-gate:**
1. `pytest tests/test_pipeline_upgrade_phase4_5.py` — all 7 fixtures green.
2. Phase 1 Risk #1 fixture (`test_run_audit_fix_unified_skipped_when_safety_nets_disabled`) still green.
3. `pytest tests/test_hook_multimatcher_conflict.py` still green.
4. Replay smoke: 3 Codex bug features dispatched, 4 DEFERRED features skipped.
5. **Full M1 smoke required** — empirical proof of recovery cascade.
6. Rollback: flip `lift_risk_1_when_nets_armed = False`.

**Phase 4.6 promote-gate:**
1. `pytest tests/test_pipeline_upgrade_phase4_6.py` — all 9 fixtures green (8 from §0.7 + 1 mutex fixture).
2. 2-milestone synthetic smoke + retry-milestone test.
3. Disk-quota warning fires at 2GB.
4. **Full M1 smoke required** — anchor primitive change.
5. Rollback: `anchor_chain_retain_last_n = 0`.

**Phase 4.7 promote-gate:**
1. `pytest tests/test_pipeline_upgrade_phase4_7.py` — all 6 fixtures green.
2. Replay smoke: F-001 finding gets owner_wave="D" + DEFERRED via stub header.
3. Re-rendered Wave B prompt has 0 ambiguity (manual diff review).
4. **Full M1 smoke required** — touches prompt + scaffold.
5. Rollback: flip `wave_boundary_block_enabled = False` AND scaffold-header-aware audit reverts to path-only classification.

---

## Section L — What we WON'T Do (anti-patterns)

* **Don't lift Risk #1 unconditionally.** Only conditional lift when ALL safety nets armed. Otherwise we re-introduce the M25-disaster risk that Phase 1-3.5 prevented.
* **Don't make retry feedback an LLM call.** Phase 4.2's payload is deterministic (regex + AST-light scan). LLM-driven feedback belongs in audit-fix (Phase 4.5), not in retry feedback (cost + latency).
* **Don't auto-resume on failure.** Phase 4.6's `--retry-milestone` is OPERATOR-INVOKED only. Auto-resume on failure is dangerous (could mask repeated failures, cost explosion).
* **Don't change scaffold semantics aggressively.** Phase 4.7b's stub header is additive. If we drop scaffold stubs entirely (cleaner alternative), it's a separate phase with its own test suite.
* **Don't grow per-wave allowlists for specific files.** Phase 4.7a NARROWS allowed_globs by default. Specific exceptions (apps/web/Dockerfile for Wave B) are minimal and named.
* **Don't add a separate audit pass for wave-fail.** Phase 4.4's deterministic forensics is the answer. Adding ANOTHER LLM audit just because it's wave-fail is the wrong direction.
* **Don't break existing tests.** §0.1 #16 invariant: UPGRADE only. Every change is additive or config-gated.
* **Don't paper over halts.** §0.10. Surface, document, fix at root cause.
* **Don't re-enable old failure modes via misconfiguration.** When a config flag is False, the OLD behavior is preserved (no worse than today). When True, the new behavior is enabled. The default for ALL Phase 4 flags is `True` (new behavior on); operators can flip to `False` to roll back per-phase.

---

## Section M — Cross-cutting concerns + open questions

### M.1 Provider differences (Codex vs Claude)

Phase 4.7a's `<wave_boundary>` block must work for BOTH Codex (Wave B) and Claude (Wave D). Context7 lookup for both providers is mandatory before Phase 4.7 ships. If either provider has special handling for `<scope>` / `<boundary>` style blocks, document and lock.

### M.2 The `STATE.json` vs `milestone_progress.json` split-write — RESOLVED (Risk #28)

Two files write `interrupted_milestone`; they disagree post-failure (per smoke evidence — `STATE.json::interrupted_milestone = None` while `milestone_progress.json::interrupted_milestone = "milestone-1"`).

**Resolution (locked):** Phase 4.5's `_run_audit_loop` epilogue is the reconciliation point (it's the final orchestration step before exit). After audit-fix terminates, Phase 4.5 emits a single write that reconciles both files. Add fixture: `test_state_and_milestone_progress_agree_on_interrupted_milestone`. Tracked as Risk #28 (closed by Phase 4.5).

### M.3 Codex sandbox locking — KNOWN LIMITATION (Risk #29)

Codex couldn't run `docker compose build` in its sandbox due to Windows buildx lock conflict (`C:\Users\<user>\.docker\buildx\.lock: Access is denied`). NOT fixable from agent-team's side — it's a Docker Desktop / Windows infrastructure issue.

**Mitigation (locked):** Phase 4.2's richer feedback REMOVES the NEED for Codex to re-run the failing command (it gets enough signal from parsed errors + unresolved imports). Document in Phase 4.2 landing as KNOWN LIMITATION mitigated by feedback richness. Risk #29 stays open as known-limitation; revisit if Docker Desktop's buildx locking changes upstream.

### M.4 Phase 4.5 reuse of single existing audit-fix loop

Phase 4.5's lift means `_run_audit_fix_unified` now runs in TWO contexts: (a) convergence-fail with all waves passing (today's path), (b) wave-fail with all safety nets armed (new path). The function should NOT branch internally on context; both paths flow through the same loop. The DIFFERENCE is in `_run_audit_loop`'s epilogue (Phase 4.5's re-self-verify only fires on context b).

### M.5 Anchor coexistence — RESOLVED

**Filesystem layout (locked):**
* Phase 1 anchor (in-flight, single-slot, captured at IN_PROGRESS-entry) — `.agent-team/milestones/<id>/_anchor/<file-tree>` (existing layout, unchanged).
* Phase 4.6 anchor (per-milestone chain, captured at COMPLETE) — `.agent-team/milestones/<id>/_anchor/_complete/<file-tree>` (NEW subdir).

**Restore precedence (locked):**
* In-flight rollback (Phase 1's audit-fix divergence within milestone N) → restore from CURRENT milestone N's `_anchor/` top-level files (existing Phase 1 contract).
* Cross-milestone resume (Phase 4.6's `--retry-milestone N+1`) → restore from PRIOR milestone N's `_anchor/_complete/` subdir.

These never conflict — different milestones, different subpaths.

**Capture sequencing on milestone N:**
1. M(N) IN_PROGRESS fires → `_capture_milestone_anchor(cwd, N)` writes to `_anchor/` top-level (Phase 1, single-slot, wipes any prior M(N) capture).
2. M(N) waves execute.
3. (Phase 4.5 path:) If wave-fail + recovery, audit-fix may restore from `_anchor/` mid-flight. Phase 1 contract.
4. M(N) reaches COMPLETE → `_capture_milestone_anchor_on_complete(cwd, N)` writes to `_anchor/_complete/` subdir (Phase 4.6, per-milestone chain).
5. M(N+1) IN_PROGRESS fires → `_capture_milestone_anchor(cwd, N+1)` writes to milestone N+1's directory. M(N)'s `_anchor/` and `_anchor/_complete/` BOTH survive.

Phase 4.6 fixture `test_complete_and_inprogress_anchors_coexist_correctly` locks this contract.

### M.6 Disk quota at 25-milestone scale

Phase 1 measured 75 MB / M1-anchor on the agent-team-v18-codex repo proxy. M25-anchor would include 25 milestones' worth of source. Realistic estimate: 200-500 MB per anchor on a real M25-class build. Chain of 5: 1-2.5 GB. Phase 4.6's WARNING threshold of 2GB is reasonable; revisit if real-world builds exceed.

### M.7 Scaffold reform — RESOLVED: Path A (header convention)

**Decision (locked for Phase 4.7):** Path A (header convention).

* Stubs continue to exist; gain machine-readable `@scaffold-stub: finalized-by-wave-<X>` header (language-agnostic comment glyph; see §J).
* Audit reads header; finding inherits owner_wave from the header (overrides path-based classification when both apply).
* Less invasive; preserves the existing scaffold contract that pre-creates module skeletons.

**Path B (drop stubs entirely)** is explicitly OUT OF SCOPE for Phase 4 and a candidate for Phase 5+ IF:
* Path A's header convention turns out brittle (e.g., Codex reformats files and strips headers).
* OR scaffold stubs are observed to consistently mislead Codex despite the boundary block (Phase 4.7a).
* OR a deeper rethink of scaffold-vs-wave-D contract is taken on.

Path B requires its own discovery + design phase; not a drop-in replacement for Path A.

### M.8 Test fixture lifecycle

All Phase 4 fixtures named `test_replay_smoke_2026_04_26_*` are LOCKED CONTRACTS. They use real artifacts from `v18 test runs/m1-hardening-smoke-20260426-173745/`. If the smoke directory is ever pruned (test-artifact disk reclamation), these fixtures need a frozen copy committed to `tests/fixtures/smoke_2026_04_26/` (subset). Plan-level invariant: before pruning ANY smoke run-dir referenced in test fixtures, run `pytest tests/ -k replay_smoke` to confirm no breaks.

---

## Section N — Verifier Report (Phase 4 plan self-verification)

**Citations verified ✓** as of 2026-04-26:
* `v18 test runs/m1-hardening-smoke-20260426-173745/.agent-team/codex-captures/milestone-1-wave-B-prompt.txt` exists, 52,574 chars, contains "Allowed file globs" + "Allowed feature/AC references" + 0 mentions of "Wave D".
* `.agent-team/milestones/milestone-1/WAVE_FINDINGS.json` exists, has per-service `(file: api|web)` attribution.
* `.agent-team/STATE.json::milestone_progress.milestone-1` is `{"status": "FAILED"}` with no `failure_reason`.
* `apps/web/src/middleware.ts` literal content includes `// SCAFFOLD STUB — Wave D finalizes with JWT cookie forwarding.`
* `AUDIT_REPORT.json` has 46 findings, severity dist `{critical: 11, high: 17, medium: 13, low: 5}`.
* `src/agent_team_v15/wave_b_self_verify.py:98` defines `run_wave_b_acceptance_test`; `:83-95` defines `_build_retry_prompt_suffix`. Confirmed by Read at 2026-04-26.
* `src/agent_team_v15/cli.py:7116` defines `_run_audit_fix_unified`; `:7559` `_run_failed_milestone_audit_if_enabled`; `:7602` `_handle_audit_failure_milestone_anchor`. Confirmed by Grep at 2026-04-26.
* `src/agent_team_v15/templates/` contains `pnpm_monorepo/` and `scaffold_assets/` directories. `src/agent_team_v15/scaffold_runner.py` is the runner.
* No `wave_d_self_verify.py` exists — Phase 4.1 creates it.
* No `prompt_builder.py` exists — Phase 4.7 implementer must locate the actual prompt source files via grep.

**Risks I'm aware of and explicitly NOT closing in Phase 4:**
* Wave A's `STACK-IMPORT-002` ("No file in the wave output contains a required stack-contract import") — Wave A architecture spec quality is OUT OF SCOPE for Phase 4. Candidate for Phase 5.
* PRD-decomp / MASTER_PLAN milestone-scoping (M1 had 39 requirements; should be ~8). User explicitly deferred.
* Codex provider quirks beyond what Context7 documents.

**What I might be wrong about (verify at implementation time):**
* The exact regex for tsc / buildkit / Next error formats (Phase 4.2). Context7 lookup at Phase-4.2 implementation time locks the canonical format.
* Whether `_classify_fix_features` in Phase 3.5 already handles owner_wave or needs Phase 4.3 to wire it. Phase 4.3 implementer must verify by reading current code.
* Whether `apps/web/Dockerfile` and `apps/web/.env.example` should be Wave B-touchable or Wave D-touchable. Phase 4.7 design decision; document in landing.
* Phase 4.5's order: should re-self-verify happen ONLY on wave-fail-recovery, or ALSO on convergence-fail-recovery? Plan says ONLY on wave-fail-recovery (convergence-fail recovery already passes self-verify by definition since waves succeeded). Lock in Phase 4.5 landing.
* The exact source files of Wave B / Wave D prompt construction. The plan listed candidates (`codex_prompts.py`, `audit_prompts.py`, `codex_fix_prompts.py`, `template_renderer.py`, `wave_a5_t5.py`, `v18_specialist_prompts.py`); Phase 4.7 implementer's first task is grepping `"Allowed file globs"` and `"FRAMEWORK INSTRUCTIONS"` to find the actual owners.
* Whether `docker_build` (in `wave_b_self_verify.py` or a sibling utility) accepts a `services` argument today, OR whether Phase 4.1 must also extend the underlying Docker invocation. Verify by reading the function.
* Whether Phase 4.6's COMPLETE-anchor capture should fire on `DEGRADED` status as well as `COMPLETE`. Default in plan: COMPLETE only. Phase 4.6 implementer should verify by checking how DEGRADED milestones are treated by `get_ready_milestones` (current Phase 1 OQ4: `("COMPLETE", "DEGRADED")` is treated as completed at SOME call sites).
* Whether the audit team's prompt itself needs updating to know about wave-awareness (Phase 4.3) or whether updating the convergence-ratio computation is sufficient. Default in plan: only computation changes. If the audit team's PROMPT also needs Wave-D-deferred awareness to avoid emitting findings as critical, surface as `[NEW — Phase 4.3]`.

---

## End of plan

Total estimated effort: 7 phases × 2-7 days each = **22-35 days of focused implementer time**. Phases 4.1-4.4 are ~2-3 days each (small, composable). Phases 4.5-4.7 are 4-7 days each (touch core orchestration / prompts).

Shipping order (per §0): 4.1 → 4.2 → 4.3 → 4.4 → 4.5 → 4.6 → 4.7. Strictly sequential; later phases depend on earlier landings.

After Phase 4.7 lands and a fresh full M1 smoke is clean, the orchestrator's input-quality and recovery layers are at their post-Phase-4 end-state:
* Wave dispatches are scope-narrowed and graded only on their own deliverables.
* Retry feedback is structured and actionable.
* Audit team is wave-aware; convergence is computed correctly.
* Wave-fail forensics are deterministic + cheap.
* Recovery cascade is automatic for fixable failures.
* Operator escape hatch (resume-from-failed) handles unfixable cases.
* Wave prompts and scaffold artifacts have explicit boundaries.

The M25-disaster scenario — M(N) wave-fail discarding M1-M(N-1) progress — is structurally prevented at every layer.
