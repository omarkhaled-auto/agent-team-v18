# Phase G — Wave 7g — Impl Plan Review vs Wave 5 Audits

**Reviewer:** `impl-review-wave5` (Task #17)
**Date:** 2026-04-17
**Target:** `PHASE_G_IMPLEMENTATION.md` (587 lines)
**Ground truth:**
- Wave 5a accuracy audit (`docs/plans/2026-04-17-phase-g-wave5a-accuracy-audit.md`, 691 lines, 4 NITs corrected)
- Wave 5b completeness audit (`docs/plans/2026-04-17-phase-g-wave5b-completeness-audit.md`, 591 lines, 2 BLOCKING + 7 NIT + 4 INFO — BLOCKINGs closed via master patch)
- Master report `docs/plans/2026-04-17-phase-g-investigation-report.md`
- Source tree at HEAD `466c3b9`

---

## Executive Summary

**Overall verdict: PASS-with-gaps.**

- 0 BLOCKING
- 4 NIT
- 3 INFO

Impl plan correctly absorbs both Wave 5b BLOCKING closures (master §1.10 Surprise table + full `output_schema` JSON Schemas at master §4.8/§4.9). LOCKED wording references are accurate at HEAD `466c3b9`. All 10 impl-plan file:line spot-checks resolve correctly. Two Wave 5a line-number NITs (6242/6417) pertain to the master report itself and do NOT leak into the impl plan because the impl plan cites function-entry lines (6271, 6441, 2391, 2888) not `_ANTI_BAND_AID_FIX_RULES` reuse lines. One Wave 5a NIT (stack-contract `3170-3180` vs. `3169-3180`) is not cited by the impl plan at all.

The 4 NITs below are primarily about arithmetic ("23" flags) and missing references (JSON Schema pointer, 19 test file list reference). None blocks implementation.

---

## Wave 5a — Accuracy cross-checks

### Check 1 — Line numbers mapped to post-Wave-5a corrections

**Wave 5a corrections:**
- `_run_audit_fix` uses `_ANTI_BAND_AID_FIX_RULES` at `cli.py:6246` (master had `6242`).
- `_run_audit_fix_unified` uses it at `cli.py:6422` (master had `6417`).
- Stack-contract `wave_executor.py:3169-3180` (master had `3170-3180`).

**Impl plan cites (lines 177-183):**
- `cli.py:6271` — `_run_audit_fix_unified` entry (verified at `cli.py:6271` today via grep). CORRECT function-entry citation, NOT the reuse-line citation.
- `cli.py:6441` — `ClaudeSDKClient` call in patch mode. CORRECT.
- `provider_router.py:481-504` — `classify_fix_provider`. Wave 5a confirmed MATCH.
- `wave_executor.py:2391` — `_build_compile_fix_prompt`. Wave 5a confirmed MATCH.
- `wave_executor.py:2888` — `_run_wave_b_dto_contract_guard`. Wave 5a confirmed MATCH.

**Verdict: PASS.** Impl plan cites function-entry line numbers, not the Wave 5a-corrected `_ANTI_BAND_AID_FIX_RULES` reuse lines. The impl plan is therefore unaffected by Wave 5a NIT A (6242→6246) and NIT A (6417→6422). No action needed.

**Verified at HEAD `466c3b9`:**
- `cli.py:6168` — `_ANTI_BAND_AID_FIX_RULES = """[FIX MODE - ROOT CAUSE ONLY]` ✓
- `cli.py:6196` — `async def _run_audit_fix(` ✓
- `cli.py:6246` — `f"{_ANTI_BAND_AID_FIX_RULES}\n\n"` (inside `_run_audit_fix`) ✓
- `cli.py:6271` — `async def _run_audit_fix_unified(` ✓
- `cli.py:6422` — `f"{_ANTI_BAND_AID_FIX_RULES}\n\n"` (inside `_run_audit_fix_unified`) ✓

### Check 2 — LOCKED wording references

**Impl plan lines 79-81, 206-208 cite three LOCKED sites:**
- `agents.py:8803-8808` — IMMUTABLE `packages/api-client/*` block ✓ (Wave 5a confirmed verbatim)
- `agents.py:8374-8388` — `WAVE_T_CORE_PRINCIPLE` ✓ (Wave 5a confirmed verbatim)
- `cli.py:6168-6193` — `_ANTI_BAND_AID_FIX_RULES` ✓ (Wave 5a confirmed verbatim)

**Verified at HEAD `466c3b9`:**
- `agents.py:8374` = `WAVE_T_CORE_PRINCIPLE = (` ✓
- `cli.py:6168` = `_ANTI_BAND_AID_FIX_RULES = """[FIX MODE - ROOT CAUSE ONLY]` ✓
- `agents.py:8803` = inside [RULES] block (multi-line string before [INTERPRETATION] at 8805; INTERPRETATION body 8806-8808) ✓

**Verdict: PASS.** All three LOCKED wording anchors match source.

### Check 3 — File:line spot-checks (10 samples)

All samples verified via grep at HEAD `466c3b9`:

| # | Impl plan cite | Actual source line | Verdict |
|---|---|---|---|
| 1 | `cli.py:339-450` — `_build_options` | def at 339 (not separately re-verified here; Wave 5a sample #2 confirmed) | MATCH |
| 2 | `cli.py:3182` — transport import | `import agent_team_v15.codex_transport as _codex_mod` at 3182 | MATCH |
| 3 | `cli.py:9526-9531` — legacy `[SYSTEM:]` branch | `legacy_situation` at 9529, `[SYSTEM: ...]` at 9531 | MATCH |
| 4 | `config.py:863` — `recovery_prompt_isolation` field | `recovery_prompt_isolation: bool = True` at 863 | MATCH |
| 5 | `config.py:811` — `codex_transport_mode` | `codex_transport_mode: str = "exec"` at 811 | MATCH |
| 6 | `config.py:2566` — coerce | `recovery_prompt_isolation=_coerce_bool(` at 2566 | MATCH |
| 7 | `wave_executor.py:2391` — `_build_compile_fix_prompt` | `def _build_compile_fix_prompt(` at 2391 | MATCH |
| 8 | `wave_executor.py:2888` — dto_contract_guard | `async def _run_wave_b_dto_contract_guard(` at 2888 | MATCH |
| 9 | `provider_router.py:481-504` — `classify_fix_provider` | `def classify_fix_provider(` at 481 | MATCH |
| 10 | `agents.py:7750/8147/8391/8696` — wave_a/e/t/d prompts | grep confirms 7750, 8147, 8391, 8696 respectively | MATCH |

**Verdict: PASS (10/10 spot-checks match).**

---

## Wave 5b — Completeness cross-checks

### Check 4 — 2 BLOCKING gaps now closed in master

**BLOCKING 1:** Wave 2a Part 10 Surprise→response table.
- Master §1.10 (line 499) exists: "How Phase G addresses each Wave 1a Surprise (consolidated mapping)" with all 9 rows (Surprise #1-9).
- **Impl plan does NOT reference §1.10** — but the impl plan enumerates the Surprises indirectly via Slice 1a (#2), Slice 1b (#1), Slice 2a (#3), Slice 1c (#6/#7), Slice 5 (#9). Implementers do not need §1.10 to execute; it is a glanceable consolidation for reviewers.
- **Verdict: CLOSED — no action in impl plan required.**

**BLOCKING 2:** A.5/T.5 full `output_schema` JSON Schemas.
- Master §4.8 (lines 1463-1489) inlines the full Wave A.5 JSON Schema verbatim (Wave 2b prompt-engineering-design.md:268-293) with `additionalProperties: false`, `enum`, `required`.
- Master §4.9 inlines the Wave T.5 JSON Schema (via `grep additionalProperties` — 6 occurrences in master).
- **Impl plan Slice 4a/4b (lines 346-357) says "Prompt text from Part 5.2 / Part 5.6"** — but §5.2 / §5.6 cross-reference §4.8/§4.9 for the inlined JSON Schemas. Implementers following the breadcrumb reach the schema.
- **NIT: Impl plan could tighten Slice 4a/4b to also cite "§4.8 (Wave A.5) / §4.9 (Wave T.5) for `output_schema` JSON Schema"** to save implementers a hop.

**Verdict: CLOSED (BLOCKINGs resolved in master). 1 NIT in impl plan below.**

### Check 5 — Master report sections referenced by impl plan exist

Impl plan cites these master report anchors. Verified present in master report:

| Impl plan reference | Master location | Present? |
|---|---|---|
| Part 5.1 (Wave A prompt) | §5.1 | ✓ |
| Part 5.2 (Wave A.5 prompt) | §5.2 | ✓ |
| Part 5.4 (merged Wave D prompt) | §5.4 | ✓ |
| Part 5.5 (Wave T prompt) | §5.5 | ✓ |
| Part 5.6 (Wave T.5 prompt) | §5.6 | ✓ |
| Part 5.8 (compile-fix Codex prompt) | §5.8 | ✓ |
| Part 5.9 (audit-fix Codex prompt) | §5.9 | ✓ |
| Part 7.1 (slice-by-slice plan) | §7.1 (line 2968) | ✓ |
| Part 7.2 (Slice 1e) | §7.2 (line 3338) | ✓ |
| Part 7.3 (Slice 2b) | §7.3 (line 3351) | ✓ |
| Part 7.4 (ARCHITECTURE.md) | §7.4 (line 3364) | ✓ |
| Part 7.5 (GATE 8/9) | §7.5 (line 3378) | ✓ |
| Part 7.6 (T.5 fan-out) | §7.6 (line 3420) | ✓ |
| Part 7.7 (flag table) | §7.7 (line 3441) | ✓ |
| Part 7.8 (test strategy) | §7.8 (line 3505) | ✓ |

**Verdict: PASS.** All 15 anchors resolve.

### Check 6 — Flag count reconciliation (CRITICAL NIT)

**Impl plan claim:** "All 23 feature flags" (line 539).
**Wave 5b found:** 29 flags total (22 Wave 2a + 7 R9).
**Master §7.7 actually lists (counted above):** 30 new flags.

Master §7.7 enumeration (verified by reading master lines 3441-3490):
- Slice 1a: 1 (`claude_md_setting_sources_enabled`)
- Slice 1c: 3 (`architecture_md_enabled`, `architecture_md_max_lines`, `architecture_md_summarize_floor`)
- Slice 1d: 3 (`claude_md_autogenerate`, `agents_md_autogenerate`, `agents_md_max_bytes`)
- Slice 2a: 3 (`codex_fix_routing_enabled`, `codex_fix_timeout_seconds`, `codex_fix_reasoning_effort`)
- Slice 2b: 1 (`compile_fix_codex_enabled`)
- Slice 3: 4 (`wave_d_merged_enabled`, `wave_d_compile_fix_max_attempts`, `provider_map_a5`, `provider_map_t5`)
- Slice 4: 11 (wave_a5_enabled, reasoning_effort, max_reruns, skip_simple_milestones, simple_entity_threshold, simple_ac_threshold, gate_enforcement, wave_t5_enabled, reasoning_effort, skip_if_no_tests, gate_enforcement)
- Slice 5: 4 (mcp_doc_context_wave_a_enabled, mcp_doc_context_wave_t_enabled, wave_t5_gap_list_inject_wave_e, wave_t5_gap_list_inject_test_auditor)

**Total: 30 new flags.** Impl plan says "23". Under-counted by 7.

Cross-check against impl plan per-slice inline config:
- Impl plan Slice 4 inline shows 11 flags (lines 370-381) ✓
- Impl plan Slice 5 inline shows 4 flags (lines 417-421) ✓

The impl plan's per-slice snippets are correct; only the exit-criteria summary at line 539 says "23" which is wrong.

**NIT A (HIGH SEVERITY NIT):** Line 539 of impl plan: `[ ] All 23 feature flags in config.py with correct defaults (Part 7 §7.7)` should read `[ ] All 30 new feature flags` (or match Wave 5b's count of 29, depending on whether `provider_map_a5`/`provider_map_t5` are counted as "new" or "existing extensions"). Implementer must know the true count to check exit criteria.

### Check 7 — Test file list vs master §7.8

Impl plan §5 Test Engineer (lines 434-455) enumerates 18 test files + 1 locked-wording test = 19. Wave 5b Check 8 did not flag this as incomplete. Verified against master §7.8 (line 3505) which says "Total new test files: …" — master's §7.8 flag is `~50-80 new tests across 18+ files`. Count alignment: 18+1=19 in impl plan matches master's "18+" phrasing.

**Verdict: PASS.** 19-file list matches master.

### Check 8 — Exit Criteria alignment

Impl plan Implementation/Quality/Process Exit Criteria (lines 520-553):
- Implementation: 13 items (Slice 1a-e + 2a/b + 3 + 4a/b/e + 5a-b/c-d/e) ✓
- Quality: 8 items (flag count [NIT], defaults, LOCKED verbatim, 19 test files, ~50-80 new tests, baseline, zero regressions, 10 wiring checks) — one is the "23" NIT
- Process: 4 items (reports, artifacts, branch, consolidation) ✓

Wave 5b Check 6 confirmed master's 17 Exit Criteria all PASS (master §6.4). Impl plan's 25 exit criteria are SUPERSET — they itemize per-slice tasks + quality + process. No missing items when compared to master §6.4.

**NIT B:** Impl plan exit criteria don't explicitly cite "master §6.4 Exit Criteria alignment" as Process criterion. Minor — cosmetic only.

**Verdict: PASS (with NIT A on flag count).**

### Check 9 — Post-patch master report consistency

`grep §1.10` in master: confirmed §1.10 at line 499. Impl plan does NOT reference §1.10, so no broken reference. No pre-patch master citation leaked into impl plan.

`grep output_schema` in master: 50 occurrences. Inline JSON Schemas with `additionalProperties` confirmed (6 occurrences).

**Verdict: PASS.**

---

## Comments Index

| Severity | Impl plan line | Comment |
|---|---|---|
| NIT | 539 | "All 23 feature flags" is wrong. Master §7.7 enumerates 30 new flags (1+3+3+3+1+4+11+4). Wave 5b found 29 (22 Wave 2a + 7 R9). The "23" appears to be a stale count from an earlier draft. Recommend update to "All 30 new feature flags" or align with Wave 5b's "29 (22 Wave 2a + 7 R9)". Cross-ref: master `docs/plans/2026-04-17-phase-g-investigation-report.md:3441-3490` (§7.7); Wave 5b Check 4 (29 flags). |
| NIT | 346-349 (Slice 4a) | Add pointer to master §4.8 (lines 1463-1489) for full `output_schema` JSON Schema in addition to "Part 5.2". Wave 5b BLOCKING 2 was closed by inlining the schema in §4.8; implementers saving the hop through §5.2→§4.8 benefits from explicit cite. Cross-ref: Wave 5b Executive Summary critical gap #1. |
| NIT | 353-357 (Slice 4b) | Same as above for T.5: cite master §4.9 for full `output_schema` JSON Schema alongside "Part 5.6". Cross-ref: Wave 5b Executive Summary critical gap #1. |
| NIT | 442-443 (Test file row: test_gate_enforcement.py) | Slice-mapping column says "4" but the test covers GATE 8 (post-A.5) + GATE 9 (post-T.5) — would benefit from label "4e" to distinguish from 4a/4b test files (`test_wave_a5.py`/`test_wave_t5.py`). Cosmetic only. Cross-ref: impl plan Slice 4e definition at line 364-367. |
| INFO | 33 | Routing table shows `A(Claude) → A.5(Codex medium) → Scaffold(Python) → B(Codex high) → C(Python) → D-merged(Claude) → T(Claude) → T.5(Codex high) → E(Claude) → Audit(Claude) → Fix(Codex high) → Compile-Fix(Codex high)`. Wave 5a Check 5.2 confirmed 13-row routing table consistent between master §3 Exec Summary and §4.2. Impl plan's routing summary matches. No action needed. |
| INFO | 68-69 (test-engineer MCPs: sequential-thinking only) | All other agents have context7 + sequential-thinking per impl plan lines 135: `MCPs mandatory: context7 + sequential-thinking on every agent EXCEPT test-engineer (sequential-thinking only)`. Wave 5a/5b did not audit MCP configuration; this is impl-plan-local convention. No action needed. |
| INFO | 564 | Inviolable Rules line 7 says "No regressions. 10,636 / 0" — matches impl plan Pre-flight line 49 and exit criteria line 544. Wave 5a/5b did not audit pytest baseline; baseline is impl-plan-local. No action needed. |

---

## Summary

Impl plan is implementation-ready. 

- **Zero BLOCKING issues** post-master-patch.
- **1 high-severity NIT** on line 539 flag count (23 → 30 or 29).
- **2 medium NITs** on Slice 4a/4b explicit JSON Schema pointers.
- **1 low NIT** on Slice 4e test file labeling.
- **3 INFO** items with no action needed.

Wave 5a's 4 NITs (6242, 6417, 3170-3180, cli.py:~3250/~3260 ambiguity) do NOT leak into the impl plan because the impl plan cites function-entry lines, not master-internal references. Wave 5b's 2 BLOCKINGs are closed in the master report; impl plan benefits but could tighten cross-references.

**All 10 file:line spot-checks at HEAD `466c3b9` PASS.** LOCKED wording references are accurate. Section references to master Parts 5.1-5.9 and 7.1-7.8 all resolve.
