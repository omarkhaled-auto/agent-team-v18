# Pipeline Upgrade — Phase 5 Plan
## Quality Milestone Completion (no workarounds)

**Date:** 2026-04-28
**Scope:** Closing the Phase 5 risk inventory (initial Risks #33-#41 plus smoke-discovered Risks #44-#47; see §C) exposed by the M1+M2+M3 hardening smoke at HEAD `2d49a0a` (post-Phase-4 + Risk-#31/#32 fixes from session 2026-04-28). Builds on Phase 4.1-4.7 (`docs/plans/2026-04-26-pipeline-upgrade-phase4.md`).
**Smoke evidence root:** `v18 test runs/m1-hardening-smoke-20260428-112339/`
**Smoke landing memory (when written):** `~/.claude/projects/-home-omar-projects-agent-team-v18-codex/memory/smoke_2026-04-28_landing.md`
**Phase 4 reference:** `~/.claude/projects/-home-omar-projects-agent-team-v18-codex/memory/{phase_4_4,phase_4_5,phase_4_6,phase_4_7}_landing.md`
**Source-of-truth status:** v5. This document is the authoritative Phase 5 source. All open questions are RESOLVED in §M. New ambiguity discovered during implementation must be added as a `[NEW — Phase 5.<N>]` halt memo at end of doc (see §0.10).

---

## Section 0 — Execution Plan (READ FIRST)

### 0.0 Why Phase 5 exists

The 2026-04-28 M1 smoke validated Phase 4's recovery-cascade plumbing end-to-end (Phase 4.5 lift fired → audit-loop entered → Phase 4.6 anchor captured → master_plan reconciled → milestone marked COMPLETE). But the cascade's quality outcome was hollow:

* `STATE.json::milestone-1.status = "COMPLETE"` with `failure_reason = "wave_fail_recovered"`.
* AUDIT_REPORT.json on disk: 28 findings, all FAIL verdict (3 CRITICAL, 10 HIGH, 9 MEDIUM, 6 LOW), score 612/1000.
* `audit_fix_rounds` field exists on STATE.json but was 0 — and is in fact NEVER incremented anywhere in the codebase.
* Audit-fix loop terminated at cycle 1 without dispatching a single fix. Recovery succeeded only because the per-wave acceptance test (`docker compose build web`) did not cover the same TypeScript surface as the compile-fix gate's strict compile profile.
* Three Wave D compile-fix sub-agent attempts: attempt #1 (689s) and #2 (116s) had real Claude reasoning but didn't crack the 2 initial TS errors; attempt #3 was stillborn (`agent_teams_session_started` then 0 tool calls for 420s) — SDK / subprocess pipe wedge.

**Phase 5 closes this gap by replacing today's "build passes ⇒ COMPLETE" contract with a Quality Contract (§B) that requires both build correctness AND audit findings cleared (PASS or DEFERRED only) before a milestone is COMPLETE.**

This is a no-workarounds replacement, not a tuning effort. Every defect we found has a structural fix; Phase 5 ships them.

### 0.1 Cross-phase invariants (apply to every Phase 5.<N>)

These are the hard rules. Implementer agents who break any of them fail review.

1. **`git rev-parse HEAD` must equal `2d49a0a` (Phase 5 baseline) or a Phase 5.<previous> descendant.** If not, `git pull` and confirm. Phase 5.1 lands first; subsequent phases land on top.
2. **Targeted slice green at HEAD before any change.** Run the targeted slice (§0.5) and confirm 570+ passing. If anything breaks at baseline, halt and surface — Phase 5 does not patch unrelated regressions.
3. **No workarounds.** This phase exists because we ran out of timeouts/retries/thresholds to dial. Don't ship one more. If a fix is hard, surface to the user; don't bandage it.
4. **Reference accuracy is non-negotiable.** Every file:line citation in the plan was verified at HEAD `2d49a0a`. If a citation drifts during implementation, update the plan as you go (§0.10 halt memo) — don't silently retarget.
5. **No new top-level config flags without explicit reason.** Every flag added in Phase 5 must close a specific risk (§C) and have a kill-switch path. If a flag exists for "future flexibility", drop it.
6. **One commit per logical change.** Conventional Commits format: `feat(scope-or-area): <subject>`. Em-dash for clause separation in subject. The recent log is the style reference (see commits `2d49a0a`, `ad4d93c`, `497b444` from session 2026-04-28).
7. **Pre-existing failures stay pre-existing.** The Linux-migration leftover failures (`test_v18_phase4_throughput::test_phase4_end_to_end_integration`, `test_h3e_wave_redispatch::test_scaffold_port_failure_redispatches_back_to_wave_a_once`, `test_cli.py::TestMain::test_interview_doc_scope_detected`, `test_cli.py::TestMain::test_complex_scope_forces_exhaustive`) repro on master HEAD without any change. Don't claim them fixed; don't claim them new. Document as pre-existing in commit message.
8. **Use mcp__sequential-thinking thoroughly for any cross-phase interaction.** Especially Phase 5.2 (unified fix loop) — the interaction with Phase 4.5 cascade is non-trivial.
9. **Use context7 BEFORE answering anything that names a library/framework/SDK.** Especially when modifying compile-fix paths or test surface.
10. **Verify on disk, not from agent summary.** When an implementer agent reports artifacts produced or files changed, `ls` / `git diff` before marking the phase complete.
11. **Brief anti-patterns explicitly in dispatch prompts.** Each Phase 5.<N> kickoff prompt (§0.0 of this doc, when authored) must list "what NOT to do" alongside "what to do".
12. **Every phase ends with a landing memory.** Author `phase_5_<N>_landing.md` per the §0.9 template before declaring done.
13. **Implementer agent investigates first, checks in for approval, THEN implements.** Each agent reports its scope-understanding + planned approach, waits for team-lead confirm, then proceeds.
14. **Replay-smoke fixture before live smoke.** Where possible, exercise the new behaviour against `tests/fixtures/smoke_2026_04_26/` (frozen) before paying for a live smoke. Live smokes only when fixture validation insufficient.
15. **Anchor + ship contract preserved.** Phase 5 does NOT touch Phase 1's anchor primitives, Phase 2's test-surface lock, Phase 3's PreToolUse hook, or Phase 3.5's ship-block. Those are load-bearing for Phase 5's contract. If a Phase 5 change requires modifying those, surface as halt memo first.
16. **The Quality Contract (§B) is the anchor.** Every sub-phase change must serve the Quality Contract. If a change weakens the contract (e.g., loosens a check), it's wrong — re-design.

### 0.2 Cost budget

**Per-phase implementer-agent + smoke estimates (revised after review #11 — adversarial-pessimist cost-realism finding):**

* Phase 5.1: ~$5-10 implementer. No live smoke required.
* Phase 5.2: ~$10-20 implementer + 1 live M1 smoke ($15-35) — replay can't validate audit-team Claude actually targets the now-canonical path. Live smoke is non-optional.
* Phase 5.3: ~$5-10 implementer. No live smoke.
* Phase 5.4: ~$15-25 implementer + 1 live M1 smoke ($15-35) — observe `audit_fix_rounds > 0`. **Per-milestone cost cap (§M.M3) kicks in here**; smoke cost is bounded.
* Phase 5.5: ~$15-30 implementer + 1 live M1+M2 smoke ($30-60). Big change.
* Phase 5.6: ~$15-25 implementer + 1 **calibration smoke** ($15-35) BEFORE the gate ships strict ($30-60 if it goes hot) — see §M.M11. The calibration smoke measures wave-fail-rate delta with `tsc_strict_check_enabled=False` vs `=True` on the same milestone slice.
* Phase 5.7: ~$10-20 implementer + 1 live smoke ($15-35) with artificial bootstrap-wedge + productive-tool-idle injection.
* Phase 5.8: ~$10-20 implementer for **diagnostic-first phase** (§M.M7) + up to 10 diagnostic M1+M2 smokes ($30-60 each; $150-300 for the first 5, $300-600 if the sequential sampler reaches the cap). IF diagnostics confirm OpenAPI insufficiency, follow-up implementer ~$15-25 + 1 live M1+M2 smoke ($30-60). Diagnostic-first means we may not ship a full contract.
* Phase 5.9: ~$15-30 implementer + 1 live M1+M2 smoke ($30-60) + 1 6-milestone synthetic.

**Realistic Phase 5 cost floor: $400-700.** Smokes alone are now budgeted from explicit units: Phase 5.2/5.4/5.7 M1 smokes ($45-105), Phase 5.5/5.6 coordinated M1+M2 smokes plus calibration ($60-155), Phase 5.8a first five diagnostic M1+M2 smokes ($150-300), and Phase 5.9 M1+M2 smoke plus synthetic ($30-60+). Implementer dispatch remains ~$90-180. The prior $200-350 floor undercounted Phase 5.8a and Wave 2/3 variance smokes.

**Per-milestone cost cap during smokes (§M.M3):** $20 default; cli aborts the audit-fix loop if a single milestone's cumulative cost (Codex + audit dispatches + fix dispatches) exceeds this. Operator-overridable via `--milestone-cost-cap-usd <N>`. Prevents the fix-regression-runaway scenario the adversarial review surfaced.

Surface to user before each phase begins; if any phase trends **≥1.5x revised estimate**, surface immediately and re-scope.

### 0.3 Phase order + dependencies

**Revised after review #2 (architecture-reviewer hidden-dependency finding) — Phase 5.6 moved from Wave 3 to Wave 2:**

```
Wave 1 (this session, ~6-10 hours total, ~$25-50):
  5.1 — Audit termination scoring fix (R-#33 + R-#34)
  5.2 — Audit-team prompt path drift (R-#36) — TWO fix sites + lint test
  5.3 — STATE.json quality-debt fields (R-#37 + R-#38 data layer)
        (no parallel runs; each lands its own commit before next starts)

Wave 2 (~3-4 weeks, ~$170-330):
  5.4 — Cycle-1 dispatch refactor (R-#35) so fixes can land on cycle 1
  5.5 — Operator-visible quality-contract enforcement (R-#38 UX layer)
        + single-resolver helper for milestone status writes (per §M.M1)
        + state-invariant validator (per §M.M2)
        + migration command --rescan-quality-debt (per §M.M10)
  5.6 — Unified post-wave strict typecheck gate (R-#39 + R-#40)
        MOVED HERE from Wave 3 because Phase 5.5's _anchor capture
        depends on knowing tsc-state. Without 5.6, Phase 5.5 can
        capture _anchor/_complete/ on milestones with hidden TS errors
        that pass docker. 5.5 + 5.6 must land together.

Wave 3 (~2-3 weeks, ~$55-120):
  5.7 — Bootstrap watchdog for SDK pipe wedges (R-#41)
        + productive-tool idle watchdog for Codex reasoning loops (R-#45)
        + cumulative-wedge circuit breaker (per §M.M4)
        Independent of Wave 2 contract work; can land in parallel
        but smoke validation still serial.

Wave 4 (~3-4 weeks, ~$330-700 if Phase 5.8a reaches 10-smoke cap):
  5.8 — Cross-package type contract (R-#42)
        DIAGNOSTIC-FIRST per §M.M7: Phase 5.8 ships only Wave C
        diagnostics first; full contract only if diagnostics confirm
        OpenAPI is genuinely insufficient.
  5.9 — PRD decomposer milestone-size cap (R-#43)
```

Within each wave, sub-phases land sequentially in the order listed. **Within Wave 2, 5.5 and 5.6 land as a single coordinated landing (one PR or two back-to-back commits) because the Quality Contract gate at completion sites depends on the unified compile-profile + docker check.** Across waves, the next wave's first sub-phase must wait for the prior wave's last sub-phase to land + smoke clean.

**Wave 1 ships fully today (or this week) per user authorization.** Waves 2-4 are session-scheduled in subsequent weeks.

**Rollback story:** every Phase 5 sub-phase ships with a kill-switch flag (the data-only Phase 5.3 has one even though it's strictly additive — `--phase-5-quality-debt-fields-disabled` for emergency rollback). Phase 5.1's score-normalization is a math fix without a flag; rollback is `git revert`. Wave 1 commits are atomic; any regression caught after Wave 2 lands can revert Wave 1 commits independently because Wave 2 doesn't structurally depend on Wave 1's fixes (Wave 2 detects the same conditions Wave 1 detected; Wave 1 just makes detection accurate).

### 0.4 What this plan is NOT

* It is **not** a refactor of Phase 4. Phase 4's anchor / lock / hook / wave-awareness primitives stay byte-identical. Phase 5 layers on top.
* It is **not** a replacement for the audit team. The 6 auditors keep producing findings. Phase 5 just makes those findings actually drive fixes.
* It is **not** a scope expansion to "any stack" (Java, Python, Go, mobile). That's Phase 6+. Phase 5 is hardening within the existing NestJS+Next.js+Prisma+TS profile.
* It is **not** an LLM upgrade. We're using existing models (Sonnet 4.6 / Opus 4.7 / Codex gpt-5.4). Per-role model routing is documented as Phase 6+ candidate.

### 0.5 Targeted-slice command (the green-at-HEAD check)

```
pytest tests/test_pipeline_upgrade_phase4_{1,2,3,4,5,6,7}.py \
       tests/test_audit_fix_guardrails_phase{1,1_5,1_6,2,3,3_5}.py \
       tests/test_wave_d_path_guard.py \
       tests/test_agent_teams_backend.py \
       tests/wave_executor/ \
       tests/test_v18_wave_executor_extended.py \
       tests/test_hook_multimatcher_conflict.py \
       tests/test_v18_specialist_prompts.py \
       tests/test_scaffold_runner.py \
       tests/test_scaffold_m1_correctness.py \
       tests/test_audit_models.py \
       tests/test_wave_scope_filter.py \
       -p no:cacheprovider --tb=short
```

**Expected at Phase 5 baseline (HEAD `2d49a0a`):** 667 passing.

### 0.6 Wide-net sweep (run before merging each Phase 5.<N>)

```
pytest tests/ -k "audit_team or audit_fix or wave_failure or wave_executor or pipeline_upgrade or audit_models or audit_agent or fix_executor or fix_prd or milestone or anchor or state or scaffold or wave_boundary or wave_ownership or specialist_prompts or scope" \
  -p no:cacheprovider --tb=line
```

**Expected at Phase 5 baseline:** 1994 passing + 4 pre-existing failures (per §0.1 rule 7). New Phase 5 fixtures land on top.

### 0.7 Module import smoke (final pre-commit check)

```
python -c "import agent_team_v15.cli; import agent_team_v15.audit_team; import agent_team_v15.audit_models; import agent_team_v15.fix_executor; import agent_team_v15.wave_executor; import agent_team_v15.state"
```

Must exit 0 with no warnings.

### 0.8 Frozen fixture root

`tests/fixtures/smoke_2026_04_26/` — used by Phase 4.3 / 4.5 / 4.6 / 4.7 replay-smoke fixtures. Phase 5 fixtures should reuse this root where possible. Do NOT mutate the frozen artifacts; build synthetic project roots from templates when post-Phase-5 shape is needed.

### 0.9 Landing memo template

```markdown
---
name: Phase 5.<N> pipeline-upgrade landing
description: As-shipped state of Phase 5.<N> (<one-line scope>); required reading before Phase 5.<N+1>
type: project
originSessionId: <session-id>
---

Phase 5.<N> of the 9-phase Phase 5 plan landed direct-to-master on
<YYYY-MM-DD> off baseline `<prev-sha>` as commit `<this-sha>`.
Plan: `docs/plans/2026-04-28-phase-5-quality-milestone.md` §<X>.

## Files touched (matches plan §<X> file list)
...

## Actual API surface shipped
...

## Risks closed by Phase 5.<N>
* Risk #<id> — closed by ...

## Smoke evidence (when applicable)
- Run dir: ...
- EXIT_CODE: ...
- Phase 5 sub-phase observations: ...

## Open follow-ups (not blocking)
...

## Out-of-scope items the plan flags but Phase 5.<N> did NOT touch
...

## Verification gates passed
...

## Surprises
...
```

### 0.10 Halt memo format

If implementer agent discovers ambiguity NOT resolved in this plan:

```markdown
## [NEW — Phase 5.<N>] <issue-title>

**Found:** <date>, <agent-name>
**Context:** <one paragraph>
**Resolution requested from user:** <specific question>
**Proposed default if no resolution:** <fallback> (low-confidence; surface to user before applying)
```

Append at end of plan, do NOT proceed without resolution unless explicit fallback authorized.

---

## Section A — Empirical evidence base

The 2026-04-28 M1 hardening smoke (`v18 test runs/m1-hardening-smoke-20260428-112339/`) ran against `master` HEAD `2d49a0a` (post-Phase-4 + Risk #31 + Risk #32 fixes from earlier in session). M2 completed in the same smoke with the same hollow-recovery shape. M3 was still running when v5 was authored and had already exposed a productive-tool idle wedge in Wave B.

### A.0 Pattern confirmation: M2 also recovered hollow

After plan v1 was authored, the same smoke completed M2 (Wave B failed; same cascade pattern as M1's Wave D):

```
13:15:45 INFO wave_executor: Milestone COMPLETE anchor captured for milestone-2
         under .../milestones/milestone-2/_anchor/_complete
13:15:45 INFO wave_executor: _prune_anchor_chain: retained=2 pruned=0
         bytes_freed=0 bytes_remaining=791680
```

`STATE.json::milestone-2.status = "COMPLETE"` with `failure_reason="wave_fail_recovered"`. Same hollow-recovery shape as M1: cascade entered, audit cycle 1 terminated "healthy", zero fixes dispatched, re-self-verify (looser) passed, milestone marked COMPLETE with the audit findings unaddressed.

**Two consecutive milestones with identical hollow-recovery shape is empirical confirmation that this is the systematic state of the system today, not a one-off.** Phase 5 must close it across both wave-fail surfaces (Wave B failures and Wave D failures) and across both milestone shapes (foundation M1 and feature-light M2).

### A.0.5 M2 shape variance + build-scope divergence

M2 adds two empirical wrinkles that v3 did not encode:

* **Path drift is systematic, not M1-specific.** M2 wrote its report to the same nested non-canonical shape: `v18 test runs/m1-hardening-smoke-20260428-112339/.agent-team/milestone-2/.agent-team/AUDIT_REPORT.json`. This confirms R-#36 applies across milestones.
* **AUDIT_REPORT.json score shape differs materially from M1.** M2 has `score.score=525.0`, `score.max_score=0`, `score.critical_count=0`, `by_severity={}`, and 28 parsed findings: 4 CRITICAL, 10 HIGH, 11 MEDIUM, 3 LOW. M1 had `max_score=1000` and populated `by_severity`. Phase 5.1 must therefore repair both zeroed counters and nonsensical score scale state.
* **M2 wave-fail mode is Wave B project-scope Docker build failure, not Wave D compile-fix timeout.** The same hollow-recovery outcome appears from a different failure class: Wave B's wave-scope per-service self-verify passed, then endpoint probing's project-scope all-services Docker build failed on `pnpm install --frozen-lockfile`.

Verbatim M2 BUILD_LOG evidence:

```text
995 2026-04-28 12:53:15,079 INFO agent_team_v15.wave_executor: [Wave B] self-verify passed (retry=0/2)
997 2026-04-28 12:53:16,728 WARNING agent_team_v15.endpoint_prober: Docker build reported failures: [BuildResult(service='postgres', success=True, error='', duration_s=0.0), BuildResult(service='api', success=False, error='target api: failed to solve: process "/bin/sh -c pnpm install --frozen-lockfile" did not complete successfully: exit code: 1\n', duration_s=1.5893952810001792), BuildResult(service='web', success=True, error='', duration_s=0.0)]
998 Warning: Milestone milestone-2 failed: Wave execution failed in B: Docker build
999 failed during live endpoint probing startup
1000 [AUDIT-FIX] Phase 4.5 conditional Risk #1 lift active for milestone-2:
1001 dispatching audit-fix loop on wave-fail (safety nets armed;
1002 failure_reason=wave_fail_recovery_attempt).
1003 Audit cycle 1 for milestone milestone-2: deploying 6 auditor(s)
```

### A.0.6 M3 productive-tool idle + audit-subagent harness gaps

M3 adds three more harness defects from the same smoke run:

* **Codex productive-tool idle is not bounded by Phase 5.7's bootstrap watchdog.** M3 Wave B reached 15 touched files and then stopped emitting `commandExecution` work. BUILD_LOG evidence:

```text
2088 2026-04-28 14:26:35,507 INFO agent_team_v15.wave_executor: [Wave B] active - last commandExecution 3959s ago, 15 files touched so far, cumulative SDK calls: 1
2095 [Wave B] summary - last progress=2026-04-28T09:20:36.057904+00:00, last
2096 message=item/started, last tool=commandExecution, files touched=15, cumulative
2097 SDK calls=1, progress events=300
2129 2026-04-28 14:37:36,025 INFO agent_team_v15.wave_executor: [Wave B] active - last commandExecution 4619s ago, 15 files touched so far, cumulative SDK calls: 1
2148 2026-04-28 14:42:36,256 INFO agent_team_v15.wave_executor: [Wave B] active - last commandExecution 4920s ago, 15 files touched so far, cumulative SDK calls: 1
```

Local artifact correction: the BUILD_LOG copy on disk does **not** show `progress events` continuing past 300; it shows stale `last_progress_at` and stale `progress events=300`. The R-#45 fix still stands, but the plan must cover both variants: non-tool progress that refreshes `last_progress_at`, and stale-progress/no-fire behavior where the outer watchdog loop fails to convert long productive-tool idle into wave-fail.

* **Audit prompt advertises subagents that are not registered in `ClaudeAgentOptions.agents`.** M1 and M2 audit sessions report:

```text
348 Note: subagent types `audit-test` and `audit-mcp-library` are not in my
349 available agent list — I'll route those responsibilities through
350 `general-purpose` with the same audit briefs.
1279 1. **`audit-test` and `audit-mcp-library` agents are not registered** in the
1280 harness — falling back to `general-purpose` with the same briefs.
1760 - `audit-test` and `audit-mcp-library` agent types are NOT registered in the
1761 harness — fell back to `general-purpose` with the same brief.
```

* **Audit-* agents lack `Write`.** M2 audit sessions report:

```text
1281 2. **All four audit-* agents that ran lack Write tool** and returned findings
1282 inline. I'll persist their JSON to disk myself, then run the missing two via
1283 general-purpose (which has Write), then invoke audit-scorer.
1762 - `audit-requirements`, `audit-technical`, `audit-interface`,
1763 `audit-comprehensive` lack the `Write` tool — they returned findings inline
1764 only. Persisted their JSON to disk myself before invoking the scorer.
```

### A.1 M1 cascade trace (the canonical test case)

| Time | Event | File:line evidence |
|---|---|---|
| 11:33:48 | Wave A teammate spawned | `wave_executor.py:_apply_post_wave_scope_validation` flagged `.claude/settings.json` only (Risk #2 fix verified) |
| 11:35:47 | Wave A complete (118.5s) | `wave_executor.py:8023` self-verify gate (Wave A doesn't have one) |
| 11:35:54 → 11:47:54 | Wave B Codex turn (12min, $3.5358) | `codex_appserver` events; 25 files written |
| 11:47:54 → 11:53:59 | Wave B self-verify passed retry=0/2 | `wave_executor.py:8090` Wave B acceptance test invocation (line 8221+ for D mirror) |
| 11:58:05 → 12:09:34 | Wave D dispatch #1 (689.5s, 24 files written) | `agent_teams_backend` "spawning teammate teammate-wave-D-milestone-1" |
| 12:09:36 → 12:11:33 | Wave D compile-fix attempt #2 (116.5s, brief Claude session) | `wave_executor.py:5798 _run_wave_compile` is the compile-fix loop entry; ran but didn't fix |
| 12:11:34 → 12:18:35 | Wave D compile-fix attempt #3 STILLBORN — emitted `agent_teams_session_started` then 0 tool calls for 420s | hang report at `.agent-team/hang_reports/wave-D-20260428T081835Z.json` shows `last_sdk_message_type="agent_teams_session_started"`, `pending_tool_starts=[]` |
| 12:18:35 | Compile-fix exhausted 3 attempts → wave-fail with "Compile failed after 3 attempt(s)" | `wave_executor.py:5798+` final exit |
| 12:18:35 | Phase 4.5 lift active | `cli.py:7584` `_phase_4_5_safety_nets_armed` returned True |
| 12:18:35 | `failure_reason="wave_fail_recovery_attempt"` written to STATE.json | `cli.py:8067 _run_failed_milestone_audit_if_enabled` (Phase 4.5 stage-2 wiring) |
| 12:18:35 → 12:33:53 | Audit cycle 1: 6 auditors deployed; 28 findings; score 612.0/1000 | nested write at `.agent-team/milestone-1/.agent-team/AUDIT_REPORT.json` (path drift R-A4) |
| 12:33:53 | `should_terminate_reaudit` returned `(True, "healthy")` at cycle 1 | `audit_team.py:111` — `score 612 >= threshold 85` AND `critical_count 0` (zeroed by `audit_models.py:746`) |
| 12:33:58 | Phase 4.5 epilogue ran `run_wave_d_acceptance_test` (`docker compose build web`) → passed | `wave_d_self_verify.py:135` |
| 12:33:58 | Master plan reconciled to COMPLETE; STATE.json updated | `cli.py:8503+` reconcile site |
| 12:33:58 | Phase 4.6 anchor captured at `_anchor/_complete/` (884KB) | `wave_executor.py:_capture_milestone_anchor_on_complete` |
| 12:33:58 | `_prune_anchor_chain: retained=1 pruned=0 bytes_freed=0 bytes_remaining=383601` | `wave_executor.py:_prune_anchor_chain` |
| 12:33:59 | M2 milestone start; same cascade pattern observed (M2 Wave D failed, audit-loop entered, Phase 4.5 stage-2 written) | M2 evidence parallel to M1 |

### A.2 Critical observed defects

* **`audit_fix_rounds=0`** on STATE.json after recovery — but `audit_fix_rounds` is **never incremented anywhere** in the source tree (`grep -rn "audit_fix_rounds" src/` returns only field definition + load shim, no assignment increment). Field is dead-data, not a behavior signal. The auditor's claim "audit_fix_rounds=0 ⇒ audit-fix didn't run" was based on this static field; cannot be trusted.
* **AUDIT_REPORT.json at `<run-dir>/.agent-team/milestone-1/.agent-team/AUDIT_REPORT.json`** — nested path. `cli.py:5534-5535` constructs the audit dispatch's `requirements_path` and `audit_dir` WITHOUT the `"milestones"` segment (compare correct construction at `cli.py:2280` and `cli.py:1254`). Audit-team Claude self-corrected by writing to a non-canonical nested path.
* **AuditScore.critical_count = 0 with 3 actual CRITICAL findings.** The canonical smoke report's `score` field is an `AuditScore`-shaped dict, so `AuditReport.from_json` takes the `isinstance(raw_score, dict)` branch at `audit_models.py:729-730` and calls `AuditScore.from_dict`. That method blindly trusts `data["critical_count"]=0` at `audit_models.py:577` even though `by_severity.CRITICAL=3` and the parsed findings contain 3 CRITICAL entries — masking them from `should_terminate_reaudit`'s `critical_count==0` guard.
* **`should_terminate_reaudit` percentage-vs-raw bug.** `audit_team.py:111` — `if current_score.score >= healthy_threshold and current_score.critical_count == 0`. The `score_healthy_threshold` default is 90.0 (a percentage); the smoke config sets 85.0 (also intended as percentage). The auditor scorer writes raw 0-1000 score (612). Direct numeric comparison: 612 >= 85 → True → "healthy" exit immediately at cycle 1.
* **Cycle-1 fix dispatch is structurally blocked.** `cli.py:8472 for cycle in range(start_cycle, max_cycles + 1):` then `cli.py:8477 if cycle > 1 and current_report:` gates the fix dispatch site at `cli.py:8503`. Cycle 1 is "discover findings"; cycle 2 is "fix prior findings + re-audit". With `max_reaudit_cycles=2`, only ONE fix-dispatch round is possible per milestone, and only IF cycle 1 didn't terminate. Today's smoke: cycle 1 terminated → 0 fix dispatches.
* **Compile-fix vs acceptance-test divergence.** `wave_executor.py:5798 _run_wave_compile` runs the existing strict TypeScript compile profile. `wave_d_self_verify.py:135 run_wave_d_acceptance_test` runs `docker compose build web`. The smoke's `apps/web/next.config.mjs` does not set `typescript.ignoreBuildErrors`; the divergence is therefore treated as a scope mismatch between the compile profile and the acceptance build, not as "Next.js never typechecks." A milestone can fail compile-fix and pass acceptance-test on the same artifact. M1 demonstrates this exactly.
* **Compile-fix sub-agent has no Phase 4.2 retry feedback.** `wave_executor.py:5979 _build_compile_fix_prompt` is single-shot; takes the build error string, not the structured `<previous_attempt_failed>` payload Phase 4.2 wired into self-verify retries. Each compile-fix retry starts fresh with no progressive signal.
* **No bootstrap watchdog.** Wave watchdog at `wave_executor.py:_WaveWatchdogState` is idle-based (default 400s). A session that emits `agent_teams_session_started` and then 0 events takes 400s to detect. Idle-only; no first-tool-call deadline.

---

## Section B — The Quality Contract

This is the new anchor. Every Phase 5 sub-phase serves it.

> **Quality Contract for milestone COMPLETE:**
>
> A milestone transitions to `status="COMPLETE"` iff ALL of:
>
> 1. **All assigned waves executed** (or skipped per dependency rules — Wave T skip when D failed is a documented skip, not a silent miss).
> 2. **The deliverable passes BOTH** the repository compile profile (`compile_profiles.run_wave_compile_check`, strict TypeScript check across the relevant app/generated/shared surfaces) AND the project-scope all-services Docker build (`docker compose build` with no `SERVICE` arguments; implemented as `docker_build(..., services=None)`). One source of truth for "build successful". Wave-scope per-service builds remain fast diagnostics, but the project-scope all-services build is the authoritative Quality Contract gate (Phase 5.6).
> 3. **Audit findings on executed waves are PASS or DEFERRED only.** No FAIL findings of severity HIGH or above remain. (DEFERRED = Phase 4.3 owner_wave-not-yet-executed; carries forward.)
> 4. **STATE.json + master_plan.md reconcile** to COMPLETE/DEGRADED/FAILED with explicit quality fields. `_anchor/_complete/` remains the single Phase 4.6 anchor slot; Phase 5.5 writes `_anchor/_complete/_quality.json` when a COMPLETE or DEGRADED milestone is captured. No `_anchor/_degraded/` slot exists.
>
> **DEGRADED is the genuine intermediate state for "deliverable runs but has carry-forward debt":**
>
> * Build correctness PASSED (gate 2 satisfied).
> * All unresolved FAIL findings on executed waves are below HIGH severity (severity ≤ MEDIUM only) OR all unresolved findings are DEFERRED.
> * `status="DEGRADED"` is the result.
> * `STATE.json::milestone_progress[id]` carries `audit_status`, `unresolved_findings_count`, `audit_debt_severity`, `audit_findings_path` (Phase 5.3 + 5.5).
> * Operator sees a yellow-warning summary at milestone-end print.
>
> **FAILED is the strict-quality result for "the wave produced something the audit team can't accept":**
>
> * Any unresolved FAIL finding ≥ HIGH severity on an executed wave → FAILED, not COMPLETE, not DEGRADED.
> * This is the **default behavior** post-Phase-5.5 (revised after review #4 — architecture-reviewer principle-violation finding). The original opt-in strictness flag was a workaround; it's removed.
> * For operators who can't immediately fix existing builds, `--legacy-permissive-audit` is shipped as a **deprecated migration flag** with an evidence-based sunset gate (§M.M15). Use is logged loudly with the deprecation notice.
>
> **Forbidden states (structurally enforced, not just documented — see §M.M2):**
> * `status="COMPLETE"` AND ANY `unresolved_findings_count > 0` with `audit_debt_severity in {"CRITICAL","HIGH"}` (today's M1 outcome — IMPOSSIBLE after Phase 5.5 + state-invariant validator).
> * `_anchor/_complete/` captured for a milestone whose `_quality.json` sidecar is missing or inconsistent with `STATE.json` (today's M1 has no quality sidecar; Phase 5.5 makes the quality state explicit per §M.M8).
>
> **Enforcement mechanism:** Phase 5.5 splits invariants by lifecycle. Cheap STATE-shape invariants run from `save_state`; terminal Quality Contract and anchor/filesystem invariants run at resolver/capture boundaries and raise by default for new terminal writes. Historical rescan/migration stays warn-only. Lint test `tests/test_state_invariants.py` enforces no new forbidden states ship without validator extension.

### B.1 Why "build passes" is necessary but not sufficient

Today's contract is "build passes ⇒ COMPLETE". Empirical evidence (M1 smoke):
* Wave-scope Docker diagnostic passed (`docker compose build web`).
* Audit found 28 FAIL findings including 3 CRITICAL.
* Milestone marked COMPLETE.
* Anchor captured.
* Operator has no signal that 3 CRITICAL findings ship in a "complete" milestone.

This is the worst possible outcome for "actual quality": silent debt accumulation across milestones. By M6, accumulated debt is unbounded.

The Quality Contract makes "build passes" necessary (gate 2) but adds "audit findings cleared" (gate 3) before COMPLETE. Build-passes-but-audit-fails goes DEGRADED instead — operator-visible, not silently shipped.

### B.2 Why DEFERRED is acceptable but FAIL is not

Phase 4.3 already wave-tags findings. A DEFERRED finding is: "the owner wave for this finding hasn't run yet on this milestone; defer to a future milestone where the owner runs". That's intentional (e.g., a finding about apps/web/middleware.ts surfacing in M1 when only Wave D=>milestone-2 owns the final form).

A FAIL finding on an EXECUTED wave is different: the wave ran, produced output, and the auditor flagged a real defect. That's actionable now, not deferrable.

Quality Contract gate 3 explicitly distinguishes: PASS = clean, DEFERRED = legitimate carry-forward, FAIL = blocking debt.

---

## Section C — Phase 5 risk register

| Risk ID | Title | Surface | Phase that PARTIALLY closes | Phase that FULLY closes |
|---|---|---|---|---|
| **R-#33** | `should_terminate_reaudit` raw-vs-percentage threshold confusion | `audit_team.py:111` | — | Phase 5.1 |
| **R-#34** | `AuditScore` severity counters can be zero despite CRITICAL findings (dict-score branch trusts zero counters; flat fallback also zeros) | `audit_models.py:571-584`, `audit_models.py:727-754`, cited lines `577` + `746` | — | Phase 5.1 |
| **R-#35** | Cycle-1 fix-dispatch guard prevents any fix from landing in cycle 1 | `cli.py:8477` | — | Phase 5.4 |
| **R-#36** | Audit-team prompt path drift (TWO sites: cli.py:5037 + cli.py:5534-5535) | `cli.py:5037`, `cli.py:5534-5535` | — | Phase 5.2 (both sites + lint test per §M.M9) |
| **R-#37** | `audit_fix_rounds` field is dead-data (never incremented) | `state.py:62` | Phase 5.3 (field still uninitialized) | Phase 5.4 (incrementing wires up; landing memo for 5.3 must state "R-#37 NOT yet closed; field still uninitialized") |
| **R-#38** | No quality-debt fields on STATE.json — operator can't see hollow recoveries | `state.py:RunState`, `cli.py` milestone-completion sites | Phase 5.3 (data fields) | Phase 5.5 (UX wiring + state-invariant validator + single-resolver helper) |
| **R-#39** | Compile-fix vs acceptance-test build-check divergence (strict compile profile vs wave-scope `docker compose build <service>` acceptance scope) | `wave_executor.py:5798`, `wave_d_self_verify.py:135`, `compile_profiles.py:512-604` | — | Phase 5.6 |
| **R-#40** | Compile-fix sub-agent has no Phase 4.2 retry feedback | `wave_executor.py:5979 _build_compile_fix_prompt` | — | Phase 5.6 (joint with R-#39) |
| **R-#41** | No bootstrap watchdog — SDK-pipe-wedge sessions take 400s to detect | `wave_executor.py:_WaveWatchdogState` | — | Phase 5.7 (with cumulative wedge cap per §M.M4) |
| **R-#42** | Cross-package type contract is implicit (Wave B → Wave C → Wave D types coordinated only via OpenAPI YAML) | NEW `cross_package_contract.py` (or proven-unnecessary by diagnostics) | Phase 5.8a (diagnostics ship) | Phase 5.8b (full contract IF diagnostics confirm need; otherwise Wave A spec-quality fix per §M.M7) |
| **R-#43** | M1 has 15 ACs (above 13 recommended); planner does not auto-split | PRD decomposer | — | Phase 5.9 |
| **R-#44** | Build-check scope divergence (wave-scope per-service vs project-scope all-services Docker build) — M2 surfaced a 1.649s gap where Wave B self-verify passed the api service build but endpoint_prober's project-scope all-services build failed on api lockfile sync | `wave_b_self_verify.py:317-327`, `wave_d_self_verify.py:225-235`, `endpoint_prober.py:812`, `runtime_verification.py:325-329` | — | Phase 5.6 |
| **R-#45** | Codex productive-tool idle wedge — M3 Wave B had no `commandExecution` for 4920s, but the wave remained active until the 5400s Codex timeout path | `wave_executor.py:480-545`, `wave_executor.py:3651-3693`, `wave_executor.py:4167-4275`, `codex_appserver.py:1328-1357`, `codex_transport.py:356-385`, BUILD_LOG `2088-2148` | — | Phase 5.7 extension (§J.4) |
| **R-#46** | Audit prompt lists `audit-*` subagents that are built for prompt rendering but not injected into `ClaudeAgentOptions.agents` | `audit_team.py:397-404`, `cli.py:605-724`, `cli.py:6914-6954`, BUILD_LOG `348-350`, `1279-1280`, `1760-1761` | — | Phase 5.2 extension (§E.4.1) |
| **R-#47** | Audit-* subagents lack `Write`, so auditors return findings inline and the parent/scorer copy-pastes them to disk | `audit_team.py:397-427`, BUILD_LOG `1281-1283`, `1762-1764` | — | Phase 5.2 extension (§E.4.2) |

Risks #33-#41 and #44-#47 are session-observed (M1 + M2 + M3 hardening smoke 2026-04-28). Risks #42-#43 are architectural (deferred from Phase 4 §N).

**Partial-closure semantics (per architecture review #10):** A landing memo for a phase that PARTIALLY closes a risk MUST explicitly state the risk's open status. E.g., Phase 5.3 landing memo: "R-#37 NOT yet closed at this phase; `audit_fix_rounds` field added but not incremented; Phase 5.4 will wire incrementer." Prevents the field-shipped-without-incrementer false-fix trap.

---

## Section D — Phase 5.1 brief: Audit termination scoring fix

**Closes:** R-#33 + R-#34
**Effort:** ~1 hour implementation + 1 hour testing
**Cost:** ~$5-10 in implementer-agent dispatch
**No live smoke required** (replay fixture sufficient)

### D.1 Files touched

* `src/agent_team_v15/audit_team.py` — `should_terminate_reaudit` (line 99-140)
* `src/agent_team_v15/audit_models.py` — `AuditScore.from_dict` + `AuditReport.from_json` post-parse severity normalization (line 571-584 and 727-754)
* `tests/test_audit_models.py` — extend round-trip + add severity-counter regression fixture
* `tests/test_pipeline_upgrade_phase5_1.py` — NEW; locks the fix

### D.2 Current behavior (verified at HEAD `2d49a0a`)

`audit_team.py:99-140 should_terminate_reaudit`:
```python
def should_terminate_reaudit(
    current_score: AuditScore,
    previous_score: AuditScore | None,
    cycle: int,
    max_cycles: int = 3,
    healthy_threshold: float = 90.0,
) -> tuple[bool, str]:
    # Condition 1: Score meets healthy threshold with no criticals
    if current_score.score >= healthy_threshold and current_score.critical_count == 0:
        return True, "healthy"
    ...
```

`audit_models.py:571-584` (`AuditScore.from_dict`) and `audit_models.py:727-754` (`AuditReport.from_json` score parsing):
```python
if isinstance(raw_score, dict):
    score = AuditScore.from_dict(raw_score)  # <-- trusts critical_count=0
else:
    score = AuditScore(
        total_items=0, passed=0, failed=0, partial=0,
        critical_count=0, high_count=0, medium_count=0, low_count=0, info_count=0,
        score=flat_score,
        health=str(data.get("health", "")),
        max_score=max_score,
    )
```

### D.3 Why it's wrong

* `score_healthy_threshold` is documented and used as a percentage (`config.py:552 score_healthy_threshold: float = 90.0`). Smoke configs set 85.0 (also percentage).
* `current_score.score` may be either:
  * A 0-100 percentage (computed via `audit_models.py:529 score = (passed * 100 + partial * 50) / max(total, 1)` — the canonical compute path); or
  * A raw 0-`max_score` integer (when scorer output preserves raw points, e.g. the smoke's dict-shaped `score.score=612.0` with `score.max_score=1000`).
* `should_terminate_reaudit` doesn't normalize. Comparison `612 >= 90` returns True → "healthy" exit, ignoring that 612/1000 = 61.2% < 90% threshold.
* The `critical_count == 0` second guard would catch this if populated. But both the dict-shaped smoke score and the flat-score fallback can carry zero counters; `critical_count = 0` despite 3 actual CRITICAL findings in `report.findings` and `by_severity.CRITICAL=3`.
* Net: cycle 1 terminates as "healthy", no fix dispatch happens (fix site at `cli.py:8503` only runs in `cycle > 1` per `cli.py:8477`).

### D.4 Target behavior

`should_terminate_reaudit` normalizes to percentage:
```python
def _score_pct(score: AuditScore) -> float:
    if score.max_score <= 0:
        raise InvalidAuditScoreScale(
            f"cannot compare audit score with max_score={score.max_score}"
        )
    return score.score if score.max_score == 100 else (score.score / score.max_score) * 100.0

def should_terminate_reaudit(
    current_score: AuditScore,
    previous_score: AuditScore | None,
    cycle: int,
    max_cycles: int = 3,
    healthy_threshold: float = 90.0,
) -> tuple[bool, str]:
    # Phase 5.1 (Risk #33): normalize to percentage. ``score_healthy_threshold``
    # is documented and consumed as a percentage (0-100). When AuditScore
    # carries raw points (e.g., scorer-agent flat output 612/1000), divide
    # to percentage before comparison. Invalid scale state must already have
    # been repaired by AuditReport.from_json, or this helper fails closed.
    score_pct = _score_pct(current_score)

    # Condition 1: Score meets healthy threshold with no criticals
    if score_pct >= healthy_threshold and current_score.critical_count == 0:
        return True, "healthy"
    ...
```

Same normalization in `Conditions 3-5` (regression / no_improvement) — the previous_score might be a different scale. Callers normalize for ALL comparisons inside the helper.

`AuditReport.from_json` applies one post-parse score normalizer for BOTH score shapes. The normalizer never trusts zero counters or nonsensical score scale when stronger evidence exists; precedence is:

1. Non-empty explicit `finding_counts` (case-insensitive keys: `critical`/`CRITICAL`, etc.).
2. Non-empty `by_severity` map (either `{severity: count}` or `{severity: [finding_ids...]}` shapes).
3. Parsed `findings` list.
4. Existing `AuditScore` counters only when no better source exists.

```python
def _normalize_score_from_report(score: AuditScore, data: dict, findings: list[AuditFinding]) -> AuditScore:
    if score.max_score <= 0 or score.score > score.max_score:
        if findings:
            # Canonical 0-100 compute path; see audit_models.py:506-552.
            score = AuditScore.compute(findings)
        else:
            raise InvalidAuditScoreScale(
                "AUDIT_REPORT.json has invalid score scale and no findings to recompute from"
            )

    counts = _severity_counts_from_finding_counts(data.get("finding_counts"))
    if not counts:
        counts = _severity_counts_from_by_severity(data.get("by_severity"))
    if not counts:
        counts = _severity_counts_from_findings(findings)
    if not any(counts.values()):
        return score
    return replace(
        score,
        critical_count=counts["CRITICAL"],
        high_count=counts["HIGH"],
        medium_count=counts["MEDIUM"],
        low_count=counts["LOW"],
        info_count=counts["INFO"],
    )

score = _normalize_score_from_report(score, data, findings)
```

If `max_score <= 0` or `score > max_score` and the report has no parseable findings, Phase 5.1 must treat the report as invalid for healthy termination. It must not route through a synthetic denominator or silently declare the audit healthy. This is the v4 tightening from M2: M2 only avoided hollow termination because its findings list was still parseable.

### D.5 Acceptance criteria

* AC1: replay synthetic fixture with `score=612, max_score=1000, threshold=85, findings=[3 CRITICAL]` → `should_terminate_reaudit` returns `(False, "")` (NOT healthy).
* AC2: replay synthetic fixture with `score=92, max_score=100, threshold=90, findings=[]` → returns `(True, "healthy")` (canonical compute path still works).
* AC3: replay synthetic fixture with `score=870, max_score=1000, threshold=85, findings=[]` → returns `(True, "healthy")` (raw passes after normalization, 87% > 85%).
* AC4: canonical smoke-shape fixture with dict `score={critical_count: 0, high_count: 0, score: 612.0, max_score: 1000}`, `by_severity={CRITICAL: 3, HIGH: 10, MEDIUM: 9, LOW: 6}`, and 28 parsed findings → `AuditScore` has `critical_count=3, high_count=10`.
* AC5: synthetic AUDIT_REPORT.json with flat `score=612`, `max_score=1000`, and `finding_counts={critical: 3, high: 10, ...}` → `AuditScore` has `critical_count=3, high_count=10`.
* AC6: synthetic AUDIT_REPORT.json with flat score AND no `finding_counts`/`by_severity` but findings list with severities → `from_json` counts severity from findings list.
* AC7: backward-compat — synthetic AUDIT_REPORT.json with computed score (max_score=100, total_items>0) is unaffected when no stronger severity source exists.
* AC8: `previous_score` regression check (`current_score.score < previous_score.score - 10`) also normalizes — synthetic with prior=70 raw and current=60 raw on max=100 scale should NOT be raw-comparable to a percentage-scale fixture.
* AC9: M2 synthetic shape with `score={score: 525.0, max_score: 0, critical_count: 0}`, `by_severity={}`, and findings list containing 4 CRITICAL findings → `AuditReport.from_json` recomputes through `AuditScore.compute(findings)`, returns canonical `max_score=100`, sets `critical_count=4`, and `should_terminate_reaudit` sees the recomputed percentage score, not bogus `525/0` or `525/100`.

### D.6 Tests shipped

`tests/test_pipeline_upgrade_phase5_1.py`:
* `test_should_terminate_reaudit_normalizes_raw_score_to_percentage` (AC1+AC3)
* `test_should_terminate_reaudit_canonical_percentage_path_still_works` (AC2+AC7)
* `test_audit_report_from_json_repairs_dict_score_zero_counts_from_by_severity` (AC4)
* `test_audit_report_from_json_populates_critical_count_from_finding_counts` (AC5)
* `test_audit_report_from_json_populates_critical_count_from_findings_list_fallback` (AC6)
* `test_should_terminate_reaudit_regression_check_normalizes_both_scales` (AC8)
* `test_audit_report_from_json_recomputes_invalid_scale_from_findings` (AC9)
* `test_replay_smoke_2026_04_28_cycle_1_does_not_terminate_healthy` — uses `tests/fixtures/smoke_2026_04_28/AUDIT_REPORT.json` (NEW frozen fixture from current smoke; copy the m1-hardening-smoke-20260428-112339 nested-path AUDIT_REPORT.json verbatim)

### D.7 Anti-patterns

* **Don't** change `AuditScore.score` field semantics. Some callers expect raw, others expect percentage. The fix is in the COMPARISON site (normalize on read), not in the field's storage.
* **Don't** set a default `max_score=100` if it's missing or zero — that masks scorer-agent output drift. Recompute through `AuditScore.compute(findings)` when findings are parseable; otherwise treat the audit report as invalid for healthy termination.
* **Don't** fix only the flat-score branch. The 2026-04-28 smoke takes the dict branch and is the regression fixture Phase 5.1 must repair.
* **Don't** flip `score_healthy_threshold`'s default from 90 to a different number to "compensate". The threshold is correct; the comparison was wrong.

---

## Section E — Phase 5.2 brief: Audit-team prompt path drift fix

**Closes:** R-#36 + R-#46 + R-#47
**Effort:** ~0.5-1 day
**Cost:** ~$8-15
**Live M1 smoke required** (replay fixture covers path/injection mechanics; live smoke proves audit-team Claude receives and uses registered audit subagents)

### E.1 Files touched

* `src/agent_team_v15/cli.py` — line 5534-5535 (the wave-fail recovery audit-dispatch path-build site)
* `src/agent_team_v15/cli.py` — `_build_options` signature + audit dispatch call at line 6954 (R-#46)
* `src/agent_team_v15/audit_team.py` — `build_auditor_agent_definitions` tool lists at lines 397-427 (R-#47)
* NEW `src/agent_team_v15/audit_output_path_guard.py` (or equivalent hook/can_use_tool helper) — restrict audit-session Write/Edit to audit outputs
* `src/agent_team_v15/agent_teams_backend.py` — hook settings writer extension if the implementation uses a PreToolUse hook for audit-output scope
* `tests/test_pipeline_upgrade_phase5_2.py` — NEW; locks the path construction, audit agent injection, and audit Write scope

### E.2 Current behavior (verified at HEAD `2d49a0a`)

`cli.py:5520-5547` (Phase 4.4 wave-fail audit dispatch site):
```python
if _phase_4_4_wave_result_for_forensics is not None:
    try:
        total_cost += await _run_failed_milestone_audit_if_enabled(
            milestone_id=milestone.id,
            ...
            requirements_path=str(req_dir / milestone.id / "REQUIREMENTS.md"),
            audit_dir=str(req_dir / milestone.id / ".agent-team"),
            ...
```

`req_dir` is `.agent-team/`. The constructions produce:
* `requirements_path = ".agent-team/milestone-1/REQUIREMENTS.md"` — **WRONG** (missing "milestones" segment; actual path is `.agent-team/milestones/milestone-1/REQUIREMENTS.md`).
* `audit_dir = ".agent-team/milestone-1/.agent-team"` — **WRONG** (missing "milestones" segment AND nests `.agent-team` twice).

Compare correct constructions elsewhere:
* `cli.py:1254`: `Path(cwd) / ".agent-team" / "milestones" / milestone_id / "REQUIREMENTS.md"`
* `cli.py:2280` (natural-completion audit dispatch): `audit_dir = str(req_dir / "milestones" / milestone.id / ".agent-team")`

### E.3 Why it's wrong (empirical)

Audit-team Claude received the prompt with the wrong paths and self-corrected by writing AUDIT_REPORT.json to `.agent-team/milestone-1/.agent-team/AUDIT_REPORT.json` — the nested non-canonical path. Downstream consumers expect canonical:
* `cli.py:6967 report_path = Path(audit_dir) / "AUDIT_REPORT.json"` — looks at `audit_dir` from the broken construction.
* `cli.py:8369 report_path = Path(audit_dir) / "AUDIT_REPORT.json"` — same.
* The H4 resume guard at `cli.py:8370 if report_path.is_file()` returned False because the file was written elsewhere → loop restarted from cycle 1 (or didn't see existing report).

Net: even when audit-team Claude produces a correct report, the orchestrator can't find it from the canonical path. AUDIT_REPORT.json's downstream consumers (Phase 4.6 reconciliation, Phase 4.5 epilogue, Phase 4.3 owner_wave aggregation) are blind.

M1/M2 also proved two audit-harness defects after v4:

* `build_auditor_agent_definitions` creates `audit-test` and `audit-mcp-library` keys, but `_run_milestone_audit` only uses those definitions for prompt text. At `cli.py:6954`, it passes positional `None` as `_build_options`' cwd argument and never supplies the audit-specific definitions, so those definitions are discarded before `ClaudeAgentOptions` is constructed.
* Current `_build_options` signature is `def _build_options(config, cwd=None, constraints=None, ...)`; the second positional argument is **cwd**, not agent definitions. Therefore the literal fix "pass `agent_defs` as the second positional arg" is wrong for current source. Phase 5.2 must add an explicit keyword path.
* `audit_team.py:402` gives specialized auditors Read/Glob/Grep and only adds Bash for `test`; `audit_team.py:412` gives `audit-comprehensive` Read/Glob/Grep only; only `audit-scorer` has `Write` at `audit_team.py:427`.
* There is no `audit_team.allow_audit_write`-style config gate. Existing `audit_fix_path_guard` is not sufficient for audit agents because it no-ops unless `AGENT_TEAM_FINDING_ID` is set; non-fix audit dispatches leave that env var unset.

### E.4 Target behavior

**Both broken sites (per §M.M9) are corrected:**

`cli.py:5037` (architecture-gate-fail audit dispatch):
```python
# BEFORE (BUG):
audit_dir=str(req_dir / milestone.id / ".agent-team"),
# AFTER:
audit_dir=str(req_dir / "milestones" / milestone.id / ".agent-team"),
```

`cli.py:5534-5535` (Phase 4.4 wave-fail audit dispatch):
```python
# BEFORE (BUG):
requirements_path=str(req_dir / milestone.id / "REQUIREMENTS.md"),
audit_dir=str(req_dir / milestone.id / ".agent-team"),
# AFTER:
requirements_path=str(req_dir / "milestones" / milestone.id / "REQUIREMENTS.md"),
audit_dir=str(req_dir / "milestones" / milestone.id / ".agent-team"),
```

Both mirror `cli.py:2280` (correct natural-completion construction).

### E.4.1 R-#46 target behavior: inject audit subagents into SDK options

Extend `_build_options` with an explicit optional keyword; do **not** use the second positional arg:

```python
def _build_options(
    config: AgentTeamConfig,
    cwd: str | None = None,
    constraints: list | None = None,
    task_text: str | None = None,
    depth: str | None = None,
    backend: str | None = None,
    system_prompt_addendum: str | None = None,
    agent_defs_override: dict[str, dict] | None = None,  # Phase 5.2 / R-#46
) -> ClaudeAgentOptions:
    agent_defs_raw = build_agent_definitions(...)
    if agent_defs_override:
        agent_defs_raw.update(agent_defs_override)
    agent_defs = {
        name: AgentDefinition(**{k: v for k, v in defn.items() if k in _ad_params})
        for name, defn in agent_defs_raw.items()
    }
```

Then update the audit dispatch:

```python
options = _build_options(
    config,
    cwd=None,
    task_text=task_text,
    depth=depth,
    backend=_backend,
    agent_defs_override=agent_defs,
)
```

Context7 `/anthropics/claude-agent-sdk-python` confirms `ClaudeAgentOptions(agents={...})` accepts `AgentDefinition` objects, and each `AgentDefinition` can carry `tools=[...]` such as `["Read", "Write"]`. This is the correct injection surface; it is not `subagents` or `setting_sources`.

This single `_run_milestone_audit` call-site fix covers:
* failed-milestone audit dispatch,
* normal re-audit loop dispatch,
* final integration audit at `cli.py:6692-6702` (because it also calls `_run_milestone_audit` with `auditors_override=["interface"]`).

### E.4.2 R-#47 target behavior: auditor Write with audit-output scope

Add `Write` to every `audit-*` auditor definition that must persist findings:

```python
tools = ["Read", "Write", "Glob", "Grep", "Bash"] if auditor_name == "test" else ["Read", "Write", "Glob", "Grep"]
...
agents["audit-comprehensive"] = {
    ...
    "tools": ["Read", "Write", "Glob", "Grep"],
}
```

Do **not** ship this as a bare tool-list change. Phase 5.2 must also add audit-output write scope. Acceptable implementations:

* preferred: a dedicated `audit_output_path_guard` PreToolUse hook enabled only for audit sessions via env such as `AGENT_TEAM_AUDIT_OUTPUT_ROOT`, `AGENT_TEAM_AUDIT_REQUIREMENTS_PATH`, and `AGENT_TEAM_AUDIT_WRITER=1`;
* acceptable: an SDK `can_use_tool` permission callback with the same allowlist semantics if the current SDK path supports it cleanly.

Allowed write/edit targets for audit sessions:
* `{audit_dir}/*_findings.json` and `{audit_dir}/audit-*_findings.json` for per-auditor output,
* `{audit_dir}/AUDIT_REPORT.json` for the scorer,
* `requirements_path` for audit verdict updates.

Everything else is denied. The hook must no-op outside audit sessions, just as `audit_fix_path_guard` no-ops outside per-finding fix dispatch. If a hook timeout/parse error would fail open, keep the hook tiny and add a test proving malformed audit-output dispatch denies when audit env is active.

**NEW lint test (per §M.M9):**
```python
# tests/test_audit_dispatch_path_construction.py
def test_no_audit_dispatch_site_omits_milestones_segment():
    """Phase 5.2 (R-#36): every audit_dir / requirements_path construction
    in cli.py for per-milestone audit dispatch must include the
    'milestones' segment. The 2026-04-28 smoke surfaced TWO sites with
    the broken pattern; this test fails CI on any future regression."""
    cli_text = Path("src/agent_team_v15/cli.py").read_text(encoding="utf-8")
    # The bug shape is: "req_dir / milestone.id" (no 'milestones' segment).
    # Match: requirements_path=str(req_dir / milestone.id /  OR
    #        audit_dir=str(req_dir / milestone.id /
    bad_pattern = re.compile(
        r"(?:requirements_path|audit_dir)=str\(\s*req_dir\s*/\s*milestone\.id\s*/",
        re.MULTILINE,
    )
    matches = bad_pattern.findall(cli_text)
    assert not matches, (
        f"Phase 5.2 R-#36 regression: found {len(matches)} broken audit-dispatch "
        f"path construction(s) in cli.py. All such constructions must include "
        f"'milestones' segment between req_dir and milestone.id. "
        f"See docs/plans/2026-04-28-phase-5-quality-milestone.md §M.M9."
    )
```

### E.5 Acceptance criteria

* AC1: synthetic test — invoke `_run_failed_milestone_audit_if_enabled` with mocked dispatch; assert the `requirements_path` and `audit_dir` arguments contain `"milestones"` segment (string match) at BOTH `cli.py:5037` AND `cli.py:5534-5535` call sites.
* AC2: replay synthetic — frozen smoke fixture with FAILED M1 wave-fail input → after Phase 5.2 fix, `_run_audit_loop` reads AUDIT_REPORT.json from canonical path.
* AC3: backward-compat — natural-completion path at `cli.py:2280` is unchanged (no regression in non-recovery flow).
* AC4: lint test (`tests/test_audit_dispatch_path_construction.py`) passes at HEAD post-Phase-5.2; fails on synthetic regression where one site is reverted.
* AC5 (LIVE SMOKE per adversarial review #8): Phase 5.2's smoke commitment changes from "no live smoke required" to "1 live M1 smoke required" — replay fixture cannot validate that audit-team Claude actually targets the now-canonical path. Smoke evidence: AUDIT_REPORT.json on disk at `.agent-team/milestones/milestone-1/.agent-team/AUDIT_REPORT.json` (canonical, NOT nested).
* AC6: synthetic test — monkeypatch `build_auditor_agent_definitions` to return `audit-test`, `audit-mcp-library`, and `audit-scorer`; invoke `_run_milestone_audit`; captured `ClaudeSDKClient.options.agents` contains those audit keys as `AgentDefinition` objects.
* AC7: lint test — no positional-`None` `_build_options` call remains inside `_run_milestone_audit`; audit dispatch uses `cwd=None` keyword plus `agent_defs_override=agent_defs`.
* AC8: integration-audit fixture — `auditors_override=["interface"]` still injects `audit-interface` into `ClaudeAgentOptions.agents`.
* AC9: synthetic test — every key returned by `build_auditor_agent_definitions([...])` whose name starts with `audit-` and is not `audit-scorer` includes `Write` in `tools`.
* AC10: synthetic test — `audit-output` guard allows `Write` to `{audit_dir}/audit-requirements_findings.json`, `{audit_dir}/AUDIT_REPORT.json`, and `Edit` to `requirements_path`.
* AC11: synthetic test — `audit-output` guard denies `Write` to a source file such as `apps/api/src/main.ts` while audit env is active.
* AC12: backward-compat — outside audit env, `audit-output` guard is transparent so Wave A/B/C/D and audit-fix dispatches are unaffected.

### E.6 Tests shipped

`tests/test_pipeline_upgrade_phase5_2.py`:
* `test_run_failed_milestone_audit_if_enabled_uses_canonical_paths`
* `test_audit_dir_construction_matches_natural_completion_path`
* `test_replay_smoke_canonical_audit_report_path_resolves`
* `test_run_milestone_audit_injects_audit_agent_definitions`
* `test_run_milestone_audit_uses_agent_defs_override_keyword_not_positional_none`
* `test_integration_audit_injects_interface_auditor_definition`
* `test_audit_agent_definitions_include_write_for_auditors`
* `test_audit_output_path_guard_allows_only_audit_outputs`
* `test_audit_output_path_guard_noops_outside_audit_env`

### E.7 Anti-patterns

* **Don't** add a "search both paths" fallback. The path construction is wrong; fix it. Fallback would mask future drifts.
* **Don't** introduce a helper function for path construction unless there are 3+ similar sites that would benefit. The fix is two lines — don't over-engineer.
* **Don't** pass `agent_defs` as `_build_options(config, agent_defs, ...)`; the second positional arg is `cwd` in current source.
* **Don't** list audit subagents in prompt text unless the same keys are present in `ClaudeAgentOptions.agents`.
* **Don't** add `Write` to auditors without audit-output write scope; existing `audit_fix_path_guard` is finding-id-bound and does not protect normal audit dispatches.

---

## Section F — Phase 5.3 brief: STATE.json quality-debt fields

**Closes:** R-#37 + R-#38 (data layer)
**Effort:** ~2-3 hours
**Cost:** ~$5-10
**No live smoke required**

### F.1 Files touched

* `src/agent_team_v15/state.py` — `RunState.milestone_progress` shape extension
* `src/agent_team_v15/state.py` — `update_milestone_progress` signature extension
* `tests/test_pipeline_upgrade_phase5_3.py` — NEW
* `tests/test_state_persistence.py` (if exists; otherwise fold into Phase 5.3 fixture)

### F.2 Current shape (verified at HEAD `2d49a0a`)

`state.py:62 audit_fix_rounds: int = 0` — defined but **never incremented**. Confirmed via `grep -rn "audit_fix_rounds" src/` returning only:
* `state.py:62` definition
* `state.py:772` load shim (`_expect`)

No write site. Field is dead-data.

`milestone_progress[id]` shape (per `cli.py:update_milestone_progress`):
```python
{"status": "COMPLETE" | "FAILED" | "DEGRADED" | "IN_PROGRESS" | "PENDING",
 "failure_reason": str}  # Phase 1.6 + Phase 4.4/4.5 wiring
```

No fields for audit findings count, severity, or path.

### F.3 Target shape

`state.py:62` — DEPRECATE `audit_fix_rounds` (mark for removal in Phase 6+; keep for now to avoid fixture churn). Add explicit comment that it's not incremented.

`milestone_progress[id]` shape extended:
```python
{"status": ...,
 "failure_reason": str,
 # Phase 5.3 — quality-debt fields. Populated at milestone-completion sites
 # (natural and recovery) from AuditReport.score + findings.
 "audit_status": "clean" | "degraded" | "failed" | "unknown",
 "unresolved_findings_count": int,           # FAIL findings on executed waves, severity ≥ HIGH
 "audit_debt_severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "",  # max severity of unresolved
 "audit_findings_path": str,                 # absolute path to AUDIT_REPORT.json that produced these
 "audit_fix_rounds": int,                    # incremented per `_run_audit_fix_unified` call (Phase 5.4 wires this)
}
```

`update_milestone_progress` extended kwargs:
```python
def update_milestone_progress(
    state, milestone_id, status, *,
    failure_reason: str = "",
    audit_status: str = "",
    unresolved_findings_count: int = -1,    # -1 = "don't update"
    audit_debt_severity: str = "",
    audit_findings_path: str = "",
    audit_fix_rounds: int | None = None,    # None = "don't update"
) -> None:
```

Empty defaults preserve byte-shape for callers who don't pass the new kwargs.

`load_state` adds `_expect` shims for each new field (mirrors Phase 4.6's pattern at `state.py:743 convergence_cycles=_expect(...)`).

### F.4 Acceptance criteria

* AC1: round-trip — write a `RunState` with all new fields populated, load it back, assert equality.
* AC2: backward-compat — load a `RunState` JSON without the new fields → fields default to empty strings / 0 / "unknown".
* AC3: `update_milestone_progress(state, "milestone-1", "DEGRADED", audit_status="degraded", unresolved_findings_count=28, audit_debt_severity="HIGH", audit_findings_path="/path/AUDIT_REPORT.json", audit_fix_rounds=2)` → STATE.json on disk carries all five fields.
* AC4: `update_milestone_progress(state, "milestone-2", "COMPLETE")` (no quality kwargs) → STATE.json's milestone-2 entry has status=COMPLETE; quality fields are at their defaults (NOT erased to None).
* AC5: existing Phase 1.6 / 4.4 / 4.5 fixtures pass byte-identically (no audit_status was passed; field defaults).

### F.5 Tests shipped

`tests/test_pipeline_upgrade_phase5_3.py` — 5 fixtures (one per AC).

### F.6 Anti-patterns

* **Don't** rename `audit_fix_rounds`. Keep the field; deprecate in comment. Renaming churns fixtures unnecessarily. Phase 5.4 will start incrementing it.
* **Don't** make any new field required. All defaults preserve backward compat.
* **Don't** wire the operator-visible UX in this phase. That's Phase 5.5. This phase is data-layer only.

---

## Section G — Phase 5.4 brief: Cycle-1 fix-dispatch refactor

**Closes:** R-#35
**Effort:** ~1 week
**Cost:** ~$10-20 + 1 live smoke (~$15-35)
**Live M1 smoke required** (refactor changes loop semantics; replay fixture insufficient)

### G.1 Files touched

* `src/agent_team_v15/cli.py` — `_run_audit_loop` body (lines 8472-8700)
* `tests/test_pipeline_upgrade_phase5_4.py` — NEW
* `tests/test_pipeline_upgrade_phase4_5.py` — extend existing fixtures to verify cycle-1 dispatch (Phase 4.5's epilogue contract is preserved)

### G.2 Current behavior (verified at HEAD `2d49a0a`)

`cli.py:8472`:
```python
for cycle in range(start_cycle, max_cycles + 1):
    ...
    if cycle > 1 and current_report:
        # Snapshot files before fix
        # Fix findings from previous cycle
        modified_files, fix_cost = await _run_audit_fix_unified(
            current_report, config, cwd, task_text, depth,
            fix_round=cycle, ...
        )
    ...
```

Fix dispatch only on cycle > 1. With `max_reaudit_cycles=2`, only cycle 2 dispatches. If cycle 1 terminates (Phase 5.1 fix corrects the spurious termination, but legitimate "healthy at cycle 1" is also possible), no fixes ever land.

### G.3 Why it's wrong

The Quality Contract requires fix dispatch when cycle 1 reveals FAIL findings ≥ HIGH severity. The "discover only on cycle 1, fix only cycle 2+" pattern was a Phase 1 design that assumed cycle 1's findings might be transient noise. Empirical evidence (M1 smoke) shows cycle 1 findings are real and actionable; the old design loses a fix-dispatch round.

### G.4 Target behavior

Cycle 1 dispatches fixes when findings warrant; cycle 2+ re-audits and dispatches additional rounds:

```python
for cycle in range(start_cycle, max_cycles + 1):
    # 1. Audit (cycle 1 = initial; cycle N = re-audit after prior fixes)
    current_report, audit_cost = await _run_milestone_audit(...)
    total_cost += audit_cost

    # 2. Termination check (always, even cycle 1 — gate against
    #    healthy-without-fixes state OR plateau OR max-cycles).
    stop, reason = should_terminate_reaudit(
        current_report.score, previous_score, cycle, max_cycles,
        config.audit_team.score_healthy_threshold,
    )
    if stop:
        break

    # 3. Fix dispatch — Phase 5.4 promotes this to fire on every cycle
    #    that didn't terminate, including cycle 1.
    modified_files, fix_cost = await _run_audit_fix_unified(
        current_report, config, cwd, task_text, depth,
        fix_round=cycle, ...
    )
    total_cost += fix_cost

    # 4. Increment audit_fix_rounds (Phase 5.3 field, now wired here).
    if state is not None:
        state.milestone_progress.setdefault(milestone_id, {})["audit_fix_rounds"] = (
            state.milestone_progress.get(milestone_id, {}).get("audit_fix_rounds", 0) + 1
        )
        save_state(state, ...)

    previous_score = current_report.score
```

### G.5 Acceptance criteria

* AC1: synthetic test — cycle 1 audit returns 28 FAIL findings (3 CRITICAL); should_terminate_reaudit returns False; `_run_audit_fix_unified` IS called with cycle=1.
* AC2: synthetic test — cycle 1 audit returns clean (score 95% computed, 0 critical); should_terminate_reaudit returns True; `_run_audit_fix_unified` is NOT called.
* AC3: synthetic test — cycle 1 dispatch + cycle 2 re-audit + cycle 2 dispatch + cycle 3 audit hits max_cycles. State.audit_fix_rounds=2.
* AC4: existing Phase 4.5 epilogue preserved — re-self-verify still runs after the audit loop terminates.
* AC5: Phase 1.5 CrossMilestoneLockViolation handling preserved — exception path unchanged.
* AC6: live M1 smoke at HEAD post-Phase-5.4 — observe `state.milestone_progress[id].audit_fix_rounds > 0` for milestones that had audit findings.

### G.6 Tests shipped

`tests/test_pipeline_upgrade_phase5_4.py` — 5 unit fixtures (AC1-AC5) + 1 live-smoke acceptance pointer.

### G.7 Anti-patterns

* **Don't** delete the `_snapshot_files` / `_restore_snapshot` rollback path. It's a separate mechanism for in-memory rollback when fix dispatch regresses score >10 points. Phase 5.4 keeps it.
* **Don't** loop fix-dispatch within a cycle. One dispatch per cycle. Multiple cycles = multiple dispatches with re-audit between.
* **Don't** increment `audit_fix_rounds` inside `_run_audit_fix_unified`. Increment at the call site so the helper's other callers (legacy paths) don't get unintended state mutation.

---

## Section H — Phase 5.5 brief: Quality-Contract enforcement at completion sites

**Closes:** R-#38 (UX layer) + the "_anchor/_complete/ on degraded milestones" gap
**Effort:** ~1 week
**Cost:** ~$15-30 + 1 live M1+M2 smoke (~$30-60)
**Live smoke required** (validates `_anchor/_complete/` captures only COMPLETE/DEGRADED with `_quality.json`; FAILED does not capture)

### H.1 Files touched

* `src/agent_team_v15/cli.py` — milestone-completion sites (natural at ~`cli.py:6196` post-Phase-2; recovery at ~`cli.py:5570+` post-Phase-4.5)
* `src/agent_team_v15/wave_executor.py` — `_capture_milestone_anchor_on_complete` gate refinement
* `src/agent_team_v15/cli.py` — argparse `--legacy-permissive-audit` migration flag
* `tests/test_pipeline_upgrade_phase5_5.py` — NEW

### H.2 Current behavior

`_capture_milestone_anchor_on_complete` (Phase 4.6) gates on `milestone_status in ("COMPLETE", "DEGRADED")`. Captures even when audit is failed.

`milestone-completion sites`: write `STATE.json::milestone_progress[id].status = "COMPLETE"` based on build success only. No quality-contract gate.

`master_plan.md`: status reflects build success.

`cli.py` print: no quality-warning summary when COMPLETE has unresolved findings.

### H.3 Target behavior

**Quality-Contract gate** at each milestone-completion site:
```python
def _evaluate_quality_contract(audit_report, run_state, config):
    """Return (final_status, audit_status, unresolved_count, debt_severity).

    final_status in {"COMPLETE", "DEGRADED", "FAILED"} per Quality Contract §B.
    """
    if audit_report is None:
        return "COMPLETE", "unknown", 0, ""

    unresolved_fail = [
        f for f in audit_report.findings
        if f.verdict == "FAIL"
        and compute_finding_status(f, run_state) != "DEFERRED"
    ]
    if not unresolved_fail:
        return "COMPLETE", "clean", 0, ""

    high_plus = [f for f in unresolved_fail if f.severity in {"CRITICAL", "HIGH"}]
    if high_plus:
        if config.v18.legacy_permissive_audit:
            _warn_legacy_permissive_audit(high_plus)
            return "DEGRADED", "degraded", len(unresolved_fail), _max_severity(unresolved_fail)
        return "FAILED", "failed", len(unresolved_fail), _max_severity(unresolved_fail)

    return "DEGRADED", "degraded", len(unresolved_fail), _max_severity(unresolved_fail)
```

`_capture_milestone_anchor_on_complete` extended (single slot per §M.M8):
```python
def _phase_4_6_capture_anchor_on_complete(*, cwd, milestone_id, milestone_status, audit_status, audit_report, config):
    # Phase 5.5 (single-slot per §M.M8):
    # - _anchor/_complete/ is the only slot (Phase 4.6 contract preserved).
    # - Quality info goes into _anchor/_complete/_quality.json sidecar.
    # - Capture happens for both COMPLETE and DEGRADED (operator may want
    #   to retry from a degraded milestone).
    # - FAILED milestones do NOT capture (Phase 1 anchor restore handles that).
    if milestone_status not in ("COMPLETE", "DEGRADED"):
        return None
    capture_path = _capture_to_complete(cwd, milestone_id)
    _write_quality_sidecar(capture_path, audit_report, audit_status, milestone_status)
    return capture_path

def _write_quality_sidecar(capture_path: Path, audit_report, audit_status, milestone_status):
    """Phase 5.5 §M.M8 — write _quality.json alongside the captured tree."""
    quality_blob = {
        "quality": "clean" if audit_status == "clean" else "degraded",
        "audit_status": audit_status,
        "milestone_status": milestone_status,
        "unresolved_findings_count": _count_unresolved_fail(audit_report),
        "audit_debt_severity": _max_severity_unresolved(audit_report),
        "audit_findings_path": str(_resolve_audit_report_path(audit_report)),
        "captured_at": _now_iso(),
    }
    (capture_path / "_quality.json").write_text(
        json.dumps(quality_blob, indent=2, sort_keys=True),
        encoding="utf-8",
    )
```

`--legacy-permissive-audit` argparse flag (per §M.M15/B — the only migration escape hatch):
```python
parser.add_argument(
    "--legacy-permissive-audit",
    action="store_true",
    help="DEPRECATED: Restore pre-Phase-5.5 permissive contract "
         "where milestones with FAIL findings ≥ HIGH severity may ship as DEGRADED "
         "instead of FAILED. "
         "Default behavior post-Phase-5.5 is strict: such milestones go FAILED. "
         "Use is logged loudly; migrate by addressing HIGH/CRITICAL findings so "
         "only the normal ≤ MEDIUM DEGRADED path remains.",
)
```

The Quality Contract gate routes:
* No unresolved FAIL on executed waves (PASS-only or all FAIL are DEFERRED) → COMPLETE (audit_status="clean").
* Unresolved FAIL findings exist but all are ≤ MEDIUM → DEGRADED (audit_status="degraded").
* ANY FAIL ≥ HIGH on executed waves → FAILED (audit_status="failed"), unless `--legacy-permissive-audit` flag is set, in which case routes to DEGRADED with deprecation warning.

Operator-visible print at milestone-end:
```
╭───────────── Milestone Quality Summary ─────────────╮
│ milestone-1: DEGRADED                               │
│ Audit: 8 unresolved findings                         │
│   0 CRITICAL · 0 HIGH · 6 MEDIUM · 2 LOW             │
│ Top severity unresolved: MEDIUM                      │
│ Findings: <run-dir>/.agent-team/milestones/m-1/.agent-team/AUDIT_REPORT.json │
╰──────────────────────────────────────────────────────╯
```

### H.4 Acceptance criteria

* AC1: synthetic test — milestone with no findings at completion → status COMPLETE, audit_status clean, `_anchor/_complete/` captured with `_quality.json.quality="clean"`.
* AC2: synthetic test — milestone with only LOW/MEDIUM unresolved findings → status DEGRADED, audit_status degraded, `_anchor/_complete/` captured with `_quality.json.quality="degraded"`.
* AC3: synthetic test — milestone with 3 HIGH unresolved (no flag) → status FAILED, audit_status failed, NO anchor capture (Phase 1 anchor restore fires per existing Phase 4.5 wiring).
* AC4: synthetic test — milestone with 3 HIGH unresolved (`--legacy-permissive-audit`) → status DEGRADED, audit_status degraded, `_anchor/_complete/` captured with `_quality.json.quality="degraded"` and deprecation warning emitted.
* AC5: synthetic test — milestone with all DEFERRED findings (Wave D didn't execute) → status COMPLETE, audit_status clean, _anchor/_complete/ captured (DEFERRED ≠ FAIL for the contract).
* AC6: print test — synthetic milestone-completion run captures stdout, asserts the Quality Summary box appears for DEGRADED.
* AC7: live M1+M2 smoke — observe `_anchor/_complete/` on disk only for COMPLETE/DEGRADED milestones, always with `_quality.json`; FAILED milestones do not capture; `_anchor/_degraded/` must not exist.

### H.5 Tests shipped

`tests/test_pipeline_upgrade_phase5_5.py` — 7 fixtures.

### H.6 Anti-patterns

* **Don't** reintroduce an opt-in strictness flag. Strict HIGH/CRITICAL handling is the default; `--legacy-permissive-audit` is the only migration escape hatch and must be noisy.
* **Don't** delete `_anchor/_complete/` for backward-compat. Phase 4.6 fixtures depend on it; rename would churn. Do not add `_anchor/_degraded/`; quality is represented by `_anchor/_complete/_quality.json`.
* **Don't** bypass the Quality Contract for the integration audit (`AUDIT_REPORT_INTEGRATION.json`). The integration audit is advisory; per-milestone audit is gating. Document the distinction in code comments.

---

## Section I — Phase 5.6 brief: Unified strict build gate (close compile-vs-docker and narrow-vs-broad divergence)

**Closes:** R-#39 + R-#40 + R-#44
**Effort:** ~2 weeks
**Cost:** ~$10-20 + 1 live M1 smoke (~$15-35)

### I.1 Files touched

* `src/agent_team_v15/wave_b_self_verify.py` — `run_wave_b_acceptance_test` extension
* `src/agent_team_v15/wave_d_self_verify.py` — `run_wave_d_acceptance_test` extension (line 135-220)
* `src/agent_team_v15/agents.py` — `build_wave_b_prompt` + `build_wave_d_prompt` suffix mandate
* `src/agent_team_v15/wave_executor.py` — `_run_wave_compile` retirement (or convert to thin shim that just calls the unified gate)
* `src/agent_team_v15/wave_executor.py` — `_build_compile_fix_prompt` extends to use Phase 4.2 retry payload
* `src/agent_team_v15/codex_fix_prompts.py` — `build_codex_compile_fix_prompt` extends similarly
* `src/agent_team_v15/config.py` — `RuntimeVerificationConfig.tsc_strict_check_enabled: bool = True`
* NEW `tests/test_pipeline_upgrade_phase5_6.py`

### I.2 Current behavior

`runtime_verification.py:269-329 docker_build`: `services=None` builds every service in the compose file, argv shape `docker compose -f <compose> build --parallel`. `services=[...]` builds only those named services, argv shape `docker compose -f <compose> build --parallel <service...>`.

`wave_b_self_verify.py:317-327` and `wave_d_self_verify.py:225-235`: default `narrow_services=True`, resolve a wave-scope service target, and pass it to `docker_build(..., services=services_arg)`. Wave B therefore grades the api service only; Wave D grades the web service only.

`endpoint_prober.py:812` and `endpoint_prober.py:848`: calls `docker_build(project_root, compose_file)` without `services`, which is project-scope all-services build.

M2 proves these are not equivalent: Wave B's wave-scope api self-verify passed at BUILD_LOG line 995, then endpoint_prober's project-scope all-services build failed at line 997 on the api image's `pnpm install --frozen-lockfile` layer.

`wave_executor.py:5798 _run_wave_compile`: runs `pnpm tsc --noEmit` (or stack-equivalent). Only fires INSIDE the wave self-verify retry loop AFTER acceptance test passes (so a wave that passes the wave-scope Docker diagnostic but fails tsc could enter compile-fix).

`agents.py:build_wave_d_prompt`: doesn't mandate in-session typecheck.

`_build_compile_fix_prompt` at `wave_executor.py:5979`: takes `error_summary` string, doesn't include the structured `<previous_attempt_failed>` Phase 4.2 payload.

### I.3 Why it's wrong

The checks are layered today:

* Wave-scope per-service Docker diagnostic lives in Wave B/D self-verify.
* Project-scope all-services Docker build lives in endpoint probing / runtime verification.
* Strict TypeScript compile profile lives in `_run_wave_compile`.

A wave-author that passes the wave-scope Docker diagnostic but fails the compile profile enters a different code path (compile-fix) than a wave-author that fails Docker self-verify. M2 adds a third split: a wave-scope Docker pass can still be followed 1.649s later by a project-scope all-services Docker failure.

The Quality Contract requires ONE authoritative source of truth: build success = strict compile profile passes AND project-scope all-services Docker build passes. Phase 5.6 keeps wave-scope per-service builds as fast diagnostics/retry-attribution, but the Quality Contract gate is the project-scope all-services build. If either the diagnostic or the authoritative gate fails, the wave fails; if they disagree, the authoritative project-scope failure wins.

Context7 + current Docker docs confirm `docker compose build` accepts optional `[SERVICE...]` args; no service args means all configured build services, `--with-dependencies` is opt-in, and `--no-cache` disables builder cache. M2 does not justify making `--no-cache` the default Quality Contract gate because the normal project-scope all-services build already exposed the failure. If future calibration shows cache-sensitive false passes, rerun with `--no-cache` as a diagnostic artifact and surface that data before changing the default gate.

In-wave typecheck text is only a hint. The authoritative contract is the post-wave validator, which calls the existing compile-profile runner and records the exact diagnostics that docker/Next did not catch.

Compile-fix retries get Phase 4.2 strong feedback: `<previous_attempt_failed>` payload with parsed errors, unresolved imports, progressive signal across retries.

### I.4 Target behavior

`run_wave_d_acceptance_test` extended:
```python
def run_wave_d_acceptance_test(
    cwd: Path,
    *,
    autorepair: bool = True,
    timeout_seconds: int = 600,
    narrow_services: bool = True,
    stack_contract: dict | None = None,
    modified_files: list | None = None,
    prior_attempts: list | None = None,
    this_retry_index: int | None = None,
    strong_feedback_enabled: bool = True,
    tsc_strict_enabled: bool = True,    # Phase 5.6 NEW
) -> WaveDVerifyResult:
    ...
    # Phase 5.6a: existing wave-scope per-service Docker diagnostic.
    # Kept for fast feedback and precise retry attribution; not sufficient
    # for the Quality Contract.
    diagnostic_results = docker_build(
        cwd_path,
        compose_file,
        timeout=timeout_seconds,
        services=services_arg,
    )

    # Phase 5.6b: authoritative project-scope all-services Docker build.
    # This is docker_build(..., services=None), i.e. project-scope
    # `docker compose build` with no SERVICE args. It uses normal cache by default; `--no-cache`
    # is a diagnostic rerun, not the default gate.
    project_results = docker_build(
        cwd_path,
        compose_file,
        timeout=timeout_seconds,
        services=None,
    )

    # Phase 5.6c: strict compile profile, runs after Docker diagnostics.
    # Project-scope Docker + compile profile must both pass for the wave to
    # be accepted. Reuses compile_profiles instead of inventing a web-only
    # pnpm tsc helper.
    if tsc_strict_enabled:
        compile_result = run_wave_compile_check(
            cwd_path,
            wave_letter="D",
            modified_files=modified_files or [],
            timeout_seconds=120,
        )
        if not compile_result.passed:
            return WaveDVerifyResult(
                passed=False,
                build_failures=[...diagnostic/project Docker results...],
                tsc_failures=compile_result.errors,
                error_summary=compile_result.error_summary,
                retry_prompt_suffix=build_retry_payload(
                    wave_letter="D",
                    docker_failures=[...diagnostic/project Docker failures...],
                    tsc_failures=compile_result.errors,
                    prior_attempts=prior_attempts,
                    this_retry_index=this_retry_index,
                ),
            )
    ...
```

NEW `WaveDVerifyResult.tsc_failures: list[str]` field.

NEW `WaveDVerifyResult.project_build_failures: list[BuildResult]` (or equivalent structured field) so a narrow-pass / broad-fail case is visible in retry payloads instead of collapsed into a generic Docker failure string. Wave B mirrors the same field shape.

NO new web-only TypeScript helper. Phase 5.6 reuses `compile_profiles.run_wave_compile_check` because it already discovers the relevant TypeScript project surfaces (`apps/web`, generated client, shared packages) and already parses combined stdout/stderr. The Wave D acceptance test becomes the single caller that combines wave-scope Docker diagnostic result + project-scope all-services Docker result + compile-profile result into one `WaveDVerifyResult`.

`build_wave_d_prompt` suffix HINT (per §M.M5 — NOT a contract):
```
### Optional: pre-completion type-check (encouraged, not required)
The wave validator runs the repository compile profile definitively
after this session ends. You are encouraged but not required to run it
inline. If you do run it and find errors, fixing them in-session means
you don't burn a self-verify retry. If you skip the inline check and
errors remain, the wave will be re-dispatched with structured retry
feedback (Phase 4.2 payload).

(The wave-grader is the authoritative gate; this is a productivity hint.)
```

**Critical:** the wave's success is decided by the post-wave validator (the unified `run_wave_d_acceptance_test` in §I.4), NOT by Claude's self-report of having run the compile profile. If Claude declares done without running the hint, the post-wave validator runs the compile profile and either passes (clean) or fails (errors found → wave-fail with retry feedback). Don't trust the claim; verify the artifact.

`_run_wave_compile` retirement:
* Phase 5.6 does NOT rewrite the compile primitive. It moves the existing compile-profile check into the unified acceptance gate.
* Keep `_run_wave_compile` as a thin shim during transition (one-week deprecation window) that delegates to the same shared compile-profile path. After Phase 5.6's smoke validates, retire only the duplicate call path, not the compile-profile implementation.

`_build_compile_fix_prompt` (kept during transition) extends to use `build_retry_payload` from `retry_feedback` module — same payload Wave B/D self-verify retries use.

### I.5 Acceptance criteria

* AC1: synthetic test — Wave D acceptance test runs compile profile + project-scope all-services Docker build; both pass → `passed=True`.
* AC2: synthetic test — Wave D acceptance test: compile profile fails, project-scope all-services Docker build passes → `passed=False`, `tsc_failures` populated, `retry_prompt_suffix` includes structured TS error parsing.
* AC3: synthetic test — Wave D acceptance test: project-scope all-services Docker build fails, compile profile passes (rare but possible) → `passed=False`, `project_build_failures` populated.
* AC4: synthetic test — Wave D acceptance test: compile profile unavailable (e.g., pnpm not installed) → graceful skip with `env_unavailable=True` (mirrors docker-unavailable contract).
* AC5: live M1 smoke — observe wave-D acceptance test invoking BOTH checks; observe wave-fail when only compile profile fails; observe Phase 4.5 cascade entering on the unified failure.
* AC5a: calibration artifact — for every compile-profile failure where docker passes, persist the exact TypeScript diagnostics and the checked tsconfig/package surface so the landing memo proves the divergence source.
* AC6: backward-compat — when `tsc_strict_check_enabled=False` (kill switch), behavior is byte-identical to pre-Phase-5.6.
* AC7: Wave B mirror — same checks for `run_wave_b_acceptance_test` against `apps/api/`.
* AC8: synthetic test — wave-scope per-service Docker diagnostic passes, then project-scope all-services Docker build fails on `pnpm install --frozen-lockfile` for the api service (M2 shape) → `passed=False`; retry payload includes the project-scope failure output and labels it authoritative.

### I.6 Tests shipped

`tests/test_pipeline_upgrade_phase5_6.py` — 9 fixtures.

### I.7 Anti-patterns

* **Don't** silently disable the compile profile for legacy stacks. The kill switch is opt-out for the operator; default on.
* **Don't** parallelize compile profile + docker (run one then the other). They have different failure semantics; cleaner to serialize.
* **Don't** invent a web-only `pnpm tsc --noEmit` helper. Reuse `compile_profiles.run_wave_compile_check` so generated/shared TypeScript drift is covered.
* **Don't** treat a wave-scope per-service Docker diagnostic pass as Quality Contract build success. The project-scope all-services Docker build is authoritative.
* **Don't** make `--no-cache` the default gate without calibration evidence. Use it only as a diagnostic rerun when cache behavior is suspected, because it materially changes cost and build behavior.
* **Don't** delete `_run_wave_compile` in this phase. One-week deprecation window during which call sites migrate to the unified gate. Removal is a follow-up commit after the smoke validates.

---

## Section J — Phase 5.7 brief: Bootstrap watchdog for SDK pipe wedges

**Closes:** R-#41 + R-#45
**Effort:** ~1 week
**Cost:** ~$10-20 + 1 live smoke

### J.1 Files touched

* `src/agent_team_v15/wave_executor.py` — `_WaveWatchdogState` extension, watchdog tick logic
* `src/agent_team_v15/agent_teams_backend.py` — surface stderr from claude binary subprocess
* `src/agent_team_v15/config.py` — `V18Config.bootstrap_idle_timeout_seconds: int = 60`
* `src/agent_team_v15/config.py` — `V18Config.tool_call_idle_timeout_seconds: int = 1200`
* `tests/test_pipeline_upgrade_phase5_7.py` — NEW

### J.2 Current behavior

`_WaveWatchdogState` at `wave_executor.py` (search result line 481+) tracks last_progress_at; idle threshold default 400s for Wave D's `orphan_tool_idle_timeout_seconds`.

A session that emits `agent_teams_session_started` and then 0 events takes 400s to detect.

`agent_teams_backend.py` swallows stderr from the bundled `claude --print` subprocess.

M3 adds a distinct Codex failure mode:
* `_WaveWatchdogState.record_progress` at `wave_executor.py:508-545` has no separate `last_tool_call_at` field; it updates `last_progress_at` for every callback and stores only `last_tool_name`.
* Codex app-server progress uses `item/started` and `item/completed` for tool/execution items, and `item/agentMessage/delta` for streaming assistant text (`codex_appserver.py:1328-1357`). Codex CLI JSONL progress similarly extracts `item.started` / `item.completed` generically (`codex_transport.py:356-385`).
* Context7 `/openai/codex` confirms Codex app-server `ThreadItem` includes agent replies, plans, reasoning, and tool executions; `commandExecution` is the command/tool execution item and is distinct from `agentMessage`/reasoning output.
* BUILD_LOG shows M3 Wave B stayed active with `last commandExecution` increasing from 3959s to 4920s. The local BUILD_LOG copy does not show `progress events` increasing past 300, so the root cause is not exclusively "reasoning refreshed `last_progress_at`"; Phase 5.7 must guard productive-tool idle directly and also test the stale-progress/no-fire shape.

### J.3 Target behavior

Two-phase watchdog (per §M.M6 — 60s/3 calibration):
1. **Bootstrap watchdog (Phase 5.7 NEW)**: from `agent_teams_session_started` event, deadline = `bootstrap_idle_timeout_seconds` (default 60, was 30 — adjusted per §M.M6 to absorb cold MCP server initialization). If exceeded, kill subprocess, log structured wedge event with stderr tail, respawn with fresh subprocess. NOT counted against per-wave retry budget.
2. **Idle watchdog (existing)**: only fires AFTER bootstrap watchdog cleared (i.e., at least one tool_call occurred). Existing 400s threshold preserved.
3. **Productive-tool idle watchdog (Phase 5.7 v5 extension; R-#45)**: tracks the last productive tool execution separately from generic SDK progress. Default `tool_call_idle_timeout_seconds=1200` (20 minutes). If no productive tool starts/completes within the threshold after bootstrap has cleared, fail the wave and let the Phase 4.5 cascade handle recovery. This does not respawn as a bootstrap wedge; it is a wave-fail signal because the model is alive but not producing executable work.
4. **Cumulative wedge circuit breaker (per §M.M4)**: Per-build counter `RunState._cumulative_wedge_budget`. Default cap 10. Each bootstrap-wedge respawn increments. When cap exceeded, build halts with `failure_reason="sdk_pipe_environment_unstable"`, EXIT_CODE=2.

`agent_teams_backend.py` captures stderr; on bootstrap-wedge, log a hang report (`hang_reports/wave-<X>-<ts>.json`) extended with:
* `stderr_tail`: last 4KB of subprocess stderr (rate-limit, auth, network errors).
* `cumulative_wedges_so_far`: read from RunState at wedge time.
* `bootstrap_deadline_seconds`: the configured deadline.

Per-wave respawn cap: 3 (was 2 per original draft; raised per §M.M6 calibration). After 3 respawns, the wave fails with `wave_d_failed` (or `wave_b_failed`) and Phase 4.5 cascade picks up.

`STATE.json::milestone_progress[id]._bootstrap_wedge_diagnostics`: per-wave summary { wave_letter: { respawns: int, last_wedge_iso: str, cumulative_at_wave_end: int } }. Phase 6+ retunes calibration data-driven.

### J.4 v5 extension: productive-tool idle watchdog

Add fields to `_WaveWatchdogState`:

```python
last_tool_call_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
last_tool_call_monotonic: float = field(default_factory=time.monotonic)
last_non_tool_progress_at: str = ""
last_productive_tool_name: str = ""
tool_call_event_count: int = 0
```

Update `record_progress` so productive tool events update `last_tool_call_*` and non-tool events only update `last_progress_*`. Productive means a Codex/Claude tool execution item, not any truthy `tool_name`. In Codex app-server/CLI paths, `commandExecution` is productive; `agentMessage`, `reasoning`, plan/text deltas, and token usage are non-productive progress. Keep the predicate centralized (for example `_is_productive_tool_event(message_type, tool_name, event_kind)`) so tests can lock it.

Timeout precedence:

1. Bootstrap watchdog fires first until the first productive tool event.
2. Existing orphan-tool watchdog remains more specific when a productive tool has started and is still pending.
3. Productive-tool idle fires when there is no pending orphan but `now - last_tool_call_monotonic >= tool_call_idle_timeout_seconds`.
4. If non-tool progress is recent but productive-tool idle is old, the failure kind is `tool-call-idle`, not healthy progress.

Hang report additions:

```json
{
  "timeout_kind": "tool-call-idle",
  "last_tool_call_at": "...",
  "tool_call_idle_timeout_seconds": 1200,
  "last_non_tool_progress_at": "...",
  "last_productive_tool_name": "commandExecution",
  "tool_call_event_count": 1
}
```

Config:
* `V18Config.tool_call_idle_timeout_seconds: int = 1200`.
* Load from config YAML via `_coerce_int`, with validation range `300 <= tool_call_idle_timeout_seconds <= codex_timeout_seconds`.
* Do not set this to 30/60s; those are bootstrap-scale values, not deep-reasoning/productive-work values.

### J.5 Acceptance criteria

* AC1: synthetic test — mock SDK that emits session_started but no tool calls; watchdog fires at 60s; respawn invoked; second session runs cleanly; wave passes.
* AC2: synthetic test — mock SDK that emits session_started + tool_call within 60s; bootstrap watchdog cleared; idle watchdog (400s) takes over; behavior unchanged from today.
* AC3: synthetic test — bootstrap-wedge stderr captured includes simulated "API rate limit exceeded".
* AC4: live M1 smoke — observe at least one bootstrap-wedge respawn (artificial: inject a transient pipe-pause); confirm respawn unblocks.
* AC5: bootstrap respawn doesn't increment retry counters (synthetic test verifies wave_executor's retry budget unchanged).
* AC6: synthetic M3 shape — after one `item/started` `commandExecution`, feed only `item/agentMessage/delta` / reasoning-like progress for >1200s; watchdog returns `timeout_kind="tool-call-idle"` even though `last_progress_at` is recent.
* AC7: synthetic stale-progress shape — after one `commandExecution`, feed no further progress for >1200s and ensure the watchdog still fails before `codex_timeout_seconds=5400`.
* AC8: precedence fixture — pending `commandExecution` older than `orphan_tool_idle_timeout_seconds` fires `orphan-tool`, not `tool-call-idle`.
* AC9: calibration fixture — `tool_call_idle_timeout_seconds=30` or `60` is rejected by config validation; default is exactly 1200.
* AC10: live M3 replay pointer — replay BUILD_LOG `2088-2148` shape and assert the wave would fail at 1200s productive-tool idle, not wait until 5400s Codex timeout.

### J.6 Tests shipped

`tests/test_pipeline_upgrade_phase5_7.py` — 10 fixtures.

### J.7 Anti-patterns

* **Don't** lower the idle watchdog threshold to 60s. The idle threshold protects mid-session pauses (Claude reasoning) which legitimately take >60s. Bootstrap is different — first tool_call should be fast.
* **Don't** auto-retry on every wedge. Limit bootstrap respawns to 3 per wave (otherwise a deep SDK bug could loop forever). If 3 respawns and still wedged, surface and fail the wave.
* **Don't** treat `agentMessage`, reasoning, token usage, or plan/text deltas as productive tool calls.
* **Don't** wait for `codex_timeout_seconds=5400` when the last productive tool call is already older than `tool_call_idle_timeout_seconds=1200`.
* **Don't** count tool-call-idle failures against the cumulative bootstrap-wedge respawn cap; this is a wave-fail/cascade path, not a subprocess bootstrap respawn.

---

## Section K — Phase 5.8 brief: Cross-package type coordination (diagnostic-first per §M.M7)

**Closes:** R-#42
**Effort:** Phase 5.8a ~3-5 days; Phase 5.8b ~2-3 weeks IF needed
**Cost:** Phase 5.8a ~$10-20 + sequential diagnostic smokes ($30-60 per M1+M2 smoke; $150-300 for the first 5, up to $300-600 at the 10-smoke cap); Phase 5.8b ~$15-25 + 1 live M1+M2 smoke ($30-60) IF triggered

### K.1 Phase 5.8a — Diagnostic-only

**Files touched:**
* `src/agent_team_v15/openapi_generator.py` — emit per-divergence diagnostic on Wave C generation
* `src/agent_team_v15/audit_models.py` — new finding code `CONTRACT-DRIFT-DIAGNOSTIC-001` (advisory only — does NOT block)
* `tests/test_cross_package_contract_diagnostics.py` — NEW

**Behavior:**

Wave C's `openapi_generator` already runs `openapi-ts` to generate `packages/api-client/`. Phase 5.8a adds a diagnostic step:
1. After client generation, parse the generated `.gen.ts` files.
2. For each exported type, compare the type shape (property names, types, optional vs required) against the OpenAPI `components.schemas` source.
3. Log every divergence as `CONTRACT-DRIFT-DIAGNOSTIC-001` finding into AUDIT_REPORT.json (severity LOW; advisory).
4. Aggregate per-smoke: log a divergence summary at end-of-Wave-C: `[CROSS-PACKAGE-DIAG] <N> divergences detected (samples: ...)`.

**Phase 5.8a smoke gate:** Run sequential M1+M2 diagnostic smokes. Stop early when 3 correlated divergences are observed; otherwise continue to 10 smokes before deciding the full contract is unnecessary. Measure:
* `divergences_detected_total / smoke_count`
* `unique_divergence_classes` (e.g., camelCase-vs-snake_case, optional-vs-required, missing-export)
* `divergences_correlated_with_compile_failures` (cross-reference Wave D compile-fix telemetry)

### K.2 Phase 5.8b — Decision gate

**If Phase 5.8a diagnostics show:**
* 3 correlated `CONTRACT-DRIFT-DIAGNOSTIC-001` findings before or at the 10-smoke cap → ship full contract (proceed to K.3 specifics).
* Fewer than 3 correlated findings after 10 smokes → close R-#42 by **Wave A spec-quality investment instead**: extend Wave A prompt to emit fully-fleshed OpenAPI 3.1 with explicit `additionalProperties: false` + complete `required` lists; add Wave A.5 plan reviewer check for OpenAPI completeness. NO `cross_package_contract.py` ships. Document the decision in Phase 5.8a landing memo.

### K.3 Phase 5.8b implementation (only if K.2 triggers)

(Detailed spec deferred to Phase 5.8b implementer kickoff if reached. Outline:)

* NEW `src/agent_team_v15/cross_package_contract.py` (~250 lines)
* `src/agent_team_v15/agents.py` — Wave A prompt extended to emit CROSS_PACKAGE_CONTRACT.json; Wave B + Wave D prompts include contract slice
* `src/agent_team_v15/openapi_generator.py` — Wave C generates packages/api-client/ AND validates against contract; promotes diagnostic to gating finding `CONTRACT-DRIFT-001` (severity HIGH)
* `tests/test_cross_package_contract.py` — NEW (6+ fixtures)

**ACs (Phase 5.8b only if reached):**
* AC1: Wave A produces `CROSS_PACKAGE_CONTRACT.json` with ≥3 entries (User, Project, Task DTOs).
* AC2: Wave C validates packages/api-client/ against contract; emits CONTRACT-DRIFT-001 (HIGH) finding when mismatch.
* AC3: Wave D's prompt for milestone-2 (Auth) includes the User DTO contract slice.
* AC4: synthetic test — Wave B emits camelCase; contract says camelCase → no drift. Wave B emits snake_case → CONTRACT-DRIFT-001 finding.
* AC5: live M1+M2 smoke — observe Wave C validation step + contract-driven Wave D prompt slice rendered.

### K.4 Anti-patterns

* **Don't** ship Phase 5.8b without Phase 5.8a diagnostic data. Decision gate is data-driven.
* **Don't** make the diagnostic finding gating in 5.8a — it's advisory, never blocks. Phase 5.8b makes it gating IF triggered.
* **Don't** dual-source. If 5.8b ships, contract.json is source of truth for type semantics; OpenAPI is for HTTP semantics. Document the split clearly.
* **Don't** trust Wave A blindly (per adversarial review #6 — Wave A's contract could be wrong-but-consistent). Phase 5.8b ships an oracle: a synthetic Wave-B-OpenAPI vs Wave-A-contract validation step that catches "Wave A's contract drifted from Wave B's actual emission" before downstream waves consume it.

---

## Section L — Phase 5.9 brief: PRD decomposer milestone-size cap

**Closes:** R-#43
**Effort:** ~1 week
**Cost:** ~$15-30 + 1 live M1+M2 smoke + 1 live 6-milestone synthetic

### L.1 Files touched

* `src/agent_team_v15/prd_decomposer.py` (or wherever the vertical_slice planner lives — verify at impl time)
* `src/agent_team_v15/cli.py` — Phase 1 plan validation (already warns at 13 ACs; Phase 5.9 makes it gate)
* NEW `tests/test_pipeline_upgrade_phase5_9.py`

### L.2 Acceptance criteria (outline)

* AC1: synthetic test — PRD with 30 ACs total decomposed into 6 milestones; no milestone has > 10 ACs. Splits where needed.
* AC2: synthetic test — PRD with 12 ACs in one feature; planner splits to M-a (8 ACs) + M-b (4 ACs).
* AC3: live M1 smoke at HEAD post-Phase-5.9 — M1 has ≤ 10 ACs (today: 15).
* AC4: backward-compat — existing tests with PRDs that already have ≤10 AC milestones unaffected.

(Detailed spec deferred to Phase 5.9 kickoff.)

---

## Section M — Resolved design decisions

### M.M1 Single-resolver helper for milestone status writes

**Question:** §H.3's Quality Contract gate is described as firing at "natural-completion ~cli.py:6196 + recovery-completion ~cli.py:5570+". But cli.py has 8+ literal `update_milestone_progress` writeback sites plus variable-status sites (verified: 4871 parallel group path; 5023, 5444, 5932, 6052, 6067, 6175, 6207, 6334, 6449, 8757). Without a single chokepoint, future bugs add new sites that bypass the contract.

**Resolution:** Phase 5.5 ships `_finalize_milestone_with_quality_contract(state, milestone, audit_report, config) -> None` as the **only authorized function** for quality-dependent terminal status writes. It may write COMPLETE, DEGRADED, or FAILED after evaluating the Quality Contract. Direct immediate FAILED writes that represent hard execution failure remain allowed. Existing terminal writeback sites are migrated:

* Sites that write `"FAILED"` directly (5023, 5444, 5932, 6175, 6207, 6449): unchanged. FAILED is a terminal state; no contract evaluation needed.
* Sites that write `"COMPLETE"` (~cli.py:6196 region), `"DEGRADED"` (6052), or a variable that can be `"COMPLETE"`/`"DEGRADED"` (`final_status` at `cli.py:4871`, `_final_status` at `cli.py:6334`): replaced with `_finalize_milestone_with_quality_contract(...)` call. The helper reads the audit report + run state + config, decides COMPLETE vs DEGRADED vs FAILED per the Quality Contract, calls `update_milestone_progress` once.
* Recovery site (5570+): same migration.

**Lint test (Phase 5.5 ships):** `tests/test_milestone_status_single_resolver.py` parses `src/agent_team_v15/cli.py` and fails on direct `update_milestone_progress(...)` calls outside the helper when the status argument is a literal `"COMPLETE"`/`"DEGRADED"` OR a local variable assigned from expressions that can produce those values (e.g. `final_status = "COMPLETE" if ... else "FAILED"`). Literal grep is insufficient because it misses the parallel path at `cli.py:4871`.

**Rationale:** The architecture-review #1 finding called this a blocker. Phase 5 cannot ship a Quality Contract that any future bug can bypass.

### M.M2 State-invariant validator

**Question:** §B "Forbidden states" are documented but enforced procedurally (only by `_evaluate_quality_contract` returning DEGRADED). Six months from now a refactor reorders writes; the forbidden state ships again.

**Resolution:** Phase 5.5 ships two invariant layers:
* `validate_state_shape_invariants(state: RunState) -> list[str]` in `state.py`, called from `save_state` always. It only checks cheap intra-STATE invariants that are valid during transitional writes.
* `validate_terminal_quality_invariants(state: RunState, *, cwd: Path, milestone_id: str) -> None`, called only from `_finalize_milestone_with_quality_contract` and `_capture_milestone_anchor_on_complete`. It checks Quality Contract + filesystem invariants and raises `StateInvariantViolation` by default for new terminal writes.

Historical commands (`rescan-quality-debt`, old-run migration, fixture replay) run terminal validators in warn-only mode so pre-Phase-5 hollow recovery can be reported without bricking migration.

**Initial rule set:**
* `forbidden_complete_with_high_debt`: `status == "COMPLETE" AND unresolved_findings_count > 0 AND audit_debt_severity in {"CRITICAL", "HIGH"}` → violation.
* `forbidden_anchor_without_quality_sidecar`: `_anchor/_complete/` present on disk AND `_anchor/_complete/_quality.json` missing or inconsistent with STATE.json → violation.
* `forbidden_failed_without_failure_reason`: `status == "FAILED" AND failure_reason == ""` → violation (Phase 1.6 contract).

**Lint test:** `tests/test_state_invariants.py::test_forbidden_complete_with_high_debt_raises_at_terminal_finalize` etc. Future Phase 6+ adds rules; cannot ship a forbidden-state-allowing change without extending the validator.

### M.M3 Per-milestone cost cap

**Question:** Cost spiral risk surfaced by adversarial review #3 — Phase 5.4 (cycle-1 dispatch) + Phase 5.5 (DEGRADED capture) + Phase 5.6 (stricter checks → more wave failures) → potential $30-80 per ill-fated milestone.

**Resolution:** Phase 5.4 ships `--milestone-cost-cap-usd` flag (default $20). The audit-fix loop tracks per-milestone cumulative cost (`total_cost` already plumbed in `_run_audit_loop`). When `cumulative_cost >= cost_cap`, the loop:
1. Logs `[AUDIT-FIX] Milestone cost cap $X reached at cycle N; aborting audit-fix loop`.
2. Persists `failure_reason = "cost_cap_reached"` and records the current audit-fix cost in STATE.json. It does NOT pre-set `audit_status="degraded"`.
3. Calls `_finalize_milestone_with_quality_contract`, which evaluates the actual unresolved findings. HIGH/CRITICAL unresolved findings still route to FAILED. Only low/medium-only unresolved findings may route to DEGRADED.
4. Phase 4.5 epilogue still runs (best-effort re-self-verify).

**Operator override:** `--milestone-cost-cap-usd 0` disables cap (legacy unbounded behavior). Documented as opt-in.

### M.M4 Cumulative bootstrap-wedge circuit breaker

**Question:** Adversarial review #4 — bootstrap watchdog caps respawns at 3 per wave, but a pathological day (Anthropic infra instability) could spawn 30+ wedged subprocesses across cascade dispatches (wave generation + compile-fix + audit-fix + reaudit), each individually under cap.

**Resolution:** Phase 5.7 ships `_cumulative_wedge_budget` on `RunState` (per-build counter, NOT per-wave). Every Claude SDK subprocess that is eligible for bootstrap respawn increments the counter when `bootstrap_idle_timeout_seconds` triggers: primary wave sessions, compile-fix sessions, audit-fix sessions, and re-audit sessions. Default cap: 10 wedges per build. When exceeded:
1. Logs `[BOOTSTRAP-WATCHDOG] Cumulative wedge cap (10) reached; halting build with environmental error`.
2. Marks current milestone FAILED with `failure_reason = "sdk_pipe_environment_unstable"`.
3. Run exits with EXIT_CODE=2 (environmental). Operator can resume after pipe stabilizes.

**Operator override:** `--cumulative-wedge-cap <N>` for builds with known-flaky environments. The landing memo must include a worst-case budget table for one milestone: 4 primary waves + up to 3 compile-fix attempts + up to 3 audit-fix cycles + reaudit sessions, and identify which of those actually used Claude SDK subprocesses in the implementation.

### M.M5 In-wave typecheck is a HINT, not a contract

**Question:** Architecture review #5 — Phase 5.6's in-wave mandate ("Wave D's prompt instructs Claude to run tsc before declaring done") is unverifiable. Claude can claim done without running it.

**Resolution:** **The prompt suffix is purely a hint, labeled clearly:**

> "(The wave validator runs the repository compile profile definitively after this session ends. You are encouraged but not required to run it inline.)"

The post-wave gate (§I.4 extended `run_wave_d_acceptance_test`) is the contract. If the post-wave compile profile fails, the wave fails — regardless of what Claude claimed. Phase 5.6's value is in the unified post-wave gate, not the in-wave mandate.

**Rationale:** Don't write a contract you can't verify. Eliminates the "Claude lied about running tsc" failure mode by not relying on the claim.

### M.M6 Bootstrap watchdog: 60s, cap=3, with diagnostics

**Question:** Architecture review #6 — 30s bootstrap deadline could be too tight for cold MCP server initialization (Playwright MCP, Context7 MCP, Gmail/Calendar MCP combined can plausibly push past 30s on cold worker).

**Resolution:**
* `bootstrap_idle_timeout_seconds: int = 60` (was 30). Absorbs cold MCP init.
* Per-wave respawn cap: 3 (was 2).
* New STATE.json field `_bootstrap_wedge_diagnostics` populated per-wave with respawn count + cumulative-wedge counter. Operators can see whether 60s/3 calibration is empirically wrong; Phase 6+ retunes data-driven.
* Cumulative-wedge global cap (M.M4): 10 per build.

### M.M7 Phase 5.8 is diagnostic-first

**Question:** Architecture review #7 — `cross_package_contract.py` (~250 lines) + Wave A prompt extension + Wave C validator + audit code = ~3 weeks of scope to solve what may be a Wave A spec-quality issue. The single M1 smoke's `STACK-IMPORT-002` is one data point; OpenAPI 3.1 `components.schemas` IS a JSON-flavored type contract.

**Resolution:** Phase 5.8 splits into two stages:

* **Phase 5.8a (diagnostic):** Ship Wave C diagnostics. Log every divergence between OpenAPI spec and generated TS client. Run sequential M1+M2 smokes: stop early on 3 correlated divergences, otherwise continue to 10 smokes before deciding against 5.8b. Measure: how many smokes hit `CONTRACT-DRIFT-001`-shape findings? What's the delta between Wave A's OpenAPI emission and Wave C's generated client?
* **Phase 5.8b (decision gate):** If diagnostics confirm OpenAPI is genuinely insufficient (e.g., 3 correlated divergences before or at the 10-smoke cap; Wave A consistently emits incomplete OpenAPI; Wave C consistently translates lossy), ship the parallel `CROSS_PACKAGE_CONTRACT.json`. If diagnostics show OpenAPI IS sufficient and Wave A's emission quality is the gap, instead invest in Wave A spec-quality (extend Wave A prompt to emit fully-fleshed OpenAPI; add Wave A.5 plan reviewer check for OpenAPI completeness).

**Rationale:** Don't over-engineer a parallel contract before measuring whether OpenAPI is actually insufficient. Phase 5.8a is ~3 days of work; the decision to proceed to 5.8b is data-driven.

### M.M8 Single anchor slot + `_quality.json` sidecar

**Question:** Architecture review #8 — Two slots (`_anchor/_complete/` + `_anchor/_degraded/`) forks Phase 4.6's prune logic. Cleaner: single slot, sidecar manifest.

**Resolution:** Phase 5.5 keeps `_anchor/_complete/` as the only slot. Phase 4.6's `_prune_anchor_chain` walks unchanged. New file `_anchor/_complete/_quality.json` (sibling to the captured tree):
```json
{
  "quality": "clean" | "degraded",
  "audit_status": "clean" | "degraded" | "failed" | "unknown",
  "unresolved_findings_count": int,
  "audit_debt_severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "",
  "audit_findings_path": "<absolute path>",
  "captured_at": "<ISO-8601>"
}
```

`_capture_milestone_anchor_on_complete` writes this file alongside the capture. `--retry-milestone <id>` reads `_quality.json` to inform the operator: "Restoring from milestone-1's last capture (quality=degraded; 28 findings, severity HIGH)". Single chain, single prune, operator-visible quality status.

**Rationale:** Phase 4.6's contract preserved byte-identical; quality information surfaces via sidecar instead of slot fork.

### M.M9 Phase 5.2 fixes ALL audit-dispatch sites + lint test

**Question:** Architecture review #9 — Phase 5.2 fixes one site (cli.py:5534-5535), but the bug class is broader. Already verified ANOTHER buggy site at cli.py:5037.

**Resolution:** Phase 5.2's first task is `grep -n "audit_dir=str\|requirements_path=str.*req_dir" src/agent_team_v15/cli.py` to enumerate ALL constructions. Each must be audited against canonical `req_dir / "milestones" / milestone.id / ...`. Confirmed broken sites at HEAD `2d49a0a`:
* `cli.py:5037` (architecture-gate-fail audit dispatch) — **NEW finding from review #9**
* `cli.py:5534-5535` (Phase 4.4 wave-fail audit dispatch) — original fix site

Phase 5.2 fixes both. **Lint test** `tests/test_audit_dispatch_path_construction.py::test_no_audit_dispatch_site_omits_milestones_segment` scans cli.py source for the broken pattern (`req_dir / milestone.id / ".agent-team"` without `"milestones"` between) — fails CI on any future regression. Locks the contract.

### M.M10 Hollow-recovery migration command

**Question:** Adversarial review #10 — Today's M1 + M2 are marked COMPLETE with N findings. After Phase 5 ships, new milestones go DEGRADED for the same condition; historical milestones keep stale "COMPLETE". No migration path.

**Resolution:** Phase 5.5 ships `agent-team-v15 rescan-quality-debt --cwd <run-dir>` cli command:
1. Loads existing STATE.json + AUDIT_REPORT.json (from canonical OR nested path — fallback for pre-Phase-5.2 runs).
2. Re-evaluates each completed milestone against the Quality Contract.
3. Updates `milestone_progress[id]` with `audit_status`, `unresolved_findings_count`, `audit_debt_severity`, `audit_findings_path` (Phase 5.3 fields).
4. Emits a report `QUALITY_DEBT_RESCAN.md` with per-milestone retroactive verdict. Doesn't change `status` (those stay COMPLETE for stability) but populates the debt fields so dashboards / consumers can see retroactive degradation.
5. Operator-overridable: `--rescan-overwrite-status` rewrites COMPLETE → DEGRADED for milestones that fail the Quality Contract retroactively (operator opts in, breaking change to STATE.json status enum).

**Rationale:** Migration debt is real; Phase 5 ships the migration.

### M.M11 Pre-Phase-5.6 calibration smoke

**Question:** Adversarial review #11 — Phase 5.6's tsc strict gate could spike DEGRADED rate to 30%+ on day one. Plan ships blind.

**Resolution:** Before Phase 5.6 lands, ship a **calibration smoke**:
1. Run M1+M2 with `tsc_strict_check_enabled=False` (existing behavior). Record findings + audit verdict.
2. Run M1+M2 with `tsc_strict_check_enabled=True` (new behavior; gate enforced). Record same.
3. Compare: how many milestones that passed at False fail at True? What's the wave-fail-rate delta?
4. For every False-pass/True-fail case, persist the exact compile-profile diagnostics, the tsconfig/package surfaces checked, and whether docker/Next passed on the same artifact. This proves the divergence source before the strict gate ships.

If delta is small (≤10% additional wave-fails), Phase 5.6 ships strict-default-on. If delta is >25%, Phase 5.6 ships strict-default-OFF with a 2-week opt-in period for operator data-collection; default flips after empirical convergence. If 10-25%, surface to user with the calibration data; user decides default.

**Rationale:** Don't break the production rate without measuring the cost. Phase 5.6 is the highest-blast-radius landing in Phase 5.

### M.M12 DEGRADED enum migration / consumer guidance

**Question:** Adversarial review #7 — `STATE.json::milestone_progress[].status` may have downstream consumers (CI/CD, dashboards) keyed on `"COMPLETE"`. Phase 5 introduces `"DEGRADED"` unconditionally.

**Resolution:**
* Phase 5.3 (data layer) ships the new fields with backward-compat defaults (existing JSON loads to `audit_status="unknown"`).
* Phase 5.5 (UX layer) ships a deprecation notice when first DEGRADED milestone lands: `[QUALITY-CONTRACT] Milestone X marked DEGRADED — this is a NEW status enum introduced in Phase 5. Downstream tooling reading milestone_progress[].status should handle DEGRADED in addition to COMPLETE/FAILED/IN_PROGRESS/PENDING. See docs/operator/phase-5-status-enum-migration.md`.
* New documentation file `docs/operator/phase-5-status-enum-migration.md` (Phase 5.5 ships it) with: enum semantics, downstream tooling guidance (e.g., "treat DEGRADED as 'shipped with debt' — separate from FAILED but not as good as COMPLETE"), JSON schema delta.
* Existing rolling fixtures that assume binary COMPLETE/FAILED enum get audited; any that match `"COMPLETE"` should match `"COMPLETE" | "DEGRADED"` (Phase 5.5 includes a fixture sweep).

### M.M13 Auditor-noise instrumentation

**Question:** Adversarial review #1 — Phase 5 makes the system depend MORE on audit accuracy. No spot-check on auditor false-positive rate.

**Resolution:**
* Phase 5.5 ships per-finding precision instrumentation. Each AUDIT_REPORT.json finding gains `confirmation_status` field on disk: `"unconfirmed" | "confirmed" | "rejected"`. Default `unconfirmed` at write-time.
* New cli command `agent-team-v15 confirm-findings --cwd <run-dir>` opens an interactive review where operator marks each finding confirmed/rejected. Updates STATE.json with confirmation rates per auditor.
* New persisted suppression registry at `.agent-team/audit_suppressions.json`. A suppression requires: finding code, `confirmation_status="rejected"` evidence, operator, reason, created_at, expires_at, and the exact auditor prompt/version that produced the false positive.
* Suppressions are applied during dispatch + Quality Contract evaluation only after the registry entry validates. CRITICAL findings cannot be suppressed unless a separate emergency flag is passed for that run; the flag logs a red warning and writes `emergency_critical_suppression=true` to STATE.json.
* Phase 5.5's smoke landing memo includes a manual-spot-check section: implementer agent samples 5 random findings from the smoke's AUDIT_REPORT and verifies each against actual code; documents precision.

**Rationale:** Don't ship a contract that depends on auditor accuracy without measuring auditor accuracy.

### M.M14 Phase 5.4 fix-regression rollback fixture

**Question:** Adversarial review #2 — fix-Claude could introduce new TS errors; the existing `_snapshot_files` helper only captures files named by current findings, cannot remove newly-created bad files, and can revert legitimate partial fixes in snapshotted files.

**Resolution:** Phase 5.4 fixture set extends with:
* `test_phase_5_4_cycle_1_fix_introduces_new_error_triggers_full_workspace_rollback`: synthetic — cycle 1 audit returns FAIL findings; fix-Claude (mocked) edits one finding file and creates one new file that introduces a new compile-profile diagnostic; post-fix diagnostic identity diff detects the new diagnostic; rollback restores edited files and removes created files; STATE.json reflects rollback.
* `test_phase_5_4_cycle_1_fix_partial_success_preserved_when_no_new_diagnostic`: synthetic — fix-Claude addresses 2/3 findings cleanly; 1 still fails; no new compile-profile diagnostic identity appears; loop keeps the good patches and continues to cycle 3 (or terminates per regression check).
* `test_phase_5_4_regression_identity_not_count_only`: synthetic — one old diagnostic disappears and one new diagnostic appears, leaving the same count; rollback still fires because diagnostic identity changed.

Implementation note: before fix dispatch, capture the full workspace diff metadata (modified, created, deleted files) and pre-fix compile-profile diagnostics. After fix dispatch, compare diagnostics by stable identity (`file`, `line`, `code`, normalized message). Count-only comparison is not sufficient.

These extend AC1-AC5 in §G.5.

### M.M15 `--legacy-permissive-audit` evidence-based sunset

**Question:** A calendar sunset ("Phase 6") is not meaningful when strict Quality Contract readiness depends on real milestone quality and auditor precision.

**Resolution:** `--legacy-permissive-audit` remains deprecated from day one, but removal is data-gated. The flag can be removed only after:
* 80%+ of live milestones land clean for 4 consecutive weeks or 4 consecutive approved smoke batches, whichever is more relevant to current release cadence.
* No active CRITICAL suppression exists in `.agent-team/audit_suppressions.json`.
* Median confirmed-finding precision remains ≥70% across the most recent 3+ smoke batches.
* The removal plan is announced in a landing memo with the exact historical runs used as evidence.

**Rationale:** Strict-by-default is mandatory for new runs; removal of the migration flag should follow observed readiness, not a phase label.

### M.M16 Other previously-resolved decisions (preserved from v1)

| Question | Resolution | Rationale |
|---|---|---|
| Should `_anchor/_complete/` be renamed for clarity? | **No** | Single slot kept; sidecar `_quality.json` per M.M8. |
| Should `audit_fix_rounds` be renamed? | **No** | Existing field name; deprecate in comment, increment from Phase 5.4. |
| Should compile-fix be deleted in Phase 5.6? | **No (transition shim)** | Keep as thin wrapper around unified gate during transition; remove in follow-up commit after smoke validates. |
| Should the Quality Contract apply to integration audit (`AUDIT_REPORT_INTEGRATION.json`)? | **No** | Integration audit is advisory; per-milestone audit is gating. |
| Should Phase 5 add per-role model routing (compile-fix → Opus 4.7)? | **No (Phase 6+)** | Out of Phase 5 scope. |
| Should Phase 5 add deterministic-build harness (temp=0, seed-locked)? | **No (Phase 6+)** | Separate research thread. |
| Should `score_healthy_threshold` default change in Phase 5.1? | **No (default stays 90)** | The threshold is correct as a percentage; the comparison was wrong. |
| Should AUDIT_REPORT.json schema change for Phase 5? | **Minimally** (new `confirmation_status` per finding per M.M13; new `_quality.json` sidecar per M.M8) | Schema deltas are additive. |
| Should Phase 5.4's cycle-1 dispatch change `max_reaudit_cycles` semantics? | **No** | Cycle counts unchanged; just allow dispatch on cycle 1. |

---

## Section N — Out of scope (explicit non-goals)

* **Phase 5 does NOT add new audit-team auditors.** Today's 6 auditors (requirements, technical, interface, test, mcp_library, comprehensive) are sufficient for the Quality Contract. Adding new auditors is Phase 6+.
* **Phase 5 does NOT change Codex's wave dispatch path.** Wave B's Codex appserver flow is byte-identical.
* **Phase 5 does NOT add multi-stack-profile support** (Java, Python, Go, mobile). Phase 6+.
* **Phase 5 does NOT change PRD decomposition strategy** — only the AC-count cap. Vertical-slice remains the planner mode.
* **Phase 5 does NOT redesign parallel-isolation / git-worktree milestone execution.** Narrow exception: Phase 5.5 migrates the parallel terminal `update_milestone_progress` write at `cli.py:4871` through the Quality Contract resolver so it cannot bypass completion gating. Scheduling, worktree isolation, and merge behavior remain out of scope.
* **Phase 5 does NOT add LLM determinism** (temperature=0, seeded sampling). Phase 6+.
* **Phase 5 does NOT add operator-review checkpoints for DEGRADED milestones.** That's a UX choice for Phase 6+.
* **Phase 5 does NOT change Phase 4 anchor / lock / hook / wave-awareness primitives.** Those are load-bearing — Phase 5 layers on top.

---

## Section O — Smoke validation plan

### O.1 Per-phase smoke commitment

| Phase | Fixture-only | Live smoke required |
|---|---|---|
| 5.1 | ✅ | No (replay sufficient) |
| 5.2 | ✅ | YES — M1 smoke; prove audit-team Claude targets canonical path |
| 5.3 | ✅ | No |
| 5.4 | ⚠ partial | YES — M1 smoke; observe `audit_fix_rounds > 0` |
| 5.5 | ⚠ partial | YES — M1+M2 smoke; observe `_anchor/_complete/` only on clean COMPLETE |
| 5.6 | ⚠ partial | YES — M1 smoke; observe wave-D acceptance running BOTH tsc + docker |
| 5.7 | ⚠ partial | YES — M1 smoke; inject artificial bootstrap wedge + productive-tool idle replay |
| 5.8 | ⚠ partial | YES — sequential M1+M2 diagnostic smokes; stop at 3 correlated divergences or 10-smoke cap |
| 5.9 | ⚠ partial | YES — M1+M2 smoke + 6-milestone synthetic |

### O.2 Acceptance metrics (Quality Contract enforcement)

After Phase 5 fully landed:

* Q1: ≥80% of milestones land `audit_status="clean"`. ≤15% degraded. ≤5% failed.
* Q2: median `audit_fix_rounds ≥ 1` per milestone (proves audit-fix actually runs).
* Q3: 0 hidden TS errors at COMPLETE; 0 hidden audit findings at COMPLETE (Quality Contract gates 2-3).
* Q4: median ≤45 min cycle time per foundation milestone (M1/M2); ≤60 min per feature milestone.
* Q5: median ≤$8 cost per milestone with budget caps.
* Q6: every DEGRADED milestone has STATE.json debt fields populated.
* Q7: 0 hollow recoveries (`failure_reason="wave_fail_recovered"` AND `audit_fix_rounds=0`). Today: 100% hollow.

### O.3 Frozen smoke fixture for Phase 5

Create `tests/fixtures/smoke_2026_04_28/` (mirroring `smoke_2026_04_26/` for Phase 4 fixtures):
* Copy from `v18 test runs/m1-hardening-smoke-20260428-112339/`:
  * `.agent-team/STATE.json`
  * `.agent-team/milestone-1/.agent-team/AUDIT_REPORT.json` (the nested-path version — evidence of R-#36)
  * `.agent-team/milestones/milestone-1/WAVE_FINDINGS.json`
  * `.agent-team/milestones/milestone-1/REQUIREMENTS.md`
  * `.agent-team/MASTER_PLAN.md`
  * `.agent-team/hang_reports/wave-D-20260428T081835Z.json` (evidence of R-#41)

Phase 5.1 / 5.2 fixtures replay against this fixture. Phase 5.3 / 5.4 / 5.5 fixtures may use synthetic state-files.

### O.4 Final-smoke evidence checklist (post-2026-04-29 follow-up patches)

The final Phase 5 smoke (post-Phase-5.5 + 5.6 land) must produce on-disk
evidence for every entry below. Each row maps to a follow-up patch landed
between Phase 5.3 + Phase 5.4 (commits in the pre-Phase-5.4 patch set
shipping after the 2026-04-28 Wave 1 closeout smoke). Reviewers cite
these artifacts directly when accepting / rejecting the smoke.

Append-only — every future Phase 5.<N> follow-up patch that adds a live-
verifiable contract appends a new row here.

| # | Pre-Phase-5.4 patch | Live-evidence shape on disk | Where to find it |
|---|---|---|---|
| O.4.1 | **Audit-output guard active + decision-log produced** (R-#47 follow-up) | Non-empty JSONL file per active audit dispatch; every entry has `ts`, `tool`, `file_path`, `decision` ∈ {`allow`,`deny`}, `reason`. At least one `allow` entry per auditor (cycle 1: 6 auditors → ≥ 6 allow rows on `audit-<name>_findings.json`). At least one `deny` entry per smoke (any drift from the live filename envelope). | `<run-dir>/.agent-team/milestones/<id>/.agent-team/audit_output_guard_decisions.jsonl` (per per-milestone audit dispatch); `<run-dir>/.agent-team/_integration_staging/audit_output_guard_decisions.jsonl` IF the integration audit fired (deleted post-rename — capture before the cleanup or skip if integration audit dispatched; canonical audit dispatches are sufficient evidence). |
| O.4.2 | **No raw-score `%` leak** (R-#33/R-#34 display follow-up) | `BUILD_LOG.txt` does NOT contain any line of shape `score=N%` where `N > 100` or `N` is the raw 1000-scale value (e.g., `score=512%` or `score=295%`). All audit-cycle log lines use the explicit `<raw>/<max> (<pct>%)` format. | `grep -E 'score=[0-9]{4,}\.0%\|score=[0-9]{3,}\.0%' BUILD_LOG.txt` returns 0 hits for raw 1000-scale values; `grep -E 'score=[0-9]+/[0-9]+ \([0-9]+\.[0-9]+%\)' BUILD_LOG.txt` returns ≥ 1 hit per audit-cycle. |
| O.4.3 | **No COMPLETE on final FAIL + HIGH/CRITICAL** (cascade quality gate) | When the cascade fires (`failure_reason=wave_fail_recovery_attempt` then `wave_fail_recovered`) the milestone's final `AUDIT_REPORT.json` has `extras.verdict != "FAIL"` AND `score.critical_count == 0` AND `score.high_count == 0`. If any of those fails, the milestone MUST be FAILED with `failure_reason="audit_fix_recovered_build_but_findings_remain"`. The 2026-04-28 smoke shape (5 CRITICAL + 8 HIGH + verdict=FAIL → COMPLETE) must NOT recur. | `STATE.json::milestone_progress[<id>].status` + `STATE.json::milestone_progress[<id>].failure_reason` cross-checked against `<run-dir>/.agent-team/milestones/<id>/.agent-team/AUDIT_REPORT.json` `extras.verdict` + `score.{critical,high}_count`. |
| O.4.4 | **Root integration report not confused with per-milestone gating report** (R-#36 follow-up) | `<run-dir>/.agent-team/AUDIT_REPORT.json` does NOT exist post-run. `<run-dir>/.agent-team/AUDIT_REPORT_INTEGRATION.json` exists IF the integration audit fired. Per-milestone gating reports live at `<run-dir>/.agent-team/milestones/<id>/.agent-team/AUDIT_REPORT.json`. The `<run-dir>/.agent-team/_integration_staging/` directory does NOT exist post-run (cleaned up). | `find <run-dir>/.agent-team -maxdepth 1 -name 'AUDIT_REPORT.json'` returns nothing; `find <run-dir>/.agent-team -maxdepth 1 -name 'AUDIT_REPORT_INTEGRATION.json'` returns the canonical integration path; `find <run-dir>/.agent-team -maxdepth 1 -name '_integration_staging' -type d` returns nothing. |
| O.4.5 | **AC4 — bootstrap-wedge respawn observed on real Claude SDK dispatch** (Phase 5.7 R-#41) | At least one `<run-dir>/.agent-team/hang_reports/wave-<X>-<ts>.json` exists with `timeout_kind=="bootstrap"`, AND `BUILD_LOG.txt` carries a corresponding respawn log line in one of three path-specific shapes: (a) **sub-agent path** (`_invoke_sdk_sub_agent_with_watchdog` — compile-fix / audit-fix / audit / re-audit): `[Wave X] role <R>: bootstrap-wedge respawn N/3 (cumulative wedges so far=M); spawning fresh subprocess`; (b) **direct-SDK wave path** (`_invoke_wave_sdk_with_watchdog` — Claude wave A/T/E/Scaffold): `[Wave X] bootstrap-wedge respawn N/3 (cumulative wedges so far=M); spawning fresh subprocess`; (c) **provider-routed Claude path** (`_invoke_provider_wave_with_watchdog` with `bootstrap_eligible=True` — Wave B/D when `provider_map_b/d='claude'` is operator-set): `[Wave X] (provider) bootstrap-wedge respawn N/3 (cumulative wedges so far=M); spawning fresh dispatch`. The respawn attempt completes — the wedge does NOT escalate to wave-fail at the first occurrence. Bootstrap-eligible paths are direct-SDK (`ClaudeSDKClient` in-process); the team-mode opaque `claude --print` subprocess is bootstrap-EXEMPT (cli.py flips `bootstrap_cleared=True` before `execute_prompt`). Smoke must inject the wedge into a bootstrap-eligible path — typical injection: monkeypatch the Claude SDK callback to await >60s on first call, or run with limited Anthropic API capacity to induce the SDK pipe handshake stall. | `BUILD_LOG.txt` grep `-E 'bootstrap-wedge respawn [0-9]+/[0-9]+'` matches any of the three shapes; `<run-dir>/.agent-team/hang_reports/wave-<X>-<ts>.json` JSON parse: `payload.timeout_kind=="bootstrap"`, `payload.role` ∈ {`compile_fix`,`audit_fix`,`audit`,`wave`}, `payload.cumulative_wedges_so_far` populated, `payload.bootstrap_deadline_seconds==60`. |
| O.4.6 | **AC10 — productive-tool-idle fires at 1200s on M3 replay** (Phase 5.7 R-#45) | Replay BUILD_LOG `2088-2148` shape (`m1-hardening-smoke-20260428-112339`): one `commandExecution` start/complete + ≥4920s of `item/agentMessage/delta`. Hang report carries `timeout_kind=="tool-call-idle"`, `tool_call_idle_timeout_seconds==1200`, `tool_call_event_count >= 1`, `last_productive_tool_name=="commandExecution"`. Wave-fail fires BEFORE `codex_timeout_seconds=5400` is reached (timestamp diff between `started_at` and `watchdog_fired_at` is ≈1200s, not ≈5400s). | `<run-dir>/.agent-team/hang_reports/wave-B-<ts>.json` JSON parse against the schema above; `BUILD_LOG.txt` grep `tool-call-idle`. |
| O.4.7 | **stderr_tail field present on every hang report; populates only for observer-wired subprocess dispatches** (Phase 5.7 §J.3) | The `stderr_tail` field is ALWAYS emitted by `_write_hang_report` (default `""`) and bounded at 4096 characters. NON-EMPTY content is only possible when the dispatch path goes through `agent_teams_backend.execute_prompt` AND the caller wires a `stderr_observer` (today: `cli.py:_execute_single_wave_sdk` team-mode branch threads `state.update_stderr_tail`). **Bootstrap-eligible paths are direct-SDK `ClaudeSDKClient` (in-process Anthropic SDK over stdin/stdout/stderr of the Python process itself) — they have NO subprocess stderr to capture.** Bootstrap-wedge hang reports on those paths SHOULD have `stderr_tail==""`; that is the as-shipped contract (a known gap closeable in Phase 6+ via `--output-format stream-json` for team-mode + stream parsing). For the team-mode opaque path (which IS observer-wired but is bootstrap-EXEMPT per Blocker 1), `stderr_tail` populates on tier-2/3/4 wedges — those are the smoke's primary opportunity to verify the observer wiring end-to-end. Smoke acceptance: field must be present, ≤4096 chars, and at least one TEAM-MODE wedge hang report (any non-bootstrap `timeout_kind`) carries non-empty stderr_tail when the smoke induces a real claude --print subprocess wedge. | `<run-dir>/.agent-team/hang_reports/*.json` JSON parse: every payload has key `stderr_tail` (string) AND `len(payload.stderr_tail) <= 4096`. For team-mode wedges (where `payload.role=="wave"` AND `payload.timeout_kind in {"orphan-tool","tool-call-idle","wave-idle"}`), at least one is non-empty when the smoke includes a real subprocess wedge. |
| O.4.8 | **Cumulative cap halts build with `sdk_pipe_environment_unstable` + EXIT 2** (Phase 5.7 §M.M4) | An induced pathological-environment smoke (e.g. `--cumulative-wedge-cap 2` + injected pipe-pauses on every dispatch) reaches the cap on the Nth wedge. STATE.json then shows `milestone_progress[<id>].status=="FAILED"` AND `milestone_progress[<id>].failure_reason=="sdk_pipe_environment_unstable"` AND `_cumulative_wedge_budget` equals the cap. `EXIT_CODE.txt` contains `2`. `BUILD_LOG.txt` carries `[BOOTSTRAP-WATCHDOG] Cumulative wedge cap (...) reached (count=...); halting build with environmental error.` | `<run-dir>/.agent-team/STATE.json` JSON parse; `<run-dir>/EXIT_CODE.txt` exact match `2`; `BUILD_LOG.txt` grep `Cumulative wedge cap`. |
| O.4.9 | **No retry-budget increment on bootstrap respawn** (Phase 5.7 §J.3 #1) | Across a smoke that exercises at least one bootstrap respawn (per O.4.5), the outer wave's retry counter (`Wave X retry N/M` lines in BUILD_LOG) does NOT increment as a result of the respawn. Counter increments are reserved for wave-level acceptance failures, not subprocess respawn. | `BUILD_LOG.txt` grep `Wave .* retry [0-9]/[0-9]` — the count does not jump in lockstep with `bootstrap-wedge respawn` lines. |
| O.4.10 | **Provider-routed Codex does NOT increment cumulative wedge counter** (Phase 5.7 §M.M4 + Blocker 2 scoping) | When Codex Wave B/D wedges occur (e.g. environment-induced appserver delay), `<run-dir>/.agent-team/STATE.json::_cumulative_wedge_budget` does NOT increment. The Codex path produces its own diagnostics (`hang_reports/...timeout_kind` may be `tool-call-idle` or `wave-idle` for Codex) but Claude SDK bootstrap respawn is structurally inapplicable on these paths. | `<run-dir>/.agent-team/STATE.json` `_cumulative_wedge_budget` value tracks Claude-SDK-only wedge events; cross-check against Codex-path hang reports (where present) to confirm no double counting. |
| O.4.11 | **Sub-agent compile/audit/reaudit bootstrap eligibility coverage** (Phase 5.7 R-#41) | Hang reports for at least one `role=compile_fix` AND/OR `role=audit_fix` AND/OR `role=audit` (re-audit) Claude SDK dispatch surface `timeout_kind=="bootstrap"` when those dispatches are stillborn. Demonstrates that all four §M.M4 subprocess classes — primary wave (`role=="wave"`), compile-fix (`role=="compile_fix"`), audit-fix (`role=="audit_fix"`), re-audit (`role=="audit"`) — are bootstrap-eligible end-to-end. The `payload.role` field is emitted unconditionally by `_write_hang_report` (Phase 5.7 reviewer-correction patch); group via this field. | `<run-dir>/.agent-team/hang_reports/*.json` parsed and grouped by `payload.role`: at least one `payload.timeout_kind=="bootstrap"` entry per `role` ∈ {`compile_fix`,`audit_fix`,`audit`} observed across a smoke batch that injects bootstrap wedges into each Claude SDK sub-agent dispatch class (e.g. by monkeypatching the Claude SDK callback to stall on first call for each role). |
| O.4.12 | **Phase 5.8a per-milestone PHASE_5_8A_DIAGNOSTIC.json artifact** (Phase 5.8a §K.1 + scope check-in correction #3) | Each milestone whose Wave C ran the canonical openapi-ts client path (`client_generator=="openapi-ts"`) produces `<run-dir>/.agent-team/milestones/<id>/PHASE_5_8A_DIAGNOSTIC.json` with the locked schema (per `tests/test_cross_package_contract_diagnostics.py::test_phase_5_8a_diagnostic_json_schema_locked`): top-level keys `phase=="5.8a"`, `milestone_id`, `smoke_id`, `generated_at` (ISO-8601), `metrics.{schemas_in_spec, exports_in_client, divergences_detected_total, unique_divergence_classes, divergences_correlated_with_compile_failures}`, `divergences[]` (each with the 8-key record), `unsupported_polymorphic_schemas[]`, `tooling.{ts_parser, ts_parser_version, error}`. The file is at the per-milestone path (NOT the run-root) so M1 + M2 do NOT collide. | `find <run-dir>/.agent-team/milestones -name PHASE_5_8A_DIAGNOSTIC.json` returns one path per milestone whose Wave C succeeded; `jq` parses each + verifies `phase == "5.8a"` + the schema lock; `find <run-dir>/.agent-team -maxdepth 2 -name PHASE_5_8A_DIAGNOSTIC.json` does NOT match any root-level file. |
| O.4.13 | **`[CROSS-PACKAGE-DIAG]` aggregate log line emitted at end-of-Wave-C** (Phase 5.8a §K.1 AC7) | Each Wave C run that took the canonical openapi-ts path produces exactly one `[CROSS-PACKAGE-DIAG]` log line per milestone in `BUILD_LOG.txt`, even when the diagnostic finds zero divergences. Two shapes accepted: (a) success — `[CROSS-PACKAGE-DIAG] milestone=<id> N divergence(s) detected (classes: <list>) [advisory; non-blocking]`; (b) tooling-unavailable — `[CROSS-PACKAGE-DIAG] milestone=<id> parser=<name> tooling_error=<reason>... — diagnostic skipped, no findings emitted`. The log fires regardless of divergence count so operators see the diagnostic step ran. | `grep '\[CROSS-PACKAGE-DIAG\]' BUILD_LOG.txt` returns ≥1 line per milestone whose Wave C ran openapi-ts canonical path; each line carries `milestone=<id>`. |
| O.4.14 | **Phase 5.8a §K.2 decision-gate evidence — 3 correlated divergences across distinct DTOs** (Phase 5.8a §K.2 stop-early predicate) | Across the operator-authorised sequential M1+M2 smoke batch (≤10 smokes), the K.2 evaluator collects every `PHASE_5_8A_DIAGNOSTIC.json` and applies `cross_package_diagnostic.k2_decision_gate_satisfied`: at least 3 distinct `(divergence_class, schema_name)` pairs share the SAME `divergence_class` across the batch ⇒ Phase 5.8b ships; otherwise close R-#42 by Wave A spec-quality investment. The predicate semantic is locked at the source level by `test_k2_decision_gate_satisfied_3_distinct_dtos_same_class` + `test_k2_decision_gate_NOT_satisfied_3_props_one_dto_same_class` + `test_k2_decision_gate_NOT_satisfied_3_distinct_dtos_different_classes`. The aggregator + decision write-up live in a separate `PHASE_5_8A_DIAGNOSTIC_SUMMARY.md` artifact authored by the K.2 evaluator session (NOT shipped by the Phase 5.8a source patch). | Aggregate CSV/JSON of `(smoke_run_id, milestone_id, divergence_class, schema_name)` from every `PHASE_5_8A_DIAGNOSTIC.json` in the smoke batch; pass each smoke's diagnostics list to `k2_decision_gate_satisfied(per_milestone_diagnostics, correlated_threshold=3)`; outcome (`True` / `False`) drives the decision. Smoke batch's `PHASE_5_8A_DIAGNOSTIC_SUMMARY.md` records the outcome + evidence rows. |

Each follow-up patch SHIPS WITH a fixture or unit test that proves the
contract at the code level; the live-smoke evidence above is the
end-to-end seal. Smoke acceptance requires every checklist row to verify.

---

## Section P — Risk register lookup (full)

| ID | One-liner | Closed by | Status |
|---|---|---|---|
| R-#33 | should_terminate_reaudit raw-vs-pct | Phase 5.1 | OPEN |
| R-#34 | AuditScore.from_json zeros counters | Phase 5.1 | OPEN |
| R-#35 | Cycle-1 fix-dispatch blocked | Phase 5.4 | OPEN |
| R-#36 | Audit-team prompt path drift | Phase 5.2 | OPEN |
| R-#37 | audit_fix_rounds dead-data | Phase 5.3 + 5.4 | OPEN |
| R-#38 | No quality-debt fields on STATE.json | Phase 5.3 + 5.5 | OPEN |
| R-#39 | tsc-vs-docker divergence | Phase 5.6 | OPEN |
| R-#40 | Compile-fix has no Phase 4.2 retry feedback | Phase 5.6 | OPEN |
| R-#41 | No bootstrap watchdog | Phase 5.7 | OPEN |
| R-#42 | Cross-package type contract implicit | Phase 5.8 | OPEN |
| R-#43 | M1 has 15 ACs (no auto-split) | Phase 5.9 | OPEN |
| R-#44 | Build-check scope divergence (wave-scope per-service vs project-scope all-services Docker build) | Phase 5.6 | OPEN |
| R-#45 | Codex productive-tool idle wedge | Phase 5.7 | OPEN |
| R-#46 | Audit subagent definitions built but not injected into SDK options | Phase 5.2 | OPEN |
| R-#47 | Audit-* subagents lack Write tool and audit-output write scope | Phase 5.2 | OPEN |

---

## Section Q — File-level reference index (verified at HEAD `2d49a0a`)

| Citation | Description |
|---|---|
| `src/agent_team_v15/audit_team.py:99-140` | `should_terminate_reaudit` (R-#33) |
| `src/agent_team_v15/audit_team.py:111` | The buggy raw-vs-pct comparison |
| `src/agent_team_v15/audit_models.py:571-584` | `AuditScore.from_dict` trusts scorer-supplied zero severity counters (canonical smoke branch; R-#34) |
| `src/agent_team_v15/audit_models.py:727-754` | `AuditReport.from_json` score parsing branches (dict + flat; Phase 5.1 normalizer applies after both) |
| `src/agent_team_v15/audit_models.py:506-552` | `AuditScore.compute` (canonical compute path) |
| `src/agent_team_v15/cli.py:5037` | **Buggy path construction #1** — architecture-gate-fail audit_dir omits "milestones" (R-#36; Phase 5.2 fix site #1) |
| `src/agent_team_v15/cli.py:5520-5547` | Phase 4.4 wave-fail audit dispatch (R-#36 surface) |
| `src/agent_team_v15/cli.py:5534-5535` | **Buggy path construction #2** — wave-fail requirements_path + audit_dir omit "milestones" (Phase 5.2 fix site #2) |
| `src/agent_team_v15/cli.py:1254` | Correct path construction (reference for Phase 5.2 fix) |
| `src/agent_team_v15/cli.py:2280` | Correct natural-completion audit_dir construction (reference) |
| `src/agent_team_v15/cli.py:605-724` | `_build_options` builds `ClaudeAgentOptions.agents`; v5 extends with explicit audit-agent override (R-#46) |
| `src/agent_team_v15/cli.py:6692-6702` | Final integration audit calls `_run_milestone_audit`; covered by the same audit-agent injection fix (R-#46) |
| `src/agent_team_v15/cli.py:6914-6954` | `_run_milestone_audit` builds audit-specific agent definitions but discarded them before v5 (R-#46) |
| `src/agent_team_v15/cli.py:4871` | Parallel group variable-status writeback (`final_status` can be COMPLETE; Phase 5.5 resolver migration includes this narrow exception) |
| `src/agent_team_v15/cli.py:5023, 5444, 5932, 6052, 6067, 6175, 6207, 6334, 6449, 8757` | Literal + variable terminal `update_milestone_progress` writeback sites (R-#38 surface; Phase 5.5 single-resolver helper consolidates COMPLETE/DEGRADED paths) |
| `src/agent_team_v15/cli.py:6967` | `report_path = Path(audit_dir) / "AUDIT_REPORT.json"` (consumer) |
| `src/agent_team_v15/cli.py:8114` | `if _use_team_mode and (Path(audit_dir) / "AUDIT_REPORT.json").is_file():` (consumer) |
| `src/agent_team_v15/cli.py:8374` | H4 resume guard `report_path = Path(audit_dir) / "AUDIT_REPORT.json"` (verified line) |
| `src/agent_team_v15/cli.py:8472` | `for cycle in range(start_cycle, max_cycles + 1)` (R-#35) |
| `src/agent_team_v15/cli.py:8477` | `if cycle > 1 and current_report:` (the cycle-gate bug) |
| `src/agent_team_v15/cli.py:8503` | `_run_audit_fix_unified` invocation site |
| `src/agent_team_v15/cli.py:8640` | Second `should_terminate_reaudit` call site |
| `src/agent_team_v15/cli.py:8313` | `_run_audit_loop` signature |
| `src/agent_team_v15/cli.py:7546` | `_run_audit_fix_unified` signature |
| `src/agent_team_v15/cli.py:7581-7600` | Phase 4.5 conditional Risk #1 lift gate |
| `src/agent_team_v15/cli.py:1158, 1293, 1350` | `should_terminate_reaudit` callers (each passes `healthy_threshold=config.audit_team.score_healthy_threshold`) |
| `src/agent_team_v15/state.py:62` | `audit_fix_rounds` definition (dead-data) |
| `src/agent_team_v15/state.py:33` | `convergence_cycles` definition |
| `src/agent_team_v15/state.py:743, 772` | `load_state` `_expect` shims (Phase 5.3 mirror site) |
| `src/agent_team_v15/wave_executor.py:5798` | `_run_wave_compile` (R-#39) |
| `src/agent_team_v15/wave_executor.py:5979` | `_build_compile_fix_prompt` (R-#40) |
| `src/agent_team_v15/wave_executor.py:481+` | `_WaveWatchdogState` (R-#41 base) |
| `src/agent_team_v15/wave_executor.py:480-545` | `_WaveWatchdogState.record_progress` updates generic progress without a separate productive-tool timestamp (R-#45) |
| `src/agent_team_v15/wave_executor.py:3651-3693` | Existing wave/orphan idle timeout builder keyed from generic `last_progress_monotonic` (R-#45) |
| `src/agent_team_v15/wave_executor.py:4167-4275` | Provider/Codex watchdog poll loop that must evaluate productive-tool idle (R-#45) |
| `src/agent_team_v15/codex_appserver.py:1328-1357` | Codex app-server progress taxonomy: item lifecycle vs agentMessage deltas (R-#45) |
| `src/agent_team_v15/codex_transport.py:356-385` | Codex CLI JSONL progress extraction for item.started/completed events (R-#45) |
| `src/agent_team_v15/wave_executor.py:8023, 8090, 8221, 8245` | Wave B/D self-verify gates (Phase 4.1 wiring; Phase 5.6 extends) |
| `src/agent_team_v15/audit_team.py:397-427` | Audit subagent definitions: audit keys, per-auditor tool lists, scorer Write baseline (R-#46/R-#47) |
| `src/agent_team_v15/audit_fix_path_guard.py:103-110` | Existing audit-fix guard no-ops without `AGENT_TEAM_FINDING_ID`; insufficient for normal audit Write (R-#47) |
| `src/agent_team_v15/agent_teams_backend.py:457-570` | PreToolUse hook writer; reference point if v5 implements audit-output write scope via hook (R-#47) |
| `src/agent_team_v15/runtime_verification.py:269-329` | `docker_build(..., services=None)` project-scope all-services build vs `services=[...]` wave-scope build args (R-#44) |
| `src/agent_team_v15/runtime_verification.py:968` | runtime verification project-scope all-services Docker build call |
| `src/agent_team_v15/runtime_verification.py:1270` | fix-loop project-scope all-services Docker build call |
| `src/agent_team_v15/wave_d_self_verify.py:135-220` | `run_wave_d_acceptance_test` (R-#39) |
| `src/agent_team_v15/wave_d_self_verify.py:188` | compose-file detection inside acceptance test |
| `src/agent_team_v15/wave_d_self_verify.py:225-235` | Wave D wave-scope per-service Docker diagnostic call shape (R-#44) |
| `src/agent_team_v15/compile_profiles.py:236-315` | Existing TypeScript compile profile discovery for frontend/generated/shared surfaces (Phase 5.6 reuses this) |
| `src/agent_team_v15/compile_profiles.py:512-604` | `run_wave_compile_check` execution/parsing primitive reused by unified Wave B/D acceptance |
| `src/agent_team_v15/wave_b_self_verify.py:run_wave_b_acceptance_test` | Wave B mirror (Phase 5.6 also touches) |
| `src/agent_team_v15/wave_b_self_verify.py:317-327` | Wave B wave-scope per-service Docker diagnostic call shape (R-#44) |
| `src/agent_team_v15/endpoint_prober.py:812` | endpoint-prober startup project-scope all-services Docker build call (R-#44; no `services` arg) |
| `src/agent_team_v15/endpoint_prober.py:848` | endpoint-prober recovery project-scope all-services Docker build call (R-#44; no `services` arg) |
| `src/agent_team_v15/agents.py:8763` | `build_wave_b_prompt` (Phase 5.6 prompt hint, NOT contract — see §M.M5) |
| `src/agent_team_v15/agents.py:9688` | `build_wave_d_prompt` (Phase 5.6 prompt hint, NOT contract — see §M.M5) |
| `v18 test runs/m1-hardening-smoke-20260428-112339/BUILD_LOG.txt:995-1003` | M2 narrow-pass / project-scope all-services build-fail evidence (R-#44) |
| `v18 test runs/m1-hardening-smoke-20260428-112339/BUILD_LOG.txt:348-350, 1279-1283, 1760-1764` | Audit subagent registration + Write-tool evidence (R-#46/R-#47) |
| `v18 test runs/m1-hardening-smoke-20260428-112339/BUILD_LOG.txt:2088-2148` | M3 productive-tool idle evidence: `commandExecution` age grows to 4920s (R-#45) |
| `v18 test runs/m1-hardening-smoke-20260428-112339/.agent-team/milestone-2/.agent-team/AUDIT_REPORT.json` | M2 nested path + score-shape variance (`max_score=0`, empty `by_severity`, zero counters with 4 CRITICAL findings; R-#33/R-#34/R-#36) |
| `src/agent_team_v15/audit_models.py:529` | `AuditScore.compute` canonical compute path (`score = (passed*100 + partial*50) / total`) |
| `src/agent_team_v15/audit_models.py:551` | `max_score=100` canonical compute return |
| `src/agent_team_v15/audit_models.py:577` | `critical_count=data["critical_count"]` dict-score trust site (canonical Phase 5.1 fix site) |
| `src/agent_team_v15/audit_models.py:746` | `critical_count=0` flat-score fallback zeroing (secondary Phase 5.1 fix site) |
| `src/agent_team_v15/config.py:552` | `score_healthy_threshold: float = 90.0` (verified line) |
| `src/agent_team_v15/config.py:711-712` | Validation: `score_healthy_threshold must be 0-100` (semantic confirmation = percentage) |
| `src/agent_team_v15/config.py:1118` | `recovery_wave_redispatch_enabled: bool = False` (NOT the audit-fix gate; clarified — see §A.2 misattribution note) |
| `src/agent_team_v15/agent_teams_backend.py` | claude --print subprocess dispatch (Phase 5.7 stderr capture) |
| `src/agent_team_v15/openapi_generator.py` | Wave C generation (Phase 5.8 contract validation OR diagnostic-first per §M.M7) |
| `src/agent_team_v15/wave_executor.py:1842, 1851` | `_plan_wave_redispatch` + `_recovery_wave_redispatch_enabled` gate (DIFFERENT mechanism from audit-fix; documented for future-maintainer disambiguation) |

---

## Section R — Phase 4 → Phase 5 reading order for implementer agents

Each Phase 5.<N> implementer must read in this order BEFORE writing any code:

1. This plan top-to-bottom (Section 0 first).
2. The Phase 4 plan: `docs/plans/2026-04-26-pipeline-upgrade-phase4.md` (Section 0 + the relevant phase brief — e.g., Phase 5.6 reader needs Phase 4.1's brief on per-wave self-verify).
3. The relevant Phase 4 landing memo:
   * Phase 5.1 / 5.2 / 5.3 / 5.4 / 5.5 readers: `phase_4_5_landing.md` + `phase_4_6_landing.md`
   * Phase 5.6 readers: `phase_4_1_landing.md` + `phase_4_2_landing.md`
   * Phase 5.7 readers: `phase_4_2_landing.md`
   * Phase 5.8 readers: `phase_4_3_landing.md` + `phase_4_7_landing.md`
4. The 2026-04-28 smoke landing memo (when written).
5. The targeted slice + wide-net commands (§0.5, §0.6) — must run green before any change.

---

---

## Section S — Cross-cutting concerns (v5 reconciled)

These items don't fit cleanly into a single sub-phase brief but cut across multiple phases. Implementer agents reading any sub-phase must also consult §S.

### S.1 Auditor signal-to-noise instrumentation (per §M.M13)

Phase 5 elevates audit findings from advisory → gating. Adversarial review #1 flagged that auditor accuracy was never measured.

**Per-phase wiring:**
* **Phase 5.5 ships:** `confirmation_status` field on each `AuditFinding` (default `"unconfirmed"`); `agent-team-v15 confirm-findings` cli command for interactive operator review; `.agent-team/audit_suppressions.json` registry for confirmed false positives. No ad hoc per-run ignore bypass.
* **Phase 5.5 landing memo SHALL include:** manual spot-check section. Implementer samples 5 random findings from the smoke's AUDIT_REPORT.json and verifies each against actual code; documents auditor precision per type. If precision < 70%, surface as halt and re-evaluate Quality Contract gate severity threshold.
* **Phase 5.4 implementer:** during the live smoke validating cycle-1 fix dispatch, capture auditor noise stats. If audit-fix dispatches against a finding that turns out false-positive (i.e., the fix-Claude declines to dispatch with `skip_reason="finding_not_actionable"`), increment `auditor_false_positive_count` on RunState.

**Acceptance metric:** Phase 5 acceptance gate adds Q8: median auditor precision ≥ 70% across confirmed-finding samples (computed from `confirm-findings` runs across 3+ smokes).

### S.2 Fix-regression rollback (per §M.M14)

Phase 5.4 promotes cycle-1 fix dispatch. Adversarial review #2 surfaced that bad fixes can introduce regressions.

**Phase 5.4 fixture additions:**
* `test_phase_5_4_cycle_1_fix_introduces_new_error_triggers_full_workspace_rollback`
* `test_phase_5_4_cycle_1_fix_partial_success_preserved_when_no_new_diagnostic`
* `test_phase_5_4_regression_identity_not_count_only`

**Phase 5.4 in-loop check:** before fix dispatch, capture the full workspace diff state plus compile-profile diagnostic identities. After fix dispatch + before next-cycle audit, run the same compile-profile helper Phase 5.6 uses. If any new diagnostic identity appears, restore the full pre-fix diff state immediately — including deleting files created by the bad fix and restoring deleted files. Do not rely on count-only comparison and do not rely on `_snapshot_files`' finding-file list.

This is a runtime-fast feedback that catches fix-regressions in seconds (compile profile) instead of minutes (re-audit cycle).

### S.3 Hollow-recovery historical migration (per §M.M10)

Phase 5.5 ships `agent-team-v15 rescan-quality-debt --cwd <run-dir>`. Implementer should:
1. Test on the 2026-04-28 smoke run-dir as the canonical case (M1 + M2 both have stale "COMPLETE" with hollow-recovery shape).
2. Generate `QUALITY_DEBT_RESCAN.md` for that run-dir as the reference output.
3. Document the migration mode in `docs/operator/phase-5-quality-debt-rescan.md`.

### S.4 Multiple-smoke variance acceptance (per adversarial review #5)

Single live smoke = sample size 1. LLM nondeterminism makes any single run a sample.

M2 from the same `m1-hardening-smoke-20260428-112339` run is the second data point for systematic hollow recovery, not an independent smoke. It still matters because it varies the failure mode: M1 is Wave D compile-fix timeout followed by a looser wave-scope Docker pass; M2 is Wave B narrow self-verify pass followed by endpoint_prober project-scope all-services Docker failure. Phase 5 must therefore treat "hollow recovery" as a cross-surface invariant bug, not as one brittle M1 reproduction.

M3 is the third data point from the same run, but it exposes a different failure class before completion: Wave B can remain active for more than 80 minutes after its last productive `commandExecution`. This is not another score-normalization case; it is a watchdog productivity gap. Phase 5.7 therefore validates both bootstrap-stillborn sessions and productive-tool-idle reasoning loops before claiming the recovery cascade is bounded.

**Wave 2 + Wave 3 smoke commitment:** for the most-load-bearing phases (Phase 5.4, 5.5+5.6, 5.7), implementer runs **3 live smokes** at the same HEAD. Variance acceptance:
* If 3/3 smokes pass the phase's AC → ship.
* If 2/3 pass → surface to user; depends on which AC failed and whether the failure is environmental (Anthropic infra) vs structural (Phase 5 bug).
* If 1/3 or 0/3 → halt; investigate.

**Cost impact:** factor 3x for Wave 2/3 smoke costs. Updated §0.2 floor accounts for this.

### S.5 DEGRADED enum migration (per §M.M12)

Phase 5.5 ships:
* `docs/operator/phase-5-status-enum-migration.md` — schema delta + downstream tooling guidance.
* Deprecation notice fires loudly when first DEGRADED milestone lands in any build.
* Audit existing fixtures that match `status == "COMPLETE"` exactly; broaden to `status in {"COMPLETE", "DEGRADED"}` where appropriate.

---

## Section T — Implementer kickoff prompts (Phase 5.<N> templates)

### T.1 Phase 5.1 kickoff

```
You are Phase 5.1 of the Phase 5 implementation.

Read /home/omar/projects/agent-team-v18-codex/docs/plans/2026-04-28-phase-5-quality-milestone.md
top-to-bottom — Section 0 first.
Then read ~/.claude/projects/-home-omar-projects-agent-team-v18-codex/memory/MEMORY.md
AND ~/.claude/projects/-home-omar-projects-agent-team-v18-codex/memory/smoke_2026-04-28_landing.md (when written).

Confirm Phase 5 baseline at HEAD (`git rev-parse HEAD` returns `2d49a0a` or
descendant; targeted slice (§0.5) returns 570+ passing) before any change.

READ BEFORE YOU WRITE. First report your understanding + planned approach and
wait for lead confirmation. Then implement §D (Phase 5.1) with TDD:
write the failing AC fixtures first, prove they fail for the expected reason,
then implement the minimal source changes.

Land a single commit with:
1. The `should_terminate_reaudit` percentage-normalization fix.
2. The `AuditScore.from_dict` / `AuditReport.from_json` post-parse score +
   severity normalizer. This MUST repair the canonical smoke shape where
   `score` is a dict with zero counters but `by_severity` and parsed findings
   contain CRITICAL/HIGH findings, and the M2 shape where `max_score=0`,
   `by_severity={}`, and parsed findings still contain CRITICAL/HIGH findings.
   Do not fix only the flat-score branch.
3. AC1-AC9 fixtures in `tests/test_pipeline_upgrade_phase5_1.py`, including
   the frozen 2026-04-28 smoke-shape fixture.

Run targeted slice + module import + audit_models slice before commit.
Wide-net sweep (§0.6) before merging.

When done, write phase_5_1_landing.md per §0.9 — include:
- Files touched (matches §D.1)
- Risk #33 + #34 closure evidence
- Backward-compat fixture results (existing audit_models tests pass)
- Open follow-ups (none expected; if any, halt memo §0.10)

Use mcp__sequential-thinking when:
- The percentage normalization interacts with previous_score regression checks
  in non-obvious ways (specifically AC8).
- Severity-counter precedence is ambiguous (`finding_counts` vs `by_severity`
  vs parsed findings vs existing score counters).
- Invalid score-scale recovery is ambiguous (`max_score <= 0` or
  `score > max_score`); recompute through `AuditScore.compute(findings)` when
  findings are parseable, otherwise fail closed.

Anti-patterns (DO NOT):
- Change AuditScore.score field semantics — fix is at comparison sites.
- Set max_score=100 default if missing or zero — that masks scorer drift.
- Flip score_healthy_threshold default to compensate.
- Fix only the flat-score branch — the canonical smoke takes the dict branch.
- Touch the canonical compute path (audit_models.py:506-552) — fixture
  changes there churn unrelated tests.
```

(Phase 5.2 through 5.9 kickoff prompts: same template structure, swap §-letter and risk IDs. Implementer agents extrapolate from Phase 4 plan's §0.0 kickoff template style.)

---

**End of Phase 5 plan v5.**

This document went through 3 review rounds (line-citation accuracy, architectural soundness, adversarial pessimism) before reaching v2, then a senior staff-engineer adversarial Codex review before v3. v4 tightened the plan against M2 empirical evidence from the same 2026-04-28 smoke. v5 tightens the remaining M1+M2+M3 harness gaps without architectural restructure. All confirmed findings are reflected:

* Citation drifts fixed (`config.py:546`→`552`; `cli.py:8369`→`8374`).
* §Q index expanded with all inline citations.
* §M expanded from 12 to 16 resolved decisions (12 v2 review findings + v3 evidence-based sunset correction).
* Phase 5.6 moved from Wave 3 to Wave 2 (architectural-dependency finding).
* Phase 5.2 expanded to fix BOTH broken sites + lint test (incomplete-fix finding).
* Original opt-in strictness flag removed; replaced with `--legacy-permissive-audit` deprecated migration flag (workaround-removal finding).
* `_anchor/_complete/` + `_quality.json` sidecar replaces two-slot fork (architectural-simplicity finding).
* Phase 5.1 now fixes the dict-score severity-counter branch used by the canonical smoke, not only the flat-score fallback.
* In-wave typecheck demoted from contract to hint (verification-gap finding); Phase 5.6 reuses `compile_profiles.run_wave_compile_check` instead of adding a web-only helper.
* Phase 5.7 watchdog: 60s/3 + cumulative wedge budget (calibration + cascade-loop findings).
* Phase 5.8 split into 5.8a-diagnostic / 5.8b-conditional-implementation with sequential diagnostic sampling (premature-architecture + sample-size findings).
* §S reconciled: auditor suppression registry, full-workspace fix-regression rollback, hollow-recovery migration, multiple-smoke variance acceptance, DEGRADED enum migration.
* §T added: implementer kickoff prompt templates.
* Cost floor revised $90-205 → $200-350 → $400-700 (cost-realism + diagnostic-smoke arithmetic finding).
* Risk register annotated with partial-vs-full closure (asymmetry-trap finding).
* v4 adds M2 evidence: nested path drift repeats; score shape variance (`max_score=0`, empty `by_severity`, zero counters with 4 CRITICAL findings); and Wave B narrow-pass / project-scope all-services Docker build-fail divergence.
* v4 corrects the canonical recompute method name to `AuditScore.compute(findings)` (verified in `audit_models.py:506-552`) and adds AC9 for invalid score-scale recompute.
* v4 adds R-#44 and Phase 5.6 AC8 for build-check scope divergence, making project-scope all-services Docker build authoritative while retaining wave-scope per-service builds as diagnostics.
* v4 documents `--no-cache` as a diagnostic/calibration rerun only, not a default Quality Contract gate.
* v5 adds R-#45 and Phase 5.7 productive-tool idle watchdog: `last_tool_call_at`, `tool_call_idle_timeout_seconds=1200`, hang-report fields, and synthetic M3 replay coverage.
* v5 adds R-#46 and Phase 5.2 audit-agent injection: `agent_defs_override` threads `build_auditor_agent_definitions` into `ClaudeAgentOptions.agents`; the proposed positional-arg fix was rejected because `_build_options`' second positional arg is `cwd`.
* v5 adds R-#47 and Phase 5.2 auditor Write scope: audit-* agents get `Write`, but only with an audit-output path guard because the existing audit-fix guard is finding-id-bound.
* v5 adds M3 evidence: Wave B productive-tool idle reached 4920s since `commandExecution`, audit sessions reported missing audit-* registration, and audit-* agents returned inline findings because they lacked `Write`.

Implementer agents: this is the source of truth. New ambiguity → §0.10 halt memo. Do not silently retarget references; surface drift.
