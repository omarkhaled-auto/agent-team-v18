# Phase G — Wave 7f — Impl Plan Review vs Wave 3 Findings

**Date:** 2026-04-17
**Reviewer:** `impl-review-wave3` (Phase G Wave 7f)
**Target:** `C:\Projects\agent-team-v18-codex\PHASE_G_IMPLEMENTATION.md` (587 lines)
**Ground truth A:** `docs/plans/2026-04-17-phase-g-integration-verification.md` (Wave 3, 659 lines)
**Ground truth B:** `docs/plans/2026-04-17-phase-g-investigation-report.md` Appendix D (R1-R10 verbatim, lines 3820-3911) + Part 4.11 flag table (lines 1666-1696) + Part 7.7 (lines 3441-3496).
**Review scope:** 5 conflicts + 10 verification checks + LOCKED wording audit + Exit Criteria + R1-R10 absorption.

---

## Executive Summary

**Verdict:** The impl plan absorbs the majority of Wave 3 and R1-R10, but carries **TWO BLOCKING errors** that misstate the spec and **one HIGH gap** that omits a load-bearing design element:

1. **BLOCKING — Slice 1d (line 259) cites the WRONG three canonical invariants.** The impl plan says the three invariants are `IMMUTABLE, WAVE_T_CORE_PRINCIPLE, _ANTI_BAND_AID_FIX_RULES`. Per R8 + Wave 2b Appendix C.1 (`prompt-engineering-design.md:1816-1820`), the three canonical invariants are (1) no parallel `main.ts`/`bootstrap()`/`AppModule`; (2) no edits to `packages/api-client/*` outside Wave C; (3) no `git commit`/new branches. These are content for CLAUDE.md/AGENTS.md, NOT the three LOCKED prompt blocks. The LOCKED blocks are a DIFFERENT category (prompt-level verbatim constants transferred into Wave A/T/D/E/Fix prompts, not into the constitution files).

2. **BLOCKING — Feature flag count wrong (lines 476 + 539).** Impl plan says "all 23 feature flags from Part 7 §7.7". Part 7.7 literally enumerates **30 flags** (Part 4.11 table lists 29 rows with R9 additions highlighted; Part 7.7 adds `agents_md_max_bytes`). Wave 5b completeness audit already flagged this at 29. An impl plan that ships verification checks "23 flags exist" will FAIL — or worse, pass vacuously while missing 7 load-bearing flags.

3. **HIGH — R3 two-doc ARCHITECTURE.md only half-implemented.** Impl plan Slice 1c (line 246-254) covers ONLY the cumulative `<cwd>/ARCHITECTURE.md` (python helper). The per-milestone `.agent-team/milestone-{id}/ARCHITECTURE.md` written by Wave A (Claude) — the Wave 2b design intent preserved by R3 — is NOT explicitly scheduled in any slice. The Wave A prompt MUST added by R3 is implicit in Part 5.1 + Slice 5a, but the slice text (lines 398-400) only covers `mcp_doc_context` injection; it does not call out the "write per-milestone ARCHITECTURE.md" MUST.

