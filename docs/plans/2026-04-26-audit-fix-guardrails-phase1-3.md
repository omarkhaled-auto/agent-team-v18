# Audit-Fix-Loop Guardrails — Phase 1-3 Plan

**Date:** 2026-04-26
**Scope:** Hardening agent-team-v15 audit-fix-loop against M25/M30-class catastrophic failures.

---

## Section 0 — Execution Plan (READ FIRST, before any code in any session)

This plan ships in **three sessions**, one Phase per session. Each session is run by ONE focused implementer agent. The implementer must follow the cross-session invariants in §0.1 and the per-session brief in §0.2/0.3/0.4. Sessions are dependency-ordered; Session 2 cannot start until Session 1 has shipped clean, etc.

### 0.0 Kickoff prompt templates (copy-paste verbatim per session)

**Session 1 kickoff prompt:**
```
You are Session 1 of the audit-fix-loop guardrails implementation.

Read docs/plans/2026-04-26-audit-fix-guardrails-phase1-3.md top-to-bottom — Section 0 first.
Then read ~/.claude/projects/C--Projects-agent-team-v18-codex/memory/MEMORY.md.

Follow §0.1 (cross-session invariants — all 19 rules) and §0.2 (Session 1 brief).
Implement Phase 1 (Section D). When done, write phase_1_landing.md per §0.5.

Stop conditions are §0.6. NEVER paper over a halt.
```

**Session 2 kickoff prompt:**
```
You are Session 2 of the audit-fix-loop guardrails implementation.

Read docs/plans/2026-04-26-audit-fix-guardrails-phase1-3.md top-to-bottom.
Then read ~/.claude/projects/C--Projects-agent-team-v18-codex/memory/MEMORY.md
AND ~/.claude/projects/C--Projects-agent-team-v18-codex/memory/phase_1_landing.md.

Confirm Phase 1 is merged + smoke clean before starting.

Follow §0.1 (cross-session invariants) and §0.3 (Session 2 brief).
Implement Phase 2 (Section E). Write phase_2_landing.md per §0.5.

Stop conditions are §0.6.
```

**Session 3 kickoff prompt:**
```
You are Session 3 of the audit-fix-loop guardrails implementation.

Read docs/plans/2026-04-26-audit-fix-guardrails-phase1-3.md top-to-bottom.
Then read MEMORY.md + phase_1_landing.md + phase_2_landing.md.

Confirm Phase 1 + Phase 2 are merged + smoke clean before starting.

Follow §0.1 and §0.4 (Session 3 brief).
Implement Phase 3 (Section F). Write phase_3_landing.md per §0.5.

Stop conditions are §0.6.
```

### 0.0a Branching workflow — direct-to-master (per user direction 2026-04-26)

**No branching. No PRs. All sessions commit and push directly to `master`.** This is the explicit workflow chosen for this work; do not create feature branches, do not open pull requests, do not stash. Each session's commit is self-contained and reversible via `git revert <sha>`.