The remainder of R1-R10 is absorbed. LOCKED wording references are consistent. Slices 1e/2b/5 (R10's additions) are present. GATE 8/9 enforcement (R4) is correctly specified. T.5 fan-out to Wave E + TEST_AUDITOR (R5 secondary + tertiary) is present; R5 primary (Wave T fix loop) is not explicitly called out in Slice 4b but is implied by the existing Wave T fix-loop machinery.

---

## R1-R10 Absorption Verdicts

### R1 — Compile-Fix routing → Codex `high`

**Impl plan coverage:** Slice 2b (lines 295-302).

- Flag `compile_fix_codex_enabled` added ✓ (line 300)
- `_build_compile_fix_prompt` rewrite at `wave_executor.py:2391` ✓ (line 298)
- Caller `_run_wave_b_dto_contract_guard` at `wave_executor.py:2888` ✓ (line 299: "thread `_provider_routing` parameter")
- New `_run_wave_d_compile_fix` threading (R1 also names this caller): **partial** — Slice 3d (line 334-336) says "merged-D compile-fix uses Slice 2b's Codex compile-fix if both flags on" but doesn't explicitly schedule threading `_provider_routing` through the new helper. Acceptable — Slice 3 owns the merged-D helper creation.

**Verdict: PASS.**

### R2 — Recovery `[SYSTEM:]` kill

**Impl plan coverage:** Slice 1e (lines 266-274).

- Non-flag-gated ✓ (line 266 and 139/561)
- Delete `cli.py:9526-9531` ✓ (line 269)
- Remove `recovery_prompt_isolation` at `config.py:863` ✓ (line 270)
- Remove coerce at `config.py:2566` ✓ (line 271)
- Unit test via `test_recovery_prompt.py` ✓ (line 441)
- Build-j BUILD_LOG:1502-1529 rationale cited ✓ (line 274)

**Verdict: PASS.**

### R3 — ARCHITECTURE.md two-doc model

**Impl plan coverage:** Slice 1c (lines 246-254) — cumulative only.

- Cumulative `<cwd>/ARCHITECTURE.md` via python helper ✓ (line 250-251)
- `init_if_missing()`, `append_milestone()`, `summarize_if_over()` ✓ (line 249)
- Config flags `architecture_md_enabled`, `max_lines`, `summarize_floor` ✓ (line 252)
- **Per-milestone `.agent-team/milestone-{id}/ARCHITECTURE.md` written by Wave A: MISSING as a distinct implementation step.** R3 verdict (line 3849-3852 of investigation report) mandates BOTH docs with different lifecycles. The per-milestone doc is Wave A's own MUST (per Part 5.1 prompt text), injected as `<architecture>` XML tag into Wave B/D/T/E of the same milestone. Slice 5a wires `mcp_doc_context` into Wave A but does not call out the "write per-milestone ARCHITECTURE.md" prompt MUST nor the downstream consumers injecting `<architecture>`. Line 254 says "Content template from Part 4.5" — Part 4.5 covers the cumulative template; per-milestone template is in Part 5.1 (Wave A prompt).
- Line 128 of impl plan mentions "Slice 5 (mcp_doc_context + T.5 fan-out + .codex/config.toml)" — no mention of `<architecture>` wiring into Wave B/D/T/E prompts.
- Consumer injection tag (`<architecture>` XML for per-milestone, `[PROJECT ARCHITECTURE]` for cumulative) — NOT explicit in impl plan.

**Verdict: PASS (gap).** BLOCKING if interpreted strictly; at minimum HIGH gap to address.

### R4 — GATE 8/9 enforcement

**Impl plan coverage:** Slice 4e (lines 364-368).

- GATE 8 after A.5: CRITICAL blocks Wave B, re-run Wave A with feedback, max 1 rerun ✓ (line 366 + flag `wave_a5_max_reruns: int = 1` at line 373)
- GATE 9 after T.5: CRITICAL blocks Wave E, loop to Wave T iteration 2 ✓ (line 367)
- Flag `wave_a5_gate_enforcement: bool = False` ✓ (line 377)
- Flag `wave_t5_gate_enforcement: bool = False` ✓ (line 381)
- Skip conditions apply even when flags True — implicit via 4a (line 352) and 4b (line 358) but not restated in 4e. NIT.

**Verdict: PASS.**

### R5 — T.5 gap list fan-out

**Impl plan coverage:** Slice 5c (lines 406-408), Slice 5d (lines 410-411), Slice 4b artifact persistence (line 357).

- **Primary (Wave T fix loop):** Per R5 "no new flag — this is the original T.5 purpose". Impl plan Slice 4b persists gaps to `.agent-team/milestones/{id}/WAVE_T5_GAPS.json` (line 357) but does NOT explicitly call out feeding into Wave T fix loop. This is INFO — the primary consumer is the original Wave 2a §7.5 design, which is existing Wave T machinery. Not a blocker, but impl plan should reference "primary consumer: Wave T fix loop (existing)" for clarity.
- **Secondary (Wave E):** Slice 5c ✓ — flag `wave_t5_gap_list_inject_wave_e` ✓ (line 420), `<wave_t5_gaps>` block ✓ (line 407), reads from WAVE_T5_GAPS.json ✓ (line 408).
- **Tertiary (TEST_AUDITOR):** Slice 5d ✓ — flag `wave_t5_gap_list_inject_test_auditor` ✓ (line 421), `audit_prompts.py:651` ✓ (line 411).

**Verdict: PASS (nit).** Primary (Wave T fix loop) wiring is implicit; call it out in Slice 4b for completeness.

### R6 — Nit: Wave 2b Appendix A "Delete after G-3 flip" labels

**Impl plan coverage:** Not referenced directly — impl plan doesn't modify Wave 2b Appendix A. R6 is a labeling nit in the DESIGN doc (Wave 2b); it was absorbed into the master report (line 3877-3878) and is reflected in retirement plan (lines 1702-1705 of master report) where `wave_d5_enabled` + `CODEX_WAVE_D_PREAMBLE/SUFFIX` + `build_wave_d5_prompt` are retained "while `v18.wave_d_merged_enabled=False`". The impl plan Slice 3 (lines 314-336) correctly extends `build_wave_d_prompt` with `merged: bool = False` kwarg (line 320), preserving legacy path — consistent with R6's intent.

**Verdict: PASS.** (R6 is a design-doc labeling fix, not an impl task.)

### R7 — Audit-Fix patch-mode qualifier

**Impl plan coverage:** Slice 2a (lines 284-293).

- `cli.py:6441` is the patch-mode dispatch site (line 287 + 443) — R7's "patch-mode only" qualifier is IMPLICIT in the line target (6441 is inside `_run_patch_fixes` per investigation report E.4 line 4063-4064). Impl plan doesn't explicitly state "patch-mode only" in Slice 2a text. Full-build mode is unchanged (subprocess escalation — investigation report §4.1).
- Prompt text from Part 5.9 ✓ (line 293)

**Verdict: PASS (nit).** Slice 2a text should explicitly say "patch-mode only" to match R7 phrasing. Low risk because the line target unambiguously scopes to patch mode.

### R8 — SHARED_INVARIANTS (3 canonical invariants)

**Impl plan coverage:** Slice 1d (lines 256-264).

**BLOCKING ERROR at line 259:**

> "NEW `src/agent_team_v15/constitution_templates.py` — template constants for CLAUDE.md and AGENTS.md content (3 canonical invariants per R8: IMMUTABLE, WAVE_T_CORE_PRINCIPLE, _ANTI_BAND_AID_FIX_RULES verbatim + project conventions)"

**This is wrong.** Per R8 (investigation report lines 3885-3892) + Wave 2b Appendix C.1 (`prompt-engineering-design.md:1816-1820`), the 3 canonical invariants are:

1. "Do NOT create a parallel `main.ts`, `bootstrap()`, or `AppModule`. A second one is a FAIL."
2. "Do NOT modify `packages/api-client/*` except in Wave C. That directory is the frozen Wave C deliverable for all other waves."
3. "Do NOT `git commit` or create new branches. The agent team manages commits."

`IMMUTABLE`, `WAVE_T_CORE_PRINCIPLE`, `_ANTI_BAND_AID_FIX_RULES` are the **three LOCKED prompt blocks** (a different concept) that get transferred VERBATIM into the prompt bodies of Wave A/T/D/E/Fix — NOT into the CLAUDE.md/AGENTS.md constitution files. The LOCKED blocks live in `agents.py:8803-8808`, `agents.py:8374-8388`, and `cli.py:6168-6193` respectively. The canonical invariants live in CLAUDE.md + AGENTS.md (repo root) as stack-wide "do not" rules loaded via `setting_sources=["project"]` and Codex AGENTS.md auto-load.

If the impl agent literally executes line 259, Slice 1d will:
- Copy `IMMUTABLE` verbatim into CLAUDE.md/AGENTS.md (duplicating prompt content into constitution files — Wave 1c §4.4 explicitly says DON'T)
- Miss the 3 canonical invariants R8 requires (the parallel-main.ts rule, the api-client rule specifically, and the git-commit rule)
- Silently violate R8's core purpose (consolidate invariants into the constitution so prompts don't re-inline them)

**Verdict: BLOCKING.** Impl plan line 259 must be rewritten to:

> "... (3 canonical invariants per R8 / Wave 2b Appendix C.1: (1) no parallel `main.ts`/`bootstrap()`/`AppModule`; (2) no edits to `packages/api-client/*` except in Wave C; (3) no `git commit` or new branches + project conventions)"

### R9 — Flag additions

**Impl plan coverage:** Slices 2b/4/5 + impl plan line 476 + line 539.

R9 added 7 flags (line 3897-3903 of master):
- `compile_fix_codex_enabled` (R1) — In Slice 2b ✓ (line 300)
- `wave_a5_gate_enforcement` (R4) — In Slice 4 ✓ (line 377)
- `wave_t5_gate_enforcement` (R4) — In Slice 4 ✓ (line 381)
- `mcp_doc_context_wave_a_enabled` — In Slice 5 ✓ (line 418)
- `mcp_doc_context_wave_t_enabled` — In Slice 5 ✓ (line 419)
- `wave_t5_gap_list_inject_wave_e` (R5) — In Slice 5 ✓ (line 420)
- `wave_t5_gap_list_inject_test_auditor` (R5) — In Slice 5 ✓ (line 421)

All 7 R9 flags are present. However, the claim at line 476 and 539 that there are "23 feature flags" in Part 7 §7.7 is wrong — Part 7.7 (lines 3441-3496) literally enumerates **30 flags**; Part 4.11 (lines 1668-1696) has 29 rows. See Flag Count Reconciliation below.

**Verdict: BLOCKING** on the count claim; individual flags all present.

### R10 — Slice 5 + Slice 1e + Slice 2b

**Impl plan coverage:**
- Slice 1e (Foundations — recovery kill): Lines 266-274 ✓
- Slice 2b (Fix routing — Compile-Fix Codex): Lines 295-302 ✓
- Slice 5 (Prompt integration wiring): Lines 386-421 ✓

**Verdict: PASS.** All three R10 slices present.

---

## LOCKED Wording Audit Reference

Wave 3 §6.3 and §3.1-3.3 verified LOCKED wording verbatim from source at HEAD `466c3b9`:
- IMMUTABLE at `agents.py:8803-8808` ✓
- WAVE_T_CORE_PRINCIPLE at `agents.py:8374-8388` ✓
- `_ANTI_BAND_AID_FIX_RULES` at `cli.py:6168-6193` ✓

Impl plan references:
- Line 37: "LOCKED items preserved verbatim: IMMUTABLE rule, WAVE_T_CORE_PRINCIPLE, _ANTI_BAND_AID_FIX_RULES." ✓
- Lines 79-81: LOCKED wording line targets listed for Wave 1 line-map verification ✓
- Lines 205-208: Verbatim-check targets enumerated for Wave 1 ✓
- Line 138: "LOCKED wording transfers VERBATIM. IMMUTABLE block, WAVE_T_CORE_PRINCIPLE, _ANTI_BAND_AID_FIX_RULES — copy-paste, don't paraphrase." ✓
- Line 322: "IMMUTABLE block at `agents.py:8803-8808` transfers VERBATIM" (in Slice 3) ✓
- Line 455: New `test_locked_wording_verbatim.py` asserts LOCKED strings verbatim in all design references ✓
- Line 541: Exit criterion for verbatim LOCKED wording ✓

**Verdict: PASS.** Wave 3's verbatim PASS for all 3 LOCKED items is correctly carried through. **However** — Slice 1d at line 259 (R8 error above) incorrectly CATEGORIZES LOCKED blocks as "canonical invariants for constitution files". If acted on, this would inline LOCKED blocks into CLAUDE.md/AGENTS.md — a category confusion that reverses R8's intent (Wave 1c §4.4: "Don't duplicate into the system prompt. Anything in CLAUDE.md/AGENTS.md is additive"). LOCKED blocks remain verbatim in their original prompt sites; constitution files carry the 3 canonical invariants, separately.

---

## Flag Count Reconciliation

**Impl plan claims:**
- Line 476: "Feature flags (all 23 from Part 7 §7.7): verify each flag exists in config.py with correct default."
- Line 539 (Exit Criteria): "All 23 feature flags in config.py with correct defaults (Part 7 §7.7)"

**Actual counts:**
- **Part 4.11 table (investigation report lines 1666-1696):** 29 new flag rows (verified by row count; matches Wave 5b §3 "29 flags incl. R9").
- **Part 7.7 codeblock (investigation report lines 3441-3496):** 30 entries (same 29 from Part 4.11 + `agents_md_max_bytes` which Part 4.11 omits but Part 7.7 / Slice 1d include).
- **Authoritative new-flag count: 29 or 30** depending on whether `agents_md_max_bytes` is counted as a flag (it's an int config, behaves like a flag in 7.7).

**Existing flag consumed by Slice 1b:** `codex_transport_mode` at `config.py:811` is NOT a new addition — Phase G only adds a consumer. Not counted.

**Flags to retire (not counted as new):**
- `recovery_prompt_isolation` — REMOVED in Slice 1e.
- `wave_d5_enabled` — retained through Phase G, removed at G-3 flip.

**Verdict: BLOCKING.** Impl plan's "23" is demonstrably wrong. Update to 29 (or 30 if counting `agents_md_max_bytes`). Wave 6 test `test_locked_wording_verbatim.py` style is not affected, but the wiring-verifier (line 461-478) and Exit Criteria need the correct count. Recommend aligning with Part 4.11's 29 (which is the authoritative table and what Wave 5b confirmed).

---

## Exit Criteria Alignment

Wave 3 Part 4 audited 17 **design-level** criteria from `PHASE_G_INVESTIGATION.md:769-787`. Those criteria are DESIGN-COMPLETENESS (e.g., "Wave D merge fully specified", "ARCHITECTURE.md fully specified"). Wave 3 + R1-R10 closed all of them (the CONFLICT 3 + CHECK 4 + 2 GAPs were resolved by R1/R2/R3/R4/R5/R9/R10).

Impl plan's Exit Criteria (lines 520-553) are **implementation-level**:
- 14 Implementation criteria (Slice 1a through Slice 5e)
- 8 Quality criteria (flags, LOCKED, tests, baseline, regressions, wiring)
- 4 Process criteria (reports, artifacts, branch, consolidation)

**Category mismatch is acceptable** — the impl plan is for EXECUTION, not DESIGN. Design-level Exit Criteria were closed by Wave 4 synthesis + R1-R10.

**Missing implementation criteria I'd expect:**
- **R3 per-milestone ARCHITECTURE.md**: Impl plan Exit Criterion line 525 says "ARCHITECTURE.md writer — `init_if_missing` + `append_milestone` + summarization" (cumulative only). Missing: "Per-milestone ARCHITECTURE.md written by Wave A; injected as `<architecture>` into Wave B/D/T/E prompts". Add as an Exit Criterion row.
- **R8 constitution content**: Impl plan Exit Criterion line 526 says "CLAUDE.md + AGENTS.md renderers — templates + writer + size enforcement". Missing specific verification that the 3 canonical invariants (parallel main.ts + api-client + git-commit) are present in the rendered files. Add as an Exit Criterion row.
- **R5 primary consumer**: Impl plan Exit Criterion line 535 mentions "T.5 gap fan-out to Wave E + TEST_AUDITOR" (two consumers). Missing mention of primary (Wave T fix loop). Add for clarity.
- **Flag count**: Line 539 says "All 23" — must become "All 29" (per Part 4.11) or "All 30" (per Part 7.7).

**Verdict: PASS (with gaps).** Categorically aligned; three rows to add for completeness, one count fix.

---

## Open Questions Status (Wave 3 §6.3)

Wave 3 raised 5 open questions. All resolved by R1-R10:

1. **Compile-Fix routing** → R1 ACCEPTED (Option A). Impl plan Slice 2b ✓
2. **Recovery-path kill** → R2 ACCEPTED. Impl plan Slice 1e ✓
3. **ARCHITECTURE.md two-doc model** → R3 ACCEPTED (both docs). Impl plan Slice 1c covers cumulative ONLY — **R3 not fully absorbed** (see R3 verdict above).
4. **GATE 8/9 enforcement severity** → R4 ALIGNED. Impl plan Slice 4e ✓
5. **T.5 gap list propagation scope** → R5 ACCEPTED (all 3 consumers). Impl plan Slice 5 covers Wave E + TEST_AUDITOR; primary (Wave T fix loop) implicit ✓ (nit)

---

## Comments Index

Format: `[SEVERITY] — <line> — <comment>` with R# or Wave 3 check# citation.

| # | Severity | Line | Comment |
|---|---|---|---|
| 1 | **BLOCKING** | 259 | R8: "3 canonical invariants" are WRONG. Currently states `IMMUTABLE, WAVE_T_CORE_PRINCIPLE, _ANTI_BAND_AID_FIX_RULES` — these are LOCKED prompt blocks, not constitution-file invariants. Per R8 + Wave 2b Appendix C.1 the three are: (1) no parallel `main.ts`/`bootstrap()`/`AppModule`; (2) no edits to `packages/api-client/*` except in Wave C; (3) no `git commit` or new branches. Rewrite. |
| 2 | **BLOCKING** | 476 | R9 / Check 7: Flag count "23" wrong. Part 7.7 lists 30 flags; Part 4.11 has 29 rows (matches Wave 5b audit). Update wiring-verifier to check 29 (Part 4.11) or 30 (Part 7.7). |
| 3 | **BLOCKING** | 539 | R9: Same flag-count error in Exit Criteria. Update to "All 29 feature flags" (per Part 4.11). |
| 4 | **HIGH** | 246-254 | R3: Slice 1c covers ONLY cumulative `<cwd>/ARCHITECTURE.md`. R3 mandates BOTH docs — per-milestone `.agent-team/milestone-{id}/ARCHITECTURE.md` written by Wave A (Claude) with `<architecture>` XML injection into Wave B/D/T/E is not scheduled. Add explicit slice text or a new sub-slice (e.g., 1c.2 per-milestone). |
| 5 | **HIGH** | 398-400 | R3: Slice 5a wires `mcp_doc_context` into Wave A but does not include R3's Wave-A MUST: "write `.agent-team/milestone-{milestone_id}/ARCHITECTURE.md`". Per Part 5.1 prompt text the MUST is already there; impl plan should reference it explicitly so the slice5 impl agent verifies it shipped. |
| 6 | **HIGH** | 407-408 | R3: Slice 5c only injects `<wave_t5_gaps>` into Wave E. Missing: `<architecture>` XML injection of per-milestone ARCHITECTURE.md into Wave B/D/T/E per R3. Add a Slice 5 sub-step (5f?) or a Slice 3 sub-step covering this wiring. |
| 7 | **NIT** | 354-358 | R5 primary consumer: Slice 4b says "Persists gaps to WAVE_T5_GAPS.json" but doesn't explicitly say "feed into Wave T fix loop (primary consumer — existing per Wave 2a §7.5)". Add one-line clarification. |
| 8 | **NIT** | 284-293 | R7: Slice 2a description lacks explicit "patch-mode only" qualifier. Line target 6441 is inside `_run_patch_fixes` so scoping is correct in practice, but R7 wording fix should also appear in the slice text. |
| 9 | **INFO** | 369-382 | R4 skip conditions: Slice 4e gate enforcement doesn't restate that skip conditions from 4a/4b override the gate. Impl agent may miss the interaction. Consider adding "Skip conditions in 4a/4b apply even when enforcement flags True (per R4)". |
| 10 | **INFO** | 474 | R3: Wiring-verifier step 10 says "Wave A/T prompts contain `<framework_idioms>`; Wave E contains `<wave_t5_gaps>`". Missing: verify `<architecture>` XML tag present in Wave B/D/T/E prompts. |
| 11 | **INFO** | 542 | Test file count: "18+ test files + 1 locked-wording test = 19 test files" — matches impl plan table (lines 436-455) listing 18 slice-specific files + `test_locked_wording_verbatim.py`. ✓ |
| 12 | **INFO** | 130 | Wave 7 description says "consolidates → PHASE_G_REPORT.md". Investigation report §7.7 tests reference `docs/plans/2026-04-17-phase-g-report.md` at line 499. Naming consistent. |
| 13 | **INFO** | 37 | "LOCKED items preserved verbatim: IMMUTABLE rule, WAVE_T_CORE_PRINCIPLE, _ANTI_BAND_AID_FIX_RULES." ✓ Correct. This correct usage at line 37 makes the error at line 259 (R8 issue) even more likely to mislead — two different concepts using the same 3-item name. |
| 14 | **INFO** | 260-262 | Slice 1d renderers `render_claude_md`, `render_agents_md`, `render_codex_config_toml` ✓. `project_doc_max_bytes = 65536` via `.codex/config.toml` (line 264, 414) ✓. Aligned with R10. |
| 15 | **INFO** | 363-367 | R4 code site: impl plan says orchestrator-level gating without specifying cli.py vs wave_executor.py. Investigation report E.1 line 3931 clarifies `cli.py:~3250, ~3260` for gate logic. Slice 4e should name the file. |

---

## Appendix: Source Verification Method

### Inputs read

- `C:\Projects\agent-team-v18-codex\PHASE_G_IMPLEMENTATION.md` (587 lines, full)
- `docs/plans/2026-04-17-phase-g-integration-verification.md` (659 lines, full)
- `docs/plans/2026-04-17-phase-g-investigation-report.md` Appendix D (3820-3911), Part 4.11 (1662-1710), Part 7.7 (3441-3505), Part 7.6 (3420-3439), Part 7 Slice 4 (3258-3295), Part 7 Slice 5 (3296-3337), Appendix E.1 files table (3919-3998)
- `docs/plans/2026-04-17-phase-g-prompt-engineering-design.md` Appendix C.1 (1805-1827)
- `PHASE_G_INVESTIGATION.md` Exit Criteria (769-787)
- `docs/plans/2026-04-17-phase-g-wave5b-completeness-audit.md` (§3 flag-count confirmation)
- Source files: `src/agent_team_v15/config.py:770 (V18Config), 863 (recovery_prompt_isolation), 2566 (coerce)` — confirming line targets still valid at HEAD.

### Verdict counts

- **BLOCKING: 3** (R8 invariants at line 259; flag count at line 476; flag count at line 539)
- **HIGH: 3** (R3 per-milestone doc not scheduled; Wave A MUST not called out; `<architecture>` injection missing from Slice 5)
- **NIT: 2** (R5 primary consumer; R7 patch-mode qualifier)
- **INFO: 7**

### Key citations

- R1 = master report lines 3824-3833
- R2 = master report lines 3835-3844
- R3 = master report lines 3846-3852
- R4 = master report lines 3854-3863
- R5 = master report lines 3865-3873
- R6 = master report lines 3875-3878
- R7 = master report lines 3880-3883
- R8 = master report lines 3885-3892
- R9 = master report lines 3894-3903
- R10 = master report lines 3905-3911
- Wave 3 LOCKED audit = Wave 3 Part 3 (`integration-verification.md:420-508`)
- Part 4.11 flag table = master report lines 1662-1710 (29 rows)
- Part 7.7 flag codeblock = master report lines 3441-3496 (30 entries)
- Wave 2b Appendix C.1 canonical invariants = `prompt-engineering-design.md:1805-1827`

---

**Completion:** Wave 7f impl plan review vs Wave 3 complete. 3 BLOCKING, 3 HIGH, 2 NIT, 7 INFO. Hand to team-lead for Wave 8 resolution.