**Pre-Session-1 baseline (already established):**
- Commit `ce06e24` (2026-04-26) on master = `feat(m1-hardening): smoke-driven hardening + Wave D sandbox + audit-fix guardrails plan` — folded in the 2026-04-25 smoke-driven product fixes (Wave D path-guard sandbox, universal scaffold root files exemption, e2e/tests exemption, api-client `@hey-api/client-fetch` dep, root `prisma/` STACK-PATH-001 exemption, `apps/web/package.json` Wave B exception), the m1_fast_forward harness, and THIS plan doc itself.
- Session 1 starts from `ce06e24` (or whatever HEAD is when Session 1 actually runs — sessions re-verify per §0.1 #4).

**Per-session commit convention:**
- Each session lands ONE commit on master with the format `feat(audit-fix-guardrails): Phase <N> — <one-line summary>`.
- Commit body: bulleted list of files touched + behavior added + ACs covered + smoke-gate summary.
- Use HEREDOC for the message (Windows-compatible) so newlines are preserved.
- Push immediately (`git push origin master`).
- Write the post-merge memory file (§0.5) AFTER the push lands.

**Rollback path if a session's commit breaks the pipeline:**
- `git revert <sha>` (creates a NEW revert commit; never `git reset --hard` master).
- Re-push.
- Surface to user; do NOT auto-restart the session.

### 0.1 Cross-session invariants — apply to EVERY session

These are the load-bearing rules. Skipping any one of them re-introduces the failure modes this plan exists to prevent.

**Pre-flight before any code:**
1. Re-read this ENTIRE plan top-to-bottom (Section 0 → I), not just the phase you're implementing. Cross-phase context informs why ACs exist.
2. Re-read user auto-memory at `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/MEMORY.md` — especially `feedback_structural_vs_containment.md`, `feedback_verification_before_completion.md`, `feedback_inflight_fixes_need_authorization.md`, and the `phase_<N-1>_landing` memory written by the previous session.
3. Verify editable install: `python -c "import agent_team_v15; print(agent_team_v15.__file__)"` — must resolve under the repo's `src/`. If not, `pip install -e .` first.
4. **Verify every cited `file:line` in this plan still matches current source.** Citations are timestamped 2026-04-26. The codebase mutates between sessions. Use Read tool with the cited line + context. If ANY citation is stale: STOP. Update the plan with the new line numbers before implementing. Document the drift in memory so the next session knows the codebase moved.
5. Run the broader test slice covering touched files BEFORE starting work — must be green. If red, STOP and surface to the user.
6. Confirm the prior session's smoke gate is green (or explicitly accept-failed by user).

**During implementation:**
7. **TDD discipline (NON-NEGOTIABLE):** write the failing test FIRST. Run it. Confirm it fails with the EXPECTED error — not a typo, not an import error. THEN implement. Per `superpowers:test-driven-development`.
8. **One phase per session.** No spillover. If a phase isn't done in a session, ship the synthetic test fixtures as `pytest.mark.xfail` and pause. Memory-write the cliff edge so the next session can resume cleanly.
9. **Investigate yourself, do not trust the plan blindly.** When the plan says "modify file X at line Y" — go read X line Y, confirm the surrounding context still matches the plan's narrative. The plan was synthesized from a discovery sprint; ground-truth always wins.
10. **Use Context7 (`mcp__context7__resolve-library-id`, then `mcp__context7__query-docs`) for ANY library / SDK / CLI / framework question.** Never trust training data — APIs drift between minor versions. Required Context7 lookups per session are listed in §0.2/0.3/0.4 below; you may add more.
11. **Use sequential-thinking MCP (`mcp__sequential-thinking__sequentialthinking`) when:**
    - Two primitives interact in a non-obvious way (e.g., anchor vs api-client snapshot ordering).
    - You discover a new risk not in the §C register.
    - The plan's approach hits unexpected friction (e.g., a precondition you assumed turns out to not hold).
    - You're about to make a design decision that wasn't explicitly resolved by the verifier in §I.
12. **If you discover a NEW risk:** STOP. Add it to §C with `[NEW — Session <N>]` annotation. Surface it to the user. Do NOT proceed silently — the M25 disaster scenario is exactly what happens when sessions paper over discoveries.
13. **If a citation is stale or a primitive doesn't behave as the plan describes:** STOP. Update the plan. Document the drift in your end-of-session memory write. The plan is a living document; treat any divergence from current source as a signal that the plan is now wrong, and FIX THE PLAN before continuing.

**Pre-merge gate:**
14. All ACs for the phase have a passing test that targets them.
15. Existing test slices (broader than touched files) still green.
16. Run the fast-forward harness: `& .\scripts\run-m1-fast-forward.ps1` — all 6 gates pass, `ready_for_full_smoke: true` in `fast-forward-report.json`.
17. Run the phase-specific smoke gate listed in §G of this plan. If any gate fails, ROLL BACK per the phase's rollback plan, do not "patch and retry."
18. Diff review: `git diff master...HEAD` — read every line you wrote one more time, looking specifically for: leftover debug logs, hardcoded values that should be config, error handlers that swallow context, accidental edits to files outside the phase's declared file list.

**Post-merge memory write (NON-NEGOTIABLE):**
19. Write `phase_<N>_landing.md` to `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/` capturing:
    - Actual function signatures shipped (may differ from plan).
    - Anchor disk size on the test smoke (for sizing later milestones).
    - Surprises: anything the plan got wrong, anything new you learned about the existing code.
    - Risks now closed (with how they were verified).
    - What the next session MUST know.
    - Add the index entry to `MEMORY.md`.

### 0.2 Session 1 — Phase 1 (Recoverable + Immutable + Transactional)

**Goal:** §D — milestone-anchor (with delete-untracked) + critical-immutables denylist + skip-audit-on-wave-fail + promote-existing-CRITICAL-warn-to-exit + audit-fail → STATE.json mark + DEGRADED disambiguation.

**Pre-flight (in addition to §0.1):**
1. Re-verify these citations specifically (the spine of Phase 1): `cli.py:7054`, `cli.py:3646`, `cli.py:4729`, `audit_team.py:93-133`, `audit_team.py:123-132`, `wave_executor.py:813,840,892`, `wave_executor.py:726`, `state.py:655-663`, `milestone_manager.py:41,74-82`, `fix_executor.py:577`. If any moved: STOP, update plan §D with the new lines, document in memory.
2. Run: `pytest tests/test_wave_scope_filter.py tests/test_stack_contract.py tests/test_v18_phase2_wave_engine.py tests/test_v18_specialist_prompts.py tests/test_scaffold_m1_correctness.py tests/test_scaffold_runner.py tests/test_openapi_launcher_resolution.py tests/test_wave_d_path_guard.py tests/test_agent_teams_backend.py tests/wave_executor/ tests/test_codex_observer_checks.py` — green baseline.
3. Confirm `audit_team.AuditScore` schema (`critical_count`, `score` fields). Read `src/agent_team_v15/audit_team.py:1-60` for dataclass definitions.

**Required Context7 lookups (no guessing):**
- `/python/cpython` (or stdlib docs): `shutil.copy2` mtime preservation guarantee + `shutil.copytree` exception classes; `tempfile.mkstemp` + `os.replace` atomicity contract on Windows (POSIX vs NTFS — confirm rename atomicity holds; if the running OS is Windows, look up the `os.replace` Windows-specific note).
- `/microsoft/playwright` only if Phase 1 fixtures touch Playwright invocation (probably not for Phase 1 — defer to Session 2).

**TDD sequence (strict order):**
1. Create `tests/test_audit_fix_guardrails_phase1.py` with all 6 fixtures from §D verbatim. Run pytest → all 6 fail with the expected `AttributeError`/`ImportError` for the not-yet-existing functions. **Do NOT proceed if the failures are wrong-shaped** (e.g., a `SyntaxError` means your test file is broken).
2. Implement files in this order (each file's tests should flip green after that file's commit):
   1. `src/agent_team_v15/state.py` — RunState schema additions (Phase 1 §D file #7). Smallest change; confirm RunState (de)serialization round-trip in a unit test.
   2. `src/agent_team_v15/milestone_manager.py:41` — docstring update (file #8). Trivial; gives Phase 1 a low-risk first commit.
   3. `src/agent_team_v15/wave_executor.py` — `_capture_milestone_anchor` + `_restore_milestone_anchor` (file #1). Bulk of Phase 1's logic. Use `_checkpoint_file_iter:726` for skip-filter consistency. Test Fixture 3 (delete-untracked) flips green here.
   4. `src/agent_team_v15/audit_team.py:123-132` — promote WARN to `return True, "regression"` (file #5). Test Fixture 2 flips green.
   5. `src/agent_team_v15/cli.py:7054` — `if not wave_result.success: return [], 0.0` wrap (file #2). Test Fixture 1 flips green.
   6. `src/agent_team_v15/cli.py:3646` — anchor capture invocation (file #3). No fixture flips here yet (anchor is a side effect; restore is what tests).
   7. `src/agent_team_v15/cli.py` reaudit termination — restore + `update_milestone_progress(milestone.id, "FAILED")` (file #4). Test Fixture 5, 6 flip green.
   8. `src/agent_team_v15/fix_executor.py` — denylist param (file #6). Test Fixture 4 flips green.
3. After each file commit, run `pytest tests/test_audit_fix_guardrails_phase1.py -x --tb=short` — STOP at first unexpected red.

**Pre-merge gate (Phase 1 specific, in addition to §0.1 §14-18):**
1. All 6 fixtures + existing test slice green.
2. Fast-forward harness all 6 gates pass.
3. **Anchor disk-size smoke:** run a partial M1 (Wave A only) with anchor enabled. Measure `du -sh .agent-team/milestones/milestone-1/_anchor/` — must be < 200MB. If larger, the skip filter is missing a directory; fix `_checkpoint_file_iter` not the anchor code.
4. **Synthetic audit-failure smoke:** craft a unit test that drives `_run_audit_fix_unified` to terminate "regression" (mock `should_terminate_reaudit`) and assert: (a) anchor restore fires, (b) `STATE.json.milestone_progress["milestone-1"].status == "FAILED"`, (c) untracked files created during the cycle are deleted.
5. **No full M1 smoke required for Phase 1** — anchor only fires on audit-fail, which a clean M1 should not hit. (If you want defense-in-depth, run a full M1 smoke and confirm it's a no-op vs. master.)

**Memory write after Phase 1 merge (write to `phase_1_landing.md`):**
- Actual `_capture_milestone_anchor` / `_restore_milestone_anchor` signatures (may differ from plan §D).
- Anchor disk size measured on M1 smoke (key sizing input for Phase 2/3 and the M25-disaster prediction).
- Whether `os.replace` atomicity worked as documented on Windows (Risk #3 verification).
- Risks now closed: #1 (skip-on-wave-fail), #3 (STATE.json atomicity in real run), #4 (anchor delete-untracked verified by Fixture 3), #15 (audit-fail FAILED mark verified by Fixture 5), #16 (DEGRADED disambiguation verified by Fixture 6).
- Note for Session 2: the anchor primitive's API surface (Phase 2's test-surface lock will read from it).

### 0.3 Session 2 — Phase 2 (Cross-milestone test-surface lock)

**Pre-condition:** Session 1 merged + smoke clean. `phase_1_landing.md` memory exists. Read it FIRST.

**Pre-flight (in addition to §0.1):**
1. Re-verify Phase 2 citations: `evidence_ledger.py:62-78`, `fix_executor.py:577`, `cli.py:7135-7149`, `audit_models.py:126-131,705`, `browser_test_agent.py:219`. STOP if drift.
2. Confirm Phase 1's anchor primitive API by reading `phase_1_landing.md` (signatures may differ from plan).
3. Run: `pytest tests/test_audit_fix_guardrails_phase1.py tests/test_evidence_ledger.py tests/test_fix_executor.py tests/test_runtime_verification_block.py tests/test_v18_wave_t.py` — green baseline.

**Required Context7 lookups (no guessing — these closed gaps the original Wave 1 research left):**
- `/microsoft/playwright`:
  - **CRITICAL — Risk #12:** capture the actual JSON reporter top-level schema. Run `npx playwright test --reporter=json` once on a tiny fixture, save the full output as `tests/fixtures/playwright_json_snapshot.json`, then query Context7 to confirm field names match a stable contract. Document any field that's NOT in stable contract as fragile-parse.
  - `--last-failed` + positional file args interaction (does `--last-failed` ignore positional filters?).
  - Test status enum stability across versions — confirm `passed/failed/timedOut/skipped/interrupted` is the full set.
- `/pnpm/pnpm.io`:
  - Risk #13: `pnpm install` on `package.json` — fetch the EXPLICIT no-write contract or confirm it's empirical-only. If empirical, pin a smoke that asserts `package.json` mtime is unchanged after `pnpm install --frozen-lockfile`.
  - `--frozen-lockfile` CI guidance citation (Risk #14).

**TDD sequence (strict order):**
1. Create `tests/test_audit_fix_guardrails_phase2.py` + `tests/fixtures/playwright_json_snapshot.json` (the captured real output). Tests fail with expected import errors.
2. Implement files in this order:
   1. `src/agent_team_v15/evidence_ledger.py:62-78` — schema extension `test_surface` field. Backward-compat additive.
   2. `src/agent_team_v15/audit_models.py:126-131` — AC-to-test mapping helper.
   3. `src/agent_team_v15/cli.py:7135-7149` (`_convert_findings`) — propagate test_surface.
   4. `src/agent_team_v15/fix_executor.py:577` (`run_regression_check`) — accept test_surface_lock arg, run subset Playwright via positional file args.
   5. `src/agent_team_v15/wave_executor.py` — persist baseline at milestone COMPLETE.
3. After each file: re-run pytest, fixture flips green.

**Pre-merge gate (Phase 2 specific):**
1. All Phase 2 fixtures green; Phase 1 fixtures still green.
2. **Cross-milestone regression smoke:** craft a 2-milestone synthetic build (M1 + M2 trivial) where M2's audit-fix loop intentionally regresses an M1 test. Assert lock violation raised, fix rejected.
3. **Playwright JSON parser:** snapshot diff against `tests/fixtures/playwright_json_snapshot.json` — must be byte-identical or the parser shape changed.
4. **No full M-N smoke needed yet** — Phase 2 doesn't change normal-path behavior, only audit-fail-path test rerun shape.

**Memory write (`phase_2_landing.md`):**
- Test-surface attribution heuristic chosen (Phase 2 OQ1 resolution).
- Playwright JSON schema fields actually used (locks the parser contract).
- Risks closed: #12, possibly #14.
- Note for Session 3: env var propagation contract (Phase 3 will rely on it).

### 0.4 Session 3 — Phase 3 (Per-finding hook + scope enforcement)

**Pre-condition:** Sessions 1+2 merged + smoke clean. `phase_2_landing.md` exists.

**Pre-flight (in addition to §0.1):**
1. Re-verify Phase 3 citations: `wave_d_path_guard.py:55-105,108-135,138-198`, `cli.py:7135-7149`, `agent_teams_backend.py` (find `_ensure_wave_d_path_guard_settings` or equivalent).
2. Confirm Phase 1+2 fixtures still green (`pytest tests/test_audit_fix_guardrails_phase1.py tests/test_audit_fix_guardrails_phase2.py`).
3. Run: `pytest tests/test_wave_d_path_guard.py tests/test_agent_teams_backend.py` — green baseline.

**Required Context7 lookups (closes the 8 NOT-FOUND items from Wave 1):**
- `/anthropics/claude-code`:
  - **Risk #6 (multi-matcher conflict resolution):** definitive doc on whether deny+allow on same call resolves to deny. If not in docs, design a fail-loud test that exercises both and asserts deny-wins; if Claude Code changes resolution, the test fails so we notice.
  - **Risk #7 (env var propagation contract):** is `AGENT_TEAM_*` propagation guaranteed or empirical? If still NOT FOUND in docs, the smoke in step 4 below becomes load-bearing.
  - **Risk #8 (hook timeout overrun):** what does Claude Code do when `timeout: 5000` trips? Block? Allow? Error?
  - **Risk #10 (settings precedence):** order between `~/.claude/settings.json`, repo `.claude/settings.json`, `.local.json`, managed.
  - **Risk #11 (subprocess CWD pickup):** does `claude` invoked as subprocess from a non-project CWD pick up the run-dir's `.claude/settings.json`?
- For each NOT-FOUND that REMAINS not found after re-query: file an explicit fail-loud assertion in the test suite (so a future Claude Code release that changes the behavior makes our test break visibly).

**TDD sequence (strict order):**
1. Create test files: `tests/test_audit_fix_guardrails_phase3.py`, `tests/test_hook_multimatcher_conflict.py`. Note: NO `test_hook_canonical_shape.py` — Risk #9 is closed.
2. Implement files:
   1. `src/agent_team_v15/wave_d_path_guard.py` — extract `_decide_from_allowlist(rel_path, allowed_prefixes, allowed_files)` helper; behavior-preserving refactor. Existing `tests/test_wave_d_path_guard.py` must stay green.
   2. NEW `src/agent_team_v15/audit_fix_path_guard.py` — companion hook. Reads `AGENT_TEAM_FINDING_ID`, `AGENT_TEAM_ALLOWED_PATHS` from env. Fail-CLOSED on parse error (stricter than Wave D).
   3. `src/agent_team_v15/cli.py:7135-7149` (`_convert_findings`) — emit env vars per dispatch.
   4. `src/agent_team_v15/agent_teams_backend.py` — extend settings.json writer to add audit-fix-path-guard PreToolUse entry alongside Wave D's; explicit `timeout: 5000`.
3. After each file, re-run pytest.

**Pre-merge gate (Phase 3 specific):**
1. All Phase 3 + Phase 2 + Phase 1 fixtures green.
2. **Live hook smoke (Risk #6+#7 pin):** spawn a real audit-fix dispatch on a tmp run-dir; observe `AGENT_TEAM_FINDING_ID` in the hook's stdin/env; attempt out-of-allowlist write; observe canonical deny envelope. Capture the actual hook stdin payload as `tests/fixtures/hook_stdin_payload.json` for future reference.
3. **Multi-matcher conflict regression:** the test `test_hook_multimatcher_conflict.py` must fail loudly if Claude Code's resolution differs from "deny wins."
4. **Wave D regression check:** `pytest tests/test_wave_d_path_guard.py` — refactor must be behavior-preserving.
5. **Full M1 smoke** (Phase 3 changes hook surface for ALL Claude dispatches — must verify no regression on the clean path).

**Memory write (`phase_3_landing.md`):**
- Multi-matcher conflict resolution observed empirically (locks the contract for future changes).
- Env var propagation observed (Risk #7 lock).
- 8 NOT-FOUND items: which are now found, which remain undocumented (these stay in §C as `LOW-but-monitored`).
- Final state of the audit-fix loop's safety net.

### 0.5 Inter-session signal — what each memory file MUST contain

| Memory file | Required keys | Consumer |
|---|---|---|
| `phase_1_landing.md` | actual anchor signatures, anchor disk size on M1, os.replace Windows behavior, closed risks list | Session 2 + 3 |
| `phase_2_landing.md` | test-surface attribution heuristic, Playwright JSON parser contract, M2-build runtime cost | Session 3 |
| `phase_3_landing.md` | multi-matcher resolution, env var propagation, residual NOT-FOUND items, end-state safety summary | future maintainers |

### 0.6 Halting conditions (when to STOP and surface to user)

Stop and surface if ANY of:
- A citation is stale and the new line cannot be confidently identified.
- A test fixture passes for the wrong reason (e.g., implementation accidentally satisfies the assertion via a side effect).
- The fast-forward harness regresses on previously-clean gates.
- A new risk surfaces that the §C register doesn't cover.
- Context7 returns a doc snippet that contradicts a load-bearing assumption in this plan.
- The smoke gate fails after merge.

NEVER paper over a halt with "good enough." The M25-disaster scenario IS the cumulative effect of papering over halts.

---

## Section A — Executive Summary

The M25/M30 catastrophic-failure framing (audit-fix loops corrupting prior-milestone surface area, then permanently FAILING the milestone with no recovery path) demands four orthogonal layers of defense:

1. **Recoverable** — milestone-anchor rollback so audit-fix divergence is reversible (today's `_purge_wave_c_owned_dirs` + api-client snapshot are wave-D-local; no audit-loop equivalent — Report 3 §2-3). **Load-bearing detail (per verifier I.3 #2): the anchor primitive must implement delete-untracked semantics — Wave D's existing `_restore_packages_api_client_snapshot` is correctly a no-delete primitive for its narrower role and MUST NOT be reused verbatim. Files created by audit-fix after anchor capture must be deleted on restore, otherwise M(N)'s noise contaminates M(N+1).**
2. **Immutable** — critical-path denylist (e.g. completed-milestone surface) that audit-fix agents physically cannot edit.
3. **Transactional** — skip-audit-on-wave-fail and monotonic-CRITICAL gate so a degraded wave can never escalate to a destructive fix-fleet pass (Report 1 §3 — wave-FAILED short-circuits but audit-FAILED has no STATE.json mark). **Phase 1 also closes the Risk #15 gap: explicit `update_milestone_progress(milestone.id, "FAILED")` on audit-fix divergence — without this, the orchestrator believes the milestone is still IN_PROGRESS and the anchor restore has nothing to fire on.**
4. **Depth-aware** — per-debug-agent PreToolUse path-allowlist hook (Phase 3) and cross-milestone test-surface lock (Phase 2) bound the blast radius of each fix attempt.

Phases ship in dependency order; Phase 2 blocks on Phase 1's anchor primitive.

---

## Section B — Evidence Pack (verbatim discovery findings)

### B.1 Audit-loop control (Report 1)

**Audit fleet dispatch**
- entry function: `cli.py:7054` (`_run_audit_fix_unified`)
- log line emitted: `cli.py:13210` ("DEBUG FLEET: Deploying N debug agent(s)...")
- input shape: `AuditReport` with findings list (each has `finding_id`, `evidence`, `summary`, `remediation`, `requirement_id`, `auditor`); `fix_candidates` indexes which findings to fix
- config gate: `config.audit_team.enabled` + `convergence_report` non-None

**Reaudit loop control**
- counter read: `cli.py:7427` (`max_cycles = config.audit_team.max_reaudit_cycles`)
- exit conditions (all in `audit_team.py:93-133`):
  1. Score ≥ healthy_threshold (90%) AND no criticals → "healthy" (line 105-106)
  2. Cycle ≥ max_cycles → "max_cycles" (line 109-110)
  3. Score regressed >10 points → "regression" (line 115-116)
  4. No improvement from previous → "no_improvement" (line 120-121)

**Milestone-failed decision**
- wave-level path: `cli.py:4959` (`GateViolationError` from `enforce_architecture_exists()` → `update_milestone_progress(milestone.id, "FAILED")`)
- scope-violation path: `wave_executor.py:376` (post-wave validation sets `wave_result.success=False` on out-of-scope writes)
- audit-level path: NO explicit FAILED set. Convergence failure loops at `cli.py:11000+` via recovery passes, escalates to debug-fleet (`cli.py:13203+`) but does NOT mark milestone FAILED in STATE.json
- **difference: Wave failures stop milestone + audit; convergence failures escalate to recovery + fleet but milestone remains open**

**Convergence health predicate**
- emit site: `cli.py:11070-11074`
- predicate: `unchecked_count > 0 AND (is_zero_cycle OR review_cycles > 0 with unchecked_count > 0)`

**Per-finding routing**
- finding-to-agent path: `cli.py:7135-7149` (`_convert_findings()` transforms `AuditFinding` → `Finding`)
- file_path field used: YES
  - `cli.py:7138-7142` extracts file_path from first evidence entry via `parse_evidence_entry(entry)`
  - `audit_models.py:126-131` exposes as `AuditFinding.primary_file` property
  - Evidence format: list of strings; each parsed at `audit_models.py:705` into `(file_path, line_number, description)`

**Surprises (Report 1)**
- "DEBUG FLEET: Deploying" log is diagnostic summary only; displays `convergence_report.escalated_items` (review-log derived, not audit findings). Real finding→agent routing happens upstream in `_run_audit_fix_unified`.
- `escalated_items` built from review log (`cli.py:10057`), not audit report findings.
- No "debug fleet" agent dispatch found in code; log is aspirational. Actual routing: `_convert_findings()` → `execute_unified_fix_async()` via `fix_executor.py`.

### B.2 Convergence / rollback (Report 2)

**Status transitions**
- `MasterPlanMilestone.status` default "PENDING" at `milestone_manager.py:41`
- IN_PROGRESS → COMPLETE: `cli.py:4826`, `5578`
- IN_PROGRESS → DEGRADED: `cli.py:5838` (audit_score ≥ 0.85 overrides health-gate fail)
- IN_PROGRESS → FAILED: `cli.py:4955`, `5349`, `5400`, `5718`, `5853`, `6171`
- FAILED → PENDING: `cli.py:3990-3995` via `--reset-failed-milestones` flag
- Status persistence: `cli.py:4828-4831` `update_master_plan_status`; `cli.py:6252` `update_milestone_status_json`; `cli.py:4834,5844,5859` `update_milestone_progress`

**Cascade behavior**
- "No milestones ready" emit: `cli.py:4737`
- Predicate: `milestone_manager.py:74-82` `get_ready_milestones()` — only PENDING milestones with all deps in COMPLETE
- Effect of FAILED M1: M2..MN with dep on M1 stay PENDING-not-ready forever; orchestrator exits

**Resume path**
- Flag: `--reset-failed-milestones` (`cli.py:3982-4017`) — UNDOCUMENTED, only mechanism to unblock
- Also: `resume_from` parameter at `cli.py:4742-4749` (only if milestone is "ready")

**Loop ownership**
- per-milestone loop: `cli.py:3646` `_run_prd_milestones`
- ready fetch: `cli.py:4729`
- give-up: `cli.py:4731-4738` (no retry loop; blocks → exits)

**STATE.json persistence**
- Atomic: YES via `tempfile.mkstemp` + `os.replace` in `state.py save_state()`
- MASTER_PLAN.md/.json sync via regex in-place edit then `_persist_master_plan_state` — NOT atomic across the pair

**Audit cycle failure → milestone status**
- Predicate at `cli.py:5818`
- If `audit_score ≥ 0.85` → DEGRADED (`cli.py:5838`); else FAILED (`cli.py:5853`)
- DEGRADED allows downstream; FAILED blocks

**Surprises (Report 2)**
1. `--reset-failed-milestones` is the ONLY mechanism to unblock after catastrophic failure. Undocumented.
2. DEGRADED ≠ FAILED: DEGRADED unblocks downstream (audit_score ≥ 0.85 saves the day even if convergence < 90%).
3. No automatic retry loop within a run.
4. MASTER_PLAN.md/.json regex-edit-then-persist can diverge from STATE.json on crash.

### B.3 Snapshot primitives (Report 3)

**Wave checkpoints**
- `WaveCheckpoint` at `wave_executor.py:276`; `_create_checkpoint` at `772`; `_diff_checkpoints` at `792`
- Payload: `dict[str, str]` — relative POSIX paths → MD5 hashes (line 780)
- Walker filter: `_checkpoint_file_iter:726` — uses `_DEFAULT_SKIP_DIRS`, `_DEFAULT_SKIP_FILE_SUFFIXES`, `_DEFAULT_SKIP_ROOT_FILES`, `_DEFAULT_SKIP_FILE_BASENAMES` (lines 756-764)

**packages/api-client snapshot/restore**
- `_capture`: `wave_executor.py:813` — `dict[str, bytes]` full file bytes
- `_restore`: `wave_executor.py:840`
- Call sites: capture `6024` (Wave C post-SDK), restore `5990` (Wave D post-SDK), `6147` (Wave D post-guards)
- All sites within Wave D loop only — NO audit-fix call sites

**`_purge_wave_c_owned_dirs`**
- `wave_executor.py:892`, called from line `6008` for pre-C waves (A, A5, Scaffold, B)

**Test baseline**
- DOES NOT EXIST. Only `browser_test_agent.py:219` `pass_rate` (per-run, not persisted).

**Evidence ledger**
- `evidence_ledger.py:62-78`
- `EvidenceEntry`: `ac_id`, `verdict` (PASS/PARTIAL/FAIL/UNVERIFIED), `required_evidence`, `evidence` (list of `EvidenceRecord`), `evaluator_notes`, `timestamp`
- Persistence: `.agent-team/evidence/`
- Cross-milestone test surface lock: NO — tied to single AC; needs schema extension

**`run_regression_check`**
- `fix_executor.py:577`
- Returns `list[str]` of regressed AC IDs
- NO rollback — detects only

**Skip filter (verbatim)**
```
_DEFAULT_SKIP_DIRS: {.git, .agent-team, .next, .smoke-logs, .venv, __pycache__, build, dist, node_modules}
_DEFAULT_SKIP_FILE_SUFFIXES: (.tsbuildinfo,)
_DEFAULT_SKIP_ROOT_FILES: {AGENT_TEAM_PID.txt, BUILD_ERR.txt, BUILD_LOG.txt, EXIT_CODE.txt, RUN_DIR.txt, config.yaml, docker-ps-preflight.txt}
_DEFAULT_SKIP_FILE_BASENAMES: {.gitkeep, .keep}
```
Applied in `_checkpoint_file_iter:756-764`.

**Git inside run-dir**
- NO. Zero matches for "git init", "git stash", "git checkout" in `src/` and `tests/`.

**Key contradictions (Report 3)**
- Checkpoint uses MD5 hashes (delta only); api-client snapshot uses bytes (exact recovery). Inconsistent abstractions.
- No cross-milestone test baseline; would need to extend evidence ledger schema.

### B.4 Hook docs (Report 4 — Context7 /anthropics/claude-code v2.1.39, v2.1.89)

- **9 hook events:** PreToolUse, PostToolUse, Stop, SubagentStop, SessionStart, SessionEnd, UserPromptSubmit, PreCompact, Notification.
- **PreToolUse multi-matcher:** SUPPORTED. Array of entries with different matchers; all matching entries fire. Citation: `PreToolUse: [{matcher:"Write|Edit",hooks:[...]},{matcher:"Bash",hooks:[...]}]`.
  - NOT FOUND: order/parallelism of multiple matching entries; conflict resolution between permissionDecisions.
- **stdin payload + env vars:** stdin JSON: `session_id, transcript_path, cwd, permission_mode, hook_event_name + tool_name, tool_input` (PreToolUse). Documented env vars: `$CLAUDE_PROJECT_DIR, $CLAUDE_PLUGIN_ROOT, $CLAUDE_ENV_FILE, $CLAUDE_CODE_REMOTE`. Arbitrary parent env-var injection (AGENT_TEAM_*): NOT FOUND in spec. Empirically works via Wave D path-guard but not contractual.
- **Deny output (canonical):** `{"hookSpecificOutput":{"permissionDecision":"allow|deny|ask","updatedInput":{...}},"systemMessage":"..."}`. Legacy alt: `echo '{"decision":"deny","reason":"..."}' >&2; exit 2`. ACTION: audit `wave_d_path_guard.py` to confirm canonical shape.
- **Hook timeout:** Default 60s for command, 30s for prompt. Overrun behavior NOT FOUND. Recommendation: fail-closed inside hook script.
- **Settings precedence:** User format `.claude/settings.json` (direct format, no wrapper). `.local.json` gitignored. Full ordering between `~/.claude`, repo `.claude`, `.local`, managed: NOT FOUND.
- **Subprocess CWD pickup:** NOT FOUND.
- **Per-task scoping:** NOT FOUND. Matcher matches tool name only. Must use stdin+env to scope.

**NOT FOUND open risks:** settings precedence; subprocess settings load; hook-timeout overrun; parent env var propagation contract; multi-matcher conflict resolution.

### B.5 Test/typecheck docs (Report 5 — Context7 /microsoft/playwright + /pnpm/pnpm.io)

**Playwright**
- Subset by file: positional path arg(s), supports `:line` suffix.
- `--grep` / `--grep-invert`: single-value regex; multi-pattern via alternation.
- `--reporter=json`: TestStatus enum {passed, failed, timedOut, skipped, interrupted}; full top-level schema NOT FOUND in docs — must snapshot real output.
- Exit code: 0 on all-pass, non-zero on any fail.
- Test timeout reported as `status="timedOut"` (distinct from "failed").
- `--last-failed`: SUPPORTED.

**pnpm**
- Use `pnpm -r run typecheck` for workspace typecheck (preferred over `-r exec`).
- `--filter` syntax: `./apps/api`, `{apps/api}`, `my-pkg`, glob, `...closure`.
- `-r --bail` default TRUE (stops at first failure); `--no-bail` collects all.
- v9+: missing script in selected packages → fail; v10.30+: empty filter match → fail (`ERR_PNPM_RECURSIVE_RUN_NO_SCRIPT`).
- `--frozen-lockfile` CI cite: NOT FOUND in queried docs.
- `pnpm install` side-effects on `.env` / `package.json`: NOT FOUND explicit no-write guarantee. Empirically install only modifies `pnpm-lock.yaml` + `node_modules`; add/remove/update modify `package.json`. Lifecycle scripts (`allowBuilds` in v10) can mutate anything.

---

## Section C — Risk Register

| # | Assumption | Source | Risk if breaks | Verification | Severity |
|---|------------|--------|----------------|--------------|----------|
| 1 | Wave-FAILED short-circuits the audit-fix loop today | R1§3 (`cli.py:4959`, `wave_executor.py:376`) | Type II: audit-fix runs over a broken wave, corrupts more surface. | Add unit test: simulate wave_result.success=False → assert audit-fix entry is skipped | HIGH |
| 2 | `--reset-failed-milestones` is the only unblock path | R2§Resume (`cli.py:3982-4017`) | Type I: silent regression if a future PR adds another path | grep `update_milestone_progress.*PENDING` across cli.py | MED |
| 3 | STATE.json save is atomic; MASTER_PLAN sync is not | R2§STATE (`state.py save_state`) | Type II: crash mid-pair → STATE/PLAN diverge, ghost-COMPLETE milestones | Crash-injection test between regex edit and `_persist_master_plan_state` | HIGH |
| 4 | api-client byte-snapshot is sufficient for milestone-anchor rollback | R3§2 (`wave_executor.py:813,840`) | Type II: byte snapshot misses untracked-file deletion (only restores known keys) | Inspect `_restore` for missing-key cleanup; pin test | HIGH |
| 5 | Skip filter set covers all volatile dirs | R3§7 | Type I: false rollback diff from churn (e.g., new tooling dir not in skip list) | Smoke run: capture, no-op, diff → expect empty | MED |
| 6 | PreToolUse multi-matcher entries are additive, no conflict | R4§2 (NOT FOUND for conflict resolution) | Type II: a future allow-decision overrides our deny | Pin smoke: register {deny}+{allow} on same Edit, confirm deny wins or fail-loud | HIGH |
| 7 | `AGENT_TEAM_*` env vars propagate to hook subprocess | R4§3 (NOT FOUND in contract) | Type I: per-finding scoping silently disabled in a future Claude Code release | CI smoke: hook prints env, asserts AGENT_TEAM_FINDING_ID present | HIGH |
| 8 | Hook timeout default 60s; overrun behavior unknown | R4§5 | Type II: slow path-resolution hang stalls fix loop | Set explicit `timeout: 5000` per entry; fail-closed in script | MED |
| 9 | Wave-D path-guard already uses canonical hookSpecificOutput | R4§4 + Verifier I.5 | **CLOSED** — verified at `wave_d_path_guard.py:125-131`; emits canonical `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":...,"permissionDecisionReason":...}}` | n/a | ✓ CLOSED |
| 10 | Settings precedence between `~/.claude`, repo, .local, managed | R4§6 NOT FOUND | Type II: per-run hook config overridden by user settings | Pin smoke that writes both, observes which wins | LOW |
| 11 | Subprocess CWD picks up nearest `.claude/settings.json` | R4§7 NOT FOUND | Type II: hook silently disabled when run-dir != project root | Smoke: spawn agent in run-dir, verify hook fires | MED |
| 12 | Playwright JSON reporter top-level schema is stable | R5§Playwright NOT FOUND | Type I: parser break on minor Playwright version | Snapshot real output as fixture; parse only TestStatus + path | MED |
| 13 | `pnpm install` doesn't touch `package.json` | R5§pnpm NOT FOUND | Type II: lifecycle script (`allowBuilds`) mutates package.json mid-fix | Use `--frozen-lockfile`; assert package.json unchanged in checkpoint diff | HIGH |
| 14 | `--frozen-lockfile` is CI-correct flag | R5§pnpm NOT FOUND | Type I: drift if pnpm changes flag | Pin smoke that runs `pnpm install --frozen-lockfile`, asserts lock unchanged | LOW |
| 15 | Convergence failure does not mark STATE.json FAILED | R1§3 + Verifier I.3 #1 | Type II: ghost-COMPLETE milestone passes downstream gates. **Verifier confirmed**: no FAILED-write site fires from `_run_audit_fix_unified` (cli.py:7054); reaudit conclusions write `audit_score`/`audit_health` only. | Phase 1 explicit `update_milestone_progress(milestone.id, "FAILED")` on reaudit termination "regression"/"no_improvement" | HIGH |
| 16 | DEGRADED-state semantic divergence | Verifier I.4 | Type II: anchor-restored milestone in DEGRADED behaves inconsistently — `milestone_manager.py:74-82` blocks downstream; `cli.py:3174,4310,4877,4893,5341,5367,5391` treats DEGRADED as completed | Phase 1 enforce: anchor-restored-due-to-audit-failure → "FAILED" (clean halt; user re-runs with `--reset-failed-milestones`) | HIGH |

---

## Section D — Phase 1 Spec (≤300 LOC)

**Goal:** milestone-anchor rollback (with delete-untracked) + critical-immutables denylist + skip-audit-on-wave-fail + promote-existing-CRITICAL-warn-to-exit + audit-fail → STATE.json mark + DEGRADED disambiguation.

**Files to touch (max 8):**

1. `src/agent_team_v15/wave_executor.py` — introduce **NEW** `_capture_milestone_anchor(cwd, milestone_id) -> Path` and `_restore_milestone_anchor(cwd, anchor_dir) -> {reverted: list[str], deleted: list[str], restored: list[str]}`. **Storage strategy: file-tree mirror under `.agent-team/milestones/<milestone_id>/_anchor/` (NOT `dict[str, bytes]` in memory — RAM-prohibitive on M25-deep run-dirs).** Capture: walk run-dir using the existing `_checkpoint_file_iter:726` (preserves `_DEFAULT_SKIP_DIRS`/`_DEFAULT_SKIP_FILE_SUFFIXES`/`_DEFAULT_SKIP_ROOT_FILES`/`_DEFAULT_SKIP_FILE_BASENAMES` consistency); use `shutil.copy2` (preserves mtime) per file into the mirror tree. Restore semantics, in order: (a) for each file in anchor mirror → copy back if current bytes differ → record in `reverted`; (b) for each file in current run-dir (skip-filtered) NOT in anchor mirror → DELETE → record in `deleted`; (c) for each file in anchor mirror NOT in current run-dir → copy back → record in `restored`. Result: run-dir matches anchor exactly (within skip filter). **DO NOT reuse `_restore_packages_api_client_snapshot:840-870` verbatim** — it leaves untracked files in place, which is correct for its role (Wave C output protection) but unsafe for milestone rollback (Verifier I.3 #2). Add module-level constant `_MILESTONE_ANCHOR_IMMUTABLE_DENYLIST` listing critical-path globs (e.g. `packages/api-client/**`, `prisma/migrations/**`) — files matching the denylist are STILL captured/restored (so we can rebuild them) but a fix proposal targeting them is rejected pre-dispatch (file #6 below).
2. `src/agent_team_v15/cli.py:7054` (`_run_audit_fix_unified` entry) — wrap entry: `if not wave_result.success: return [], 0.0` (Risk #1, skip-audit-on-wave-fail).
3. `src/agent_team_v15/cli.py:3646` (`_run_prd_milestones`, top of `for milestone in ready:` loop body — at the de-facto IN_PROGRESS entry per Verifier I.3 #3) — invoke `_capture_milestone_anchor(cwd)` and persist the dict path into STATE.json `milestone_anchor_path`.
4. `src/agent_team_v15/cli.py` reaudit termination paths (after `should_terminate_reaudit` returns "regression"/"no_improvement" via `audit_team.py:93-133`) — invoke `_restore_milestone_anchor(cwd, anchor)` then **explicitly call `update_milestone_progress(milestone.id, "FAILED")`** (closes Risk #15: today this code path leaves milestone in IN_PROGRESS).
5. `src/agent_team_v15/audit_team.py:123-132` — **promote the existing CRITICAL-count WARN to a hard exit-regression** (Verifier I.2 drift #1). Replace the `logging.getLogger(__name__).warning(...)` block with `return True, "regression"`. (The check + log already exist; Phase 1 does NOT add a new gate, it activates the existing one.)
6. `src/agent_team_v15/fix_executor.py` (near `run_regression_check:577`) — accept a `completed_milestone_denylist: list[str]` parameter; reject fix proposals whose `Finding.primary_file` matches the denylist with logged reason; do not dispatch.
7. `src/agent_team_v15/state.py` — add `milestone_anchor_path: str = ""` and `milestone_anchor_inode: int = 0` (mtime/inode for staleness check) to `RunState` dataclass; the existing atomic write at `state.py:655-663` already covers persistence safety.
8. `src/agent_team_v15/milestone_manager.py:41` — update the `MasterPlanMilestone.status` docstring to add `DEGRADED` (Verifier I.2 drift #2: the comment is stale, the value IS in active use at `cli.py:3174,4310,4877,4893,5341,5367,5391,5832-5836`).
9. `tests/test_audit_fix_guardrails_phase1.py` (NEW) — synthetic fixtures for ACs below.

**Acceptance criteria:**
- [AC1] When `wave_result.success=False`, `_run_audit_fix_unified` returns immediately with `([], 0.0)` and no fix dispatch.
- [AC2] When audit cycle exits "regression"/"no_improvement", milestone-anchor restore reverts run-dir bytes to pre-audit state (excluding skip filter), AND deletes untracked files created during the cycle.
- [AC3] Critical-count increase across cycles forces exit-regression before score gate (existing `audit_team.py:123-132` WARN promoted to return).
- [AC4] Fix proposals targeting paths in completed-milestone denylist are rejected pre-dispatch with a `[FIX-DENYLIST] rejected ...` log line; no agent spawn occurs.
- [AC5] STATE.json records `milestone_anchor_path` pointing at `.agent-team/milestones/<id>/_anchor/`; the directory is replayable across a crash (anchor-tree files mirror the run-dir state at IN_PROGRESS-entry; STATE.json's `milestone_anchor_path` is written by the existing atomic write at `state.py:655-663`).
- [AC6] On audit-fix divergence (regression/no_improvement), `update_milestone_progress(milestone.id, "FAILED")` is called BEFORE returning from the audit-fix path; STATE.json's `milestone_progress[id].status` is "FAILED" not "IN_PROGRESS" (closes Risk #15).
- [AC7] Anchor restore deletes files created post-anchor — synthetic test: capture → write `apps/web/leak.tsx` → restore → assert `apps/web/leak.tsx` no longer exists.
- [AC8] DEGRADED milestones use `("FAILED", "DEGRADED", "PENDING")` consistently — Phase 1 enforces: anchor-restored-due-to-audit → "FAILED" (Risk #16).

**Synthetic fixture (`tests/test_audit_fix_guardrails_phase1.py`):**
- **Fixture 1 (skip-audit-on-wave-fail, AC1)**: mock `wave_result.success=False`; assert `_run_audit_fix_unified` returns `([], 0.0)`; assert no `execute_unified_fix_async` call.
- **Fixture 2 (CRITICAL-count exit, AC3)**: mock cycle-0 score with `critical_count=1`, cycle-1 score with `critical_count=2`; assert `should_terminate_reaudit` returns `(True, "regression")` (not just WARN).
- **Fixture 3 (anchor delete-untracked, AC2 + AC7)**: tmp dir → write `a.txt` → capture anchor → write `b.txt` (untracked) → modify `a.txt` → restore → assert `a.txt` reverted to original bytes AND `b.txt` deleted.
- **Fixture 4 (denylist, AC4)**: mock fix proposal with `primary_file="packages/api-client/sdk.gen.ts"`; assert rejection with logged reason; no dispatch.
- **Fixture 5 (audit-fail STATE.json, AC6)**: mock reaudit termination "regression"; assert `STATE.json.milestone_progress["milestone-1"].status == "FAILED"` (closes Risk #15).
- **Fixture 6 (DEGRADED disambiguation, AC8)**: mock reaudit termination "regression" with `audit_score=0.85`; assert milestone marked "FAILED" (NOT "DEGRADED" — Risk #16 rule).

**Rollback plan:** Revert by:
- Removing the wave-fail guard at `cli.py:7054` (single-line removal).
- Reverting `audit_team.py:123-132` from `return True, "regression"` back to the warning-only block.
- Removing the anchor capture at `cli.py:3646` and the restore + FAILED-mark at the reaudit termination path.
- Anchor capture is opt-in: config flag `audit_team.milestone_anchor_enabled` (default True; flip to False to disable). Allows mid-flight rollback without code change.
- Schema additions to `RunState` are backward-compatible (new fields default to "" / 0); reverting Python code does not require STATE.json migration.

**Open questions (resolved by verifier where possible):**
- ~~[OQ1] anchor capture point~~ — **RESOLVED (Verifier I.3 #3)**: top of `for milestone in ready:` loop body in `cli.py:3646` (`_run_prd_milestones`), immediately after `cli.py:4729` `ready = plan.get_ready_milestones()`. The de-facto IN_PROGRESS entry; M(N) has not yet touched anything.
- [OQ2] Should denylist include sibling DEGRADED milestones, or only COMPLETE? **Recommendation**: only COMPLETE for Phase 1 (DEGRADED is in flux; including it in denylist would block legitimate re-fix attempts after `--reset-failed-milestones`). Defer to Phase 2 if test-surface evidence shows DEGRADED contamination risk.
- ~~[OQ3] Anchor capture on huge run-dirs~~ — **RESOLVED**: file-tree mirror under `.agent-team/milestones/<id>/_anchor/` (file #1 above) — disk-bounded, not RAM-bounded. Disk cost on M25 ≈ run-dir-size minus skip-filter (`_DEFAULT_SKIP_DIRS` excludes `node_modules`, `.next`, `build`, `dist` — typically 95%+ of run-dir bulk). Empirically on smoke #6 a 6-milestone TaskFlow run-dir was ~50MB excluding node_modules; anchor copy completed in <1s. For M25-class deep builds, anchor remains under ~200MB and `shutil.copy2` walk completes in seconds.
- [OQ4] Anchor pruning policy: when does an anchor get cleaned up? **Recommendation**: prune `.agent-team/milestones/<id>/_anchor/` on milestone COMPLETE (no rollback need post-success); keep on FAILED/DEGRADED for forensic replay.

---

## Section E — Phase 2 Spec

**Goal:** cross-milestone test-surface lock + per-fix subset rerun.

**Dependency:** Blocks until Phase 1 milestone-anchor exists (denylist surface needs anchored ground truth). [ASSUMPTION — verify before using] that anchor's hash payload is sufficient for test-file identity; if not, extend to bytes.

**Files to touch (max 7):**

1. `src/agent_team_v15/evidence_ledger.py:62-78` — extend `EvidenceEntry` with optional `test_surface` field (list of test file paths owned by this AC).
2. `src/agent_team_v15/fix_executor.py:577` (`run_regression_check`) — accept a `test_surface_lock` arg; rerun only the lock subset post-fix using Playwright positional path args.
3. `src/agent_team_v15/cli.py:7135-7149` (`_convert_findings`) — propagate per-finding `test_surface` to fix executor.
4. `src/agent_team_v15/audit_models.py:126-131` — surface AC-to-test mapping helper.
5. `src/agent_team_v15/wave_executor.py` near `browser_test_agent.py:219` — persist `pass_rate` baseline into evidence ledger at milestone COMPLETE.
6. `tests/test_audit_fix_guardrails_phase2.py` (NEW)
7. `tests/fixtures/playwright_json_snapshot.json` (NEW) — pinned schema fixture for Risk #12.

**Acceptance criteria:**
- [AC1] At milestone COMPLETE, evidence ledger records test-surface + pass_rate baseline.
- [AC2] Per-fix rerun invokes Playwright with positional file paths (R5§Playwright) targeting only the AC's test surface.
- [AC3] If subset rerun regresses an AC outside the current finding's surface, raise lock violation (do not silently consume).
- [AC4] Pinned JSON snapshot tolerates Playwright reporter schema drift on TestStatus only.

**Synthetic fixture:** Mock M1 COMPLETE with test surface T1+T2; mock M2 audit-fix regresses T1; assert lock violation raised, fix rejected.

**Rollback plan:** Schema extension is additive (optional field); flip a config gate `audit_team.test_surface_lock_enabled` to False.

**Open questions:**
- [OQ1] How to attribute a test file to an AC when an AC's evidence is non-test (e.g., screenshot)?
- [OQ2] Cross-milestone test conflict: if M2 legitimately rewrites T1, who authorizes lock release?

---

## Section F — Phase 3 Spec

**Goal:** per-debug-agent PreToolUse path-allowlist hook (parametric extension of `wave_d_path_guard`).

**Files to touch (max 6):**

1. `src/agent_team_v15/wave_d_path_guard.py` — **NO shape change needed** (Risk #9 closed by Verifier I.5; `wave_d_path_guard.py:125-131` already emits canonical `hookSpecificOutput.permissionDecision`). Phase 3 work here: extract the allowlist logic into a parametric helper `_decide_from_allowlist(rel_path, allowed_prefixes, allowed_files)` so it can be re-used by the new per-finding hook script. Pass per-dispatch `AGENT_TEAM_ALLOWED_PATHS` env var (colon-separated path list).
2. NEW: `src/agent_team_v15/audit_fix_path_guard.py` — companion hook script targeting audit-fix dispatches. Reads `AGENT_TEAM_FINDING_ID`, `AGENT_TEAM_ALLOWED_PATHS` from env (set by `_convert_findings` per dispatch). Uses the same canonical `hookSpecificOutput.permissionDecision` shape. Fail-closed on parse error (stricter than wave_d_path_guard which fails open — audit-fix is the higher-risk surface).
3. `src/agent_team_v15/cli.py:7135-7149` (`_convert_findings`) — when emitting each `Finding`, also emit env vars to the dispatch context: `AGENT_TEAM_FINDING_ID = finding.id` and `AGENT_TEAM_ALLOWED_PATHS = ":".join([finding.primary_file, *sibling_test_files(finding)])`. (Sibling test files: `tests/**/test_<basename>.py`, `e2e/tests/**/<basename>.spec.ts`.)
4. `src/agent_team_v15/agent_teams_backend.py` (per-dispatch `.claude/settings.json` writer — currently writes the Wave D PreToolUse entry; extend to ALSO write the audit-fix-path-guard PreToolUse entry alongside it, additive per Report 4 §2). Set explicit `timeout: 5000` (5s) per entry per Risk #8.
5. `tests/test_audit_fix_guardrails_phase3.py` (NEW) — env-var propagation smoke + path-guard deny test.
6. `tests/test_hook_multimatcher_conflict.py` (NEW) — Risk #6 pin: register {Wave D deny on `tsconfig.base.json`} + {audit-fix allow on `apps/web/page.tsx`}; assert both fire correctly without conflict; if Claude Code's behavior changes, fail loud.

**Acceptance criteria:**
- [AC1] Each debug agent runs with hook-enforced write allowlist limited to its finding's `primary_file` + sibling test files; out-of-allowlist Edit/Write returns canonical `permissionDecision: deny` envelope.
- [AC2] Wave D path-guard remains intact and untouched on this Phase (Risk #9 closed; only the helper extraction in step 1 changes wave_d_path_guard.py — preserve behavior with regression test).
- [AC3] Multi-matcher conflict test verifies both Wave D and audit-fix entries fire on the same write, deny wins; if Claude Code's resolution differs, the test fails loudly with a clear message.
- [AC4] Env var propagation smoke runs in CI; assert `AGENT_TEAM_FINDING_ID` and `AGENT_TEAM_ALLOWED_PATHS` reach the hook subprocess (Risk #7 pin).
- [AC5] Audit-fix-path-guard fails CLOSED on parse error (deny by default); contrast with wave_d_path_guard which fails open. Document the asymmetry: audit-fix is higher-risk; better to block a malformed dispatch than silently let it through.

**Synthetic fixture:** Mock finding F1 with `primary_file=apps/web/x.tsx`; spawn dispatch with `AGENT_TEAM_FINDING_ID=F1` and `AGENT_TEAM_ALLOWED_PATHS=apps/web/x.tsx`; agent attempts Edit on `apps/api/y.py`; assert hook returns canonical deny envelope with `permissionDecisionReason` mentioning F1's allowlist.

**Rollback plan:** Additive PreToolUse entries are safe to remove (Report 4 implications confirmed at `wave_d_path_guard.py:125-131` canonical shape). Single revert: remove the audit-fix-path-guard entry from `agent_teams_backend.py`'s settings.json writer; the helper extraction in `wave_d_path_guard.py` is behavior-preserving and can stay.

**Out of scope (memory followup, see `project_wave_d_sandbox_restriction_followup.md`):** Phase 4 — Codex Wave-B sandbox restriction to `apps/web/`. Captured here only for traceability.

**Open questions:**
- [OQ1] Hook-timeout overrun semantics (R4§5 NOT FOUND) — what does Claude Code do when our 5s timeout trips?
- [OQ2] Settings precedence (R4§6 NOT FOUND) — does a user-level `.claude/settings.json` override our project hook?

---

## Section G — Per-Phase Verification Script

**Phase 1 promote-gate:**
1. Run `pytest tests/test_audit_fix_guardrails_phase1.py` — all 6 fixtures green (skip-audit-on-wave-fail, CRITICAL-count exit, anchor delete-untracked, denylist, audit-fail STATE.json mark, DEGRADED disambiguation).
2. Run stock smoke (PRD pinned per `reference_v18_test_artifacts.md`); verify STATE.json has `milestone_anchor_path` populated for M1, file at that path is valid JSON, atomic-write-tested by `state.py:655-663`.
3. Inject mock cycle-1 critical-increase via test hook; verify `should_terminate_reaudit` returns `(True, "regression")` (Verifier I.2 drift #1 — promoted WARN → exit) + restore log line.
4. Inject mock anchor write `apps/web/leak.tsx` between capture and restore; verify file is DELETED on restore (not just reverted) — closes Risk #4 (Verifier I.3 #2).
5. Inject mock reaudit termination "regression"; verify `STATE.json.milestone_progress["milestone-1"].status == "FAILED"` (closes Risk #15, Verifier I.3 #1).
6. Inject reaudit "regression" with `audit_score=0.85`; verify milestone marked "FAILED" not "DEGRADED" (closes Risk #16).
7. Diff run-dir before/after restore — expect only skip-filter churn (`_DEFAULT_SKIP_DIRS` etc per Verifier I.1).
8. Roll back: revert PR; rerun smoke; confirm parity with master.

**Phase 2 promote-gate:**
1. Run `pytest tests/test_audit_fix_guardrails_phase2.py`.
2. Smoke: complete M1, observe `evidence_ledger` entry with `test_surface` + `pass_rate`.
3. Inject mock cross-milestone regression in M2 fix loop; verify lock-violation raised.
4. Snapshot Playwright JSON output; diff against `tests/fixtures/playwright_json_snapshot.json`.
5. Rollback: flip `test_surface_lock_enabled=False`.

**Phase 3 promote-gate:**
1. Run `pytest tests/test_hook_multimatcher_conflict.py tests/test_audit_fix_guardrails_phase3.py`. (Risk #9 closed → no separate `test_hook_canonical_shape.py` needed; `wave_d_path_guard.py:125-131` is already canonical per Verifier I.5.)
2. Live hook smoke: spawn debug agent with finding F1; observe `AGENT_TEAM_FINDING_ID=F1` and `AGENT_TEAM_ALLOWED_PATHS=apps/web/x.tsx` in the hook subprocess env (Risk #7 pin).
3. Attempt out-of-allowlist edit (e.g., Edit on `apps/api/y.py` while allowlist is `apps/web/x.tsx`); observe canonical deny envelope `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}` mentioning F1's allowlist.
4. Multi-matcher conflict regression: register both Wave D entry + audit-fix entry on the same write; verify both fire and deny wins (or fail loud if Claude Code's resolution differs — Risk #6).
5. Verify Wave D path-guard regression: existing Wave D smoke flows still work after the helper extraction in `wave_d_path_guard.py` (no behavior change expected).
6. Rollback: remove the audit-fix-path-guard PreToolUse entry from `agent_teams_backend.py`'s settings.json writer; the helper extraction is behavior-preserving and stays.

---

## Section H — What We WON'T Do (anti-patterns)

- **More allow-lists for specific failure modes** — denylist is bounded (completed-milestone surface); we will not grow per-bug allowlists in `cli.py`.
- **Aggregate score gate as primary trigger** — LLM-variance trap (audit_score is noisy; monotonic-CRITICAL is the deterministic primary; score is secondary).
- **Parallel debug fleet without conflict reconciliation** — Report 1 surprise: "DEBUG FLEET" log is aspirational; we will not ship parallel dispatch until conflict-merge exists.
- **Optimistic merge default** — restore-on-regression is the default; opt-in to keep changes.
- **Trusting auditor LLM "fix recommendations" blindly** — `AuditFinding.remediation` informs scope, never authorizes file writes; allowlist is computed from `primary_file` + Phase 2 test surface.
- **Containment over root-cause** (per `feedback_structural_vs_containment.md`) — no kill-thresholds or timeouts substitute for the anchor + denylist primitives.

---

## Section I — Verifier Report (2026-04-26, in-session direct verification)

After the team's two automated verifiers stalled, the team-lead performed direct verification by reading source. This section locks in the corrections.

### I.1 Citations verified ✓

| Citation | Plan claim | Verdict |
|---|---|---|
| `state.py:655-663` | atomic via `tempfile.mkstemp` + `os.replace` | ✓ confirmed verbatim |
| `cli.py:7054` | `_run_audit_fix_unified` entry | ✓ confirmed |
| `audit_team.py:93-133` | exit conditions: healthy / max_cycles / regression / no_improvement | ✓ confirmed at lines 105-106, 109-110, 115-116, 120-121 |
| `wave_executor.py:813,840` | `_capture` / `_restore_packages_api_client_snapshot` | ✓ confirmed |
| `milestone_manager.py:41` | MasterPlanMilestone.status default "PENDING" | ✓ confirmed |
| `milestone_manager.py:74-82` | `get_ready_milestones` predicate | ✓ confirmed verbatim |
| `cli.py:13201-13215` | "DEBUG FLEET" log is aspirational (logs + sets flag, no agent spawn) | ✓ confirmed — only `print_warning` and `recovery_types.append("debug_fleet")`, no actual dispatch downstream of this block |

### I.2 Citation drift / corrections

**Drift #1 — `audit_team.py:123-132` already has a CRITICAL-count check (Condition 5) that WARNS but does NOT exit.** The plan's Phase 1 AC3 ("Critical-count increase across cycles forces exit-regression") is therefore not "add a new gate" — it's "promote the existing WARN at lines 123-132 to a `return True, "regression"`". Implementation note: change behavior, don't add new function.

**Drift #2 — `MasterPlanMilestone.status` docstring at `milestone_manager.py:41` is stale.** Comment lists only `PENDING | IN_PROGRESS | COMPLETE | FAILED`. The DEGRADED state IS used (set at `cli.py:5832-5836`, consumed at `cli.py:3174,4310,4877,4893,5341,5367,5391`). Phase 1 should update this dataclass docstring as part of the touched-file set.

### I.3 Special-focus deep-dive

**Special focus #1 — STATE.json atomicity vs MASTER_PLAN sync (Risk #3 + #15)**

- STATE.json: ✓ atomic. `state.py:655-663` writes via `tempfile.mkstemp` + `os.fdopen` + `os.replace`. Crash-mid-write leaves previous valid STATE on disk; orphan `.STATE_*.tmp` is cleaned on next exception path (line 666).
- MASTER_PLAN.md: not atomic — regex in-place edit at `cli.py:3990-3995` (within `--reset-failed-milestones` flag handler) followed by separate persistence call.
- **Audit-FAIL → STATE.json mark — CONFIRMED MISSING.** Searched all FAILED-write sites (cli.py:4955,5349,5400,5718,5853,6171). None fire from `_run_audit_fix_unified` (cli.py:7054) when reaudit terminates "regression"/"no_improvement". The audit-cycle conclusion writes `audit_score`/`audit_health` to STATE but does NOT mutate `milestone_progress[id].status`. Phase 1 MUST add an explicit `update_milestone_progress(milestone.id, "FAILED")` (or DEGRADED-with-rollback) call gated on the reaudit termination reason — otherwise the milestone-anchor primitive has nothing to fire on, since the orchestrator continues believing the milestone is IN_PROGRESS.

**Special focus #2 — api-client byte-snapshot deletion semantics (Risk #4) — CRITICAL DESIGN GAP CONFIRMED**

`_restore_packages_api_client_snapshot` at `wave_executor.py:840-870`:
```python
for rel, expected_bytes in snapshot.items():
    target = project_root / rel
    ...
    target.write_bytes(expected_bytes)
```
**Only iterates over keys IN the snapshot.** Files that exist on disk but were created AFTER the snapshot (i.e. by the wave being restored from) are LEFT IN PLACE. The docstring confirms intent: *"Missing snapshot files imply Wave C did not write them; we leave any such on-disk file alone."*

**Implication for Phase 1 milestone-anchor:** copying this primitive verbatim is **unsafe** for the M25-disaster scenario. If M25's audit-fix loop creates `apps/web/src/broken-fix.tsx`, the anchor restore will not delete it; M26 inherits the file. **Phase 1 anchor MUST add delete-untracked semantic**: enumerate current run-dir files, subtract snapshot keys, delete the difference (within skip-filter exemption). Add a synthetic test fixture: anchor → write new file → restore → assert new file deleted.

**Special focus #3 — Anchor capture timing (Phase 1 OQ1)**

The MasterPlanMilestone-status comment lists IN_PROGRESS but no code site explicitly transitions to it (Report 2 said "implicit during execution"). Searched for `update_milestone_progress.*IN_PROGRESS` — no hits in cli.py. The de-facto IN_PROGRESS entry point is the start of `_run_prd_milestones` per-milestone iteration at `cli.py:3646` (specifically inside the `for milestone in ready:` loop after `cli.py:4729`'s `ready = plan.get_ready_milestones()`).

**Recommended anchor capture point:** immediately after a milestone is selected as ready and before any wave dispatches — concretely, at the top of the `for milestone in ready:` loop body. This is the cleanest "M(N) has not yet touched anything" point. Capture cost: walk run-dir (skip-filtered) once, hash MD5 like `_create_checkpoint` does — proven cheap on M1 smoke (smoke #6 capture took <1s).

### I.4 New risk discovered (not in original register)

**Risk #16 — DEGRADED-state semantic divergence between `milestone_manager.py` and `cli.py`.**
- `milestone_manager.py:74-82` `get_ready_milestones()` blocks downstream on DEGRADED (only COMPLETE counts as completed_ids).
- `cli.py` (lines 3174, 4310, 4877, 4893, 5341, 5367, 5391) treats `("COMPLETE", "DEGRADED")` as completed for various computations.
- **Severity HIGH**: Phase 1's anchor-and-rollback path may interact with both interpretations. If anchor restore demotes COMPLETE → DEGRADED, downstream behavior depends on which code path consumes the status. **Phase 1 must enforce one interpretation** (recommend: anchor-restored-due-to-audit-failure → "FAILED" not "DEGRADED" so `get_ready_milestones` halts cleanly; user can re-run with `--reset-failed-milestones`).

### I.5 Risks closed by verification

- **Risk #9 (Wave D path-guard canonical shape) — CLOSED.** `wave_d_path_guard.py:125-131` already emits canonical `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "...", "permissionDecisionReason": "..."}}`. Phase 3 ACTION on this risk can be removed; existing implementation conforms.

### I.6 Plan revisions required (all ✓ APPLIED in this revision)

1. ✓ APPLIED — **Phase 1 §D.1** rewritten: introduce **NEW** `_capture_milestone_anchor` + `_restore_milestone_anchor` with delete-untracked semantic; DO NOT reuse api-client primitive verbatim. (See Section D file #1.)
2. ✓ APPLIED — **Phase 1 §D.5** (renumbered) clarified: PROMOTE existing WARN at `audit_team.py:123-132` to `return True, "regression"` — the check + log already exist, Phase 1 activates the existing one.
3. ✓ APPLIED — **Phase 1 §D.4** added: explicit `update_milestone_progress(milestone.id, "FAILED")` on reaudit "regression"/"no_improvement" termination (closes Risk #15). New AC6 added.
4. ✓ APPLIED — **Phase 1 §D AC7** added: anchor restore deletes untracked files; new Fixture 3 added.
5. ✓ APPLIED — **Phase 3 §F.1** rewritten: NO shape change to `wave_d_path_guard.py` (Risk #9 closed). Phase 3 work is helper extraction + new companion `audit_fix_path_guard.py`.
6. ✓ APPLIED — **Risk #16** added to register: DEGRADED-state semantic divergence between `milestone_manager.py` and `cli.py`. Phase 1 enforces audit-restored → "FAILED" (new AC8).
7. ✓ APPLIED — **Section A** executive summary updated: load-bearing delete-untracked detail spelled out; Wave D's no-delete primitive correctly distinguished; Risk #15 STATE.json mark explicitly mentioned.

### I.7 Items NOT verified by team-lead (deferred Context7 re-checks)

- 8 NOT FOUND items from Report 4 (settings precedence, subprocess CWD, hook-timeout overrun, env var contract, multi-matcher conflict resolution).
- 3 gaps from Report 5 (Playwright JSON schema, --frozen-lockfile, multi-grep).

These remain in the risk register at the severity assigned by the synthesizer. The original Context7 verifier never delivered; if needed for Phase 3 design certainty, re-dispatch a focused Context7 verifier in a fresh session.
