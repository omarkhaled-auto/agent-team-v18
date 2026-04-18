# Phase G — Wave 7a — Impl Plan Review vs Wave 1a Findings

> Reviewer: `impl-review-wave1a`
> Source of truth: `docs/plans/2026-04-17-phase-g-pipeline-findings.md` (Wave 1a, 1301 lines)
> Target under review: `PHASE_G_IMPLEMENTATION.md` (587 lines)
> Reference HEAD: `466c3b9` (confirmed via `git rev-parse HEAD`)

---

## Executive Summary

**Verdict:** PASS-with-comments.

**Drifts found:** 6 total — 0 BLOCKING, 3 NIT, 3 INFORMATIONAL.

The impl plan is accurate to Wave 1a on every LOAD-BEARING claim:
- All 9 "Surprises" are covered by at least one slice (though only #1, #2, #3, #6, #7 are explicit; #4, #5, #8, #9 are implicit — see Check 1).
- Every LOCKED-wording file:line citation (agents.py:8803-8808, agents.py:8374-8388, cli.py:6168-6193) is verified against HEAD `466c3b9` and correct.
- 8/8 spot-checked line targets match HEAD exactly.
- CLAUDE.md / AGENTS.md semantics match Wave 1a §8 verbatim quotes from Context7.
- Fix routing assertion ("classify_fix_provider exported but never called") is confirmed against source.

The comments below are about **precision**, not correctness: the plan occasionally under-cites Wave 1a findings, one config-line citation is off by a few lines, and the "compile-fix-then-rollback" wording at line 191 conflates two distinct regions. None of these block implementation.

**Key concerns for implementation:**
- Surprises #4 (Wave T bypass) and #5 (D5 forces Claude) are *constraints* the impl plan must respect when writing the mutator in Slice 3b — they are acknowledged in the "Critical Rules" but not explicitly cross-referenced to the Surprises.
- Surprise #8 (task_text repeatedly inlined in fix prompt) is uncited; Slice 2a's audit-fix Codex dispatch will inherit this behavior unchanged — acceptable under 1M context but worth noting.
- Wave 1a did not explicitly describe a Slice 1a safer-migration path (concatenate CLAUDE.md → `system_prompt_addendum`); impl plan goes straight to `setting_sources=["project"]`. Wave 1a §8 flagged this as a **semantic shift** — plan does not acknowledge that nuance.

---

## Check 1 — 9 Surprises Coverage

Wave 1a §Surprises lists 9 items. Per-Surprise verdict against the impl plan:

| # | Surprise (Wave 1a) | Impl Plan Coverage | Verdict |
|---|--------------------|--------------------|---------|
| 1 | `codex_transport_mode` declared but never consumed (cli.py:3182 hard-coded) | Slice 1b — cli.py:3182 transport selector, flag-gated on `codex_transport_mode` | COVERED — impl plan §"Slice 1b" lines 240-245 |
| 2 | `setting_sources=["project"]` never set; builder ignores generated-project CLAUDE.md | Slice 1a — `cli.py:~430` adds `setting_sources=["project"]` when `claude_md_setting_sources_enabled=True` | COVERED — impl plan lines 234-239 |
| 3 | `classify_fix_provider` (provider_router.py:481) exported, never called | Slice 2a — wire classifier at `cli.py:6441` branch on `classify_fix_provider()` result | COVERED — impl plan lines 284-293 |
| 4 | Wave T hard-bypasses `provider_routing` at wave_executor.py:3243-3260 | Not explicitly cited as a Surprise, but Slice 3b mutator design implicitly respects it (T is inserted before E, never re-routed); Slice 4b's T.5 is a NEW dispatch, not a modification to T | COVERED implicitly — impl plan §"Slice 3b" line 328, §"Slice 4b" lines 354-359 |
| 5 | D5 forces Claude regardless of caller's map (provider_router.py:39-41) | Slice 3 provider flip mentions "regardless of `provider_map_d`" at line 333, which mirrors the D5 pattern; D5 hard-pin preserved | COVERED implicitly — impl plan line 333 |
| 6 | No `MILESTONE_HANDOFF.md` writer/reader found | Slice 1c — ARCHITECTURE.md writer is the substitute (per-project cumulative doc) | COVERED — impl plan lines 246-255 |
| 7 | No project-level cumulative architecture document exists | Slice 1c — same as #6 | COVERED — impl plan lines 246-255 |
| 8 | Fix prompt inlines entire `task_text` (cli.py:6428) | NOT CITED — Slice 2a inherits this behavior unchanged | INFORMATIONAL gap — see Comments Index |
| 9 | `_n17_prefetch_cache` (cli.py:3976) is per-milestone, per-wave (B+D only) | Partially — Slice 5a/5b adds `mcp_doc_context` to Wave A + Wave T prompts, which would require extending prefetch; line 205 cites cli.py:3976 for Slice 5 | COVERED-partially — impl plan line 204 and 399-406 |

**Conclusion for Check 1:** 7/9 explicitly, 2/9 implicitly (#4, #5), 1/9 uncited (#8). No blocking gaps — #8 is acceptable-under-1M-context per Wave 1a's own note.

---

## Check 2 — Line Targets Accuracy (8 Samples Verified)

Verified against HEAD `466c3b9` via direct `Read` calls:

| # | Impl plan citation | HEAD source | Verdict |
|---|--------------------|-------------|---------|
| 1 | `cli.py:339-450` — `_build_options` + `opts_kwargs` at `:427-444` | `_build_options` located; `opts_kwargs` dict at cli.py:427-434 (dict literal); extra appends 436-449, `return ClaudeAgentOptions(**opts_kwargs)` at 450 | MATCH — exact |
| 2 | `cli.py:3182` — hard-coded Codex transport import | `import agent_team_v15.codex_transport as _codex_mod` at cli.py:3182 | MATCH — exact |
| 3 | `cli.py:9526-9531` — legacy `[SYSTEM:]` recovery branch | Comment at 9525-9528; `legacy_situation` with `[SYSTEM: ...]` at 9529-9533 | MATCH-approx — actual legacy block is 9525-9539 (impl plan cites 9526-9531 which covers the comment + opening of the block). Deletion target is the whole legacy branch, verbatim cited 9525-9539. |
| 4 | `config.py:863` — `recovery_prompt_isolation` field | `recovery_prompt_isolation: bool = True` at config.py:863 | MATCH — exact |
| 5 | `config.py:2566` — corresponding coerce | `recovery_prompt_isolation=_coerce_bool(` at config.py:2566 | MATCH — exact |
| 6 | `cli.py:6271` — `_run_audit_fix_unified` entry | `async def _run_audit_fix_unified(` at cli.py:6271 | MATCH — exact |
| 7 | `cli.py:6441` — ClaudeSDKClient call in patch mode | `async with ClaudeSDKClient(options=options) as client:` at cli.py:6441 | MATCH — exact |
| 8 | `provider_router.py:481-504` — `classify_fix_provider` | `def classify_fix_provider(` at provider_router.py:481; function body ends with `return "claude"` at line 504 | MATCH — exact |
| 9 (bonus) | `agents.py:8696` — `build_wave_d_prompt` | `def build_wave_d_prompt(` at agents.py:8696 | MATCH — exact |
| 10 (bonus) | `wave_executor.py:307-311` — `WAVE_SEQUENCES` | `WAVE_SEQUENCES = {` at line 307, body 308-310, close `}` at 311 | MATCH — exact |
| 11 (bonus) | `wave_executor.py:395-403` — `_wave_sequence` mutator | `def _wave_sequence(template, config)` at 395; body 396-402; `return waves` at 403 | MATCH — exact |
| 12 (bonus) | `wave_executor.py:~3295-3305` — compile-fix-then-rollback point | Compile gate `if wave_result.success and wave_letter in {"A", "B", "D", "D5"}:` at 3295 — but rollback branch is 3357-3375 (D5 ONLY). The 3295 region is the compile-gate, NOT rollback. | MATCH-approx — see Comments Index (NIT-1) |

**Conclusion for Check 2:** 11/12 exact matches. 1 approximate (item 12 — wording issue, not a line drift).

---

## Check 3 — CLAUDE.md + AGENTS.md Descriptions

**Wave 1a §8 ground truth:**
- Claude SDK auto-loads `CLAUDE.md` ONLY IF caller sets `setting_sources=["project"]` + `system_prompt={"type":"preset","preset":"claude_code"}` (Wave 1a §8 lines 721-732, verbatim Context7).
- `_build_options()` sets neither (Wave 1a §8 lines 762-777).
- Codex auto-loads `AGENTS.md` from CWD + ancestors automatically (Wave 1a §8 lines 738-755, verbatim Context7).
- Builder repo ships **no** CLAUDE.md and **no** AGENTS.md at root (Wave 1a §8 lines 680-698).
- Wave 1a §8 lines 790-808 notes two paths: (a) flip to `system_prompt={"type":"preset",...}` + `setting_sources=["project"]` (semantic shift), or (b) concatenate CLAUDE.md content into `system_prompt_addendum` (safer).

**Impl plan claims:**
- Slice 1a (lines 234-239): "add `setting_sources=["project"]` when `v18.claude_md_setting_sources_enabled=True`" — matches Wave 1a path (a).
- Slice 1d (lines 256-265): auto-generates CLAUDE.md + AGENTS.md + 32 KiB cap — matches Codex spec.
- Slice 5e (lines 413-415): `.codex/config.toml` with `project_doc_max_bytes = 65536` — matches Codex default cap raise.

**Accuracy assessment:**
- [CORRECT] `setting_sources=["project"]` semantics.
- [CORRECT] 32 KiB AGENTS.md cap (Wave 1a §8 does not cite this number explicitly — Codex docs cite 32 KiB default; impl plan treats it as known).
- [GAP / NIT-2] Impl plan Slice 1a does NOT mention `system_prompt={"type":"preset","preset":"claude_code"}`. Wave 1a §8 Query 2 shows the SDK requires BOTH `system_prompt` preset AND `setting_sources` to auto-load CLAUDE.md. If impl plan only sets `setting_sources` without flipping `system_prompt`, the hand-built system_prompt will still override — auto-load won't work.
- [GAP / NIT-3] Impl plan does not offer the safer alternative (concatenate into `system_prompt_addendum`). Wave 1a §8 called this out explicitly as the "safer migration" — impl plan picks the semantic-shift path without commentary.

---

## Check 4 — Provider Routing Assertions

**Wave 1a §2 ground truth (at HEAD `466c3b9`):**
- A=claude, B=codex, C=python, D=codex, D5=claude (forced), E=claude.
- Only `provider_map_b` + `provider_map_d` user-configurable.
- Wave T bypasses routing entirely.

**Impl plan "new routing table" (line 33):**
> A(Claude) → A.5(Codex medium) → Scaffold(Python) → B(Codex high) → C(Python) → D-merged(Claude) → T(Claude) → T.5(Codex high) → E(Claude) → Audit(Claude) → Fix(Codex high) → Compile-Fix(Codex high)

**Accuracy:**
- [CORRECT] A=Claude, B=Codex, C=Python, T=Claude, E=Claude — matches Wave 1a current map.
- [CORRECT] D-merged=Claude — matches Slice 3c's "force D to Claude when `wave_d_merged_enabled=True`" at line 331.
- [CORRECT] A.5=Codex medium, T.5=Codex high — NEW waves; no Wave 1a conflict.
- [CORRECT] Fix=Codex, Compile-Fix=Codex — Slices 2a/2b, wires `classify_fix_provider` + `compile_fix_codex_enabled`.
- [CORRECT] Audit=Claude — unchanged per Wave 1a §7 (audit loop is Claude-only; Slice 4's T.5 is pre-audit edge-case dispatch, not a new auditor).
- [INFORMATIONAL / INFO-1] Scaffold is listed as "Python" which is accurate per Wave 1a §1 ("Python-only... No LLM dispatch") but the impl plan inserts it between A and A.5 — Wave 1a doesn't describe scaffold explicitly in the wave sequence (scaffold phase is part of the orchestrator's setup, not a wave). This is a restructure Wave 1a didn't evaluate. Not a drift vs Wave 1a; just scope-new.

---

## Check 5 — Fix Routing Assertions (Slice 2a `classify_fix_provider`)

**Wave 1a §3 ground truth:**
- `provider_router.classify_fix_provider()` at provider_router.py:481-504 — exists, uses issue-type + file-path heuristics, returns `"codex"` or `"claude"`.
- Verified by `grep classify_fix_provider`: only the definition and export; **no call site in cli.py**.

**Source verification at HEAD `466c3b9`:**
- `provider_router.py:481`: `def classify_fix_provider(affected_files: list[str], issue_type: str) -> str:` — confirmed.
- Body returns "codex" / "claude" per keyword scoring — confirmed at lines 487-504.
- cli.py:6441: `async with ClaudeSDKClient(options=options) as client:` — confirmed no classifier branch.

**Impl plan Slice 2a claims:**
- Line 286: "branch on `classify_fix_provider()` result when `v18.codex_fix_routing_enabled=True`"
- Line 288: "Wire `provider_router.py:481-504` `classify_fix_provider()` — it's exported but never called; now it gets called"

**Verdict:** [CORRECT] — matches Wave 1a §3 exactly. The claim "exported but never called" is verified true at HEAD `466c3b9`.

---

## Check 6 — LOCKED Wording File:Line

**Wave 1a + Wave 5a both verified these at HEAD `466c3b9`. Independent verification:**

| Locked item | Impl plan citation | HEAD content | Verdict |
|-------------|--------------------|--------------|---------|
| IMMUTABLE packages/api-client block | `agents.py:8803-8808` | agents.py:8803 starts with "For every backend interaction..."; extends through `[INTERPRETATION]` block at 8805-8808. The full IMMUTABLE paragraph is line 8803 (one long sentence); lines 8804-8808 are the `[INTERPRETATION]` supporting block. | CORRECT-approx — the IMMUTABLE sentence is 8803 alone; 8804-8808 is related but distinct `[INTERPRETATION]` (NIT-4). |
| WAVE_T_CORE_PRINCIPLE | `agents.py:8374-8388` | `WAVE_T_CORE_PRINCIPLE = (` at 8374; closing `)` at 8388; body is the test-writing principle | MATCH — exact |
| _ANTI_BAND_AID_FIX_RULES | `cli.py:6168-6193` | `_ANTI_BAND_AID_FIX_RULES = """[FIX MODE - ROOT CAUSE ONLY]` at 6168; closes at line 6193 with the STRUCTURAL note | MATCH — exact |

**Verdict:** 2/3 exact, 1/3 approximate-but-not-broken (IMMUTABLE citation covers the `[INTERPRETATION]` block as well, which is arguably "LOCKED adjacent" — the Codex Wave-D suffix at codex_prompts.py:231 also locks this via "Zero edits to `packages/api-client/*`"). Verbatim copy instructions will still work because the impl agent copy-pastes the whole block.

---

## Check 7 — Team Structure Feasibility from 1a Perspective

**Wave 1a did not prescribe the implementation team structure.** The impl plan's 8-agent team across 7 waves is novel.

**Feasibility check (using Wave 1a's understanding of which files share surface area):**

1. **Slice 3 and Slice 4 both touch `agents.py` and `wave_executor.py`** (impl plan lines 111-114). Wave 1a confirms this is real:
   - Slice 3 touches `agents.py:8696-8858` (Wave D builder), `wave_executor.py:307-311` (WAVE_SEQUENCES), `wave_executor.py:395-403` (mutator).
   - Slice 4 touches `wave_executor.py:~3250-3260` (new A.5/T.5 dispatch insertion), `agents.py` (new prompt functions near existing `build_wave_*_prompt` — Wave 1a locates these at 7750 / 7909 / 8147 / 8391 / 8696 / 8860).
   - Line-range overlap: Slice 3's `agents.py:8696-8858` (Wave D) is distinct from Slice 4's new prompts inserted near existing builders. NO BLOCKING overlap.
   - `wave_executor.py`: Slice 3 at 307-403, Slice 4 at ~3250+. NO overlap.
   - **Conclusion: Parallel execution is feasible per Wave 1a's line topology.**

2. **Slice 1 and Slice 2 parallelism**: Slice 2 waits for Slice 1b (transport selector). Slice 1b is cli.py:3182 edit; Slice 2a is cli.py:6441 edit + uses the selector. Wave 1a confirms these are independent call sites (lines 249-263 vs. §3 fix path). Serial dependency is correct.

3. **Slice 5 waits for Slice 4** (T.5 dispatch must exist for gap fan-out). Wave 1a §7 note (line 664) confirms T.5 would be a new dispatch consumed by Wave E prompt + TEST_AUDITOR — ordering is correct.

4. **Wave 1 line-map verifier agent** reads every target from Part 7. Wave 1a's file:line index (Appendix A, lines 842-1108) is the source of truth for the verifier. The architecture-discoverer's task (impl plan lines 156-208) covers every site Wave 1a cited — **no blind spots**.

**Verdict:** Team structure is feasible per Wave 1a's line topology. No blocking concerns.

---

## Comments Index

Format: `[SEVERITY] — <impl plan line> — <comment> — <source citation>`

1. **[NIT-1] — line 191 ("compile-fix-then-rollback")** — Impl plan says `wave_executor.py:~3295-3305` is the "compile-fix-then-rollback point". At HEAD `466c3b9`, line 3295 is the compile-gate START (`if wave_result.success and wave_letter in {"A", "B", "D", "D5"}:`). The actual rollback is at `wave_executor.py:3357-3375` (D5-only). Impl plan conflates "compile gate" with "compile-fix-then-rollback". Recommend: "wave_executor.py:~3295 (compile gate start) + 3357-3375 (D5 rollback)". — Source: Wave 1a §1 line 101, verified at HEAD.

2. **[NIT-2] — lines 234-239 (Slice 1a)** — Impl plan adds `setting_sources=["project"]` but does NOT flip `system_prompt` to `{"type":"preset","preset":"claude_code"}`. Per Wave 1a §8 Query 2 verbatim Context7 snippet, BOTH are required for CLAUDE.md auto-load. If only `setting_sources` is added, the hand-built `system_prompt` (cli.py:390-408) will continue to override and auto-load will NOT activate. Recommend: add `system_prompt` flip to Slice 1a, OR explicitly document that CLAUDE.md is consumed via `system_prompt_addendum` concatenation (Wave 1a §8 "safer alternative", line 806). — Source: Wave 1a §8 lines 721-732, 790-808.

3. **[NIT-3] — lines 234-239 (Slice 1a)** — The impl plan doesn't acknowledge Wave 1a's explicit note that switching `system_prompt` to the preset is a "semantic shift, not a pure addition" (Wave 1a line 804). This is worth a one-line comment in the impl plan — impl agent should know this changes behavior even with the flag OFF's complement (flag ON = preset replaces hand-built prompt). — Source: Wave 1a §8 lines 800-808.

4. **[NIT-4] — lines 206-208 (LOCKED wording check in Wave 1)** — Impl plan cites `agents.py:8803-8808` for IMMUTABLE. At HEAD `466c3b9`, line 8803 is the IMMUTABLE sentence (one long line); 8804-8808 is the separate `[INTERPRETATION]` block that elaborates on the rule. They are adjacent but semantically distinct. Recommend: cite `agents.py:8803` for IMMUTABLE proper, with `agents.py:8803-8808` acceptable as the "IMMUTABLE-plus-interpretation" bundle. No functional impact on the impl agent (copy-paste still works). — Source: Wave 1a §6 line 551, verified at HEAD.

5. **[INFORMATIONAL — INFO-1] — line 33 (routing table)** — Scaffold is listed between A and A.5 as "Python". Wave 1a describes scaffold-phase separately from the wave pipeline (Wave 1a §4 refers to `run_scaffolding` callback at cli.py). The impl plan treats scaffold as a pipeline slot, which is a reasonable restructure but NOT something Wave 1a endorsed or evaluated. Impl agents should note this is scope-new, not Wave-1a-derived. — Source: Wave 1a §1 (no scaffold entry in `WAVE_SEQUENCES`).

6. **[INFORMATIONAL — INFO-2] — Slice 2a (lines 284-293)** — Surprise #8 from Wave 1a (line 1294-1297) flags that the fix prompt re-inlines the entire `task_text` (the full PRD) at cli.py:6428. Slice 2a will inherit this behavior when routing to Codex — no impact under 1M context, but worth noting the audit-fix Codex prompt is going to be large. Impl agent should verify Codex can consume the full PRD within Codex's context window (not Claude's 1M). — Source: Wave 1a Surprise #8.

7. **[INFORMATIONAL — INFO-3] — Slice 5a-b (lines 398-406)** — Slice 5 extends `mcp_doc_context` to Wave A + Wave T prompts. Wave 1a Surprise #9 (line 1299-1301) notes `_n17_prefetch_cache` at cli.py:3976 is B+D only. Slice 5 will need the cache broadened to A+T (impl plan line 204 cites cli.py:3976 for Slice 5, so the author is aware — just not cross-referenced to Surprise #9). — Source: Wave 1a Surprise #9.

---

## Summary

- **Verdict:** PASS-with-comments.
- **Load-bearing accuracy:** 100%. All LOCKED-wording file:line citations verified. All 8 spot-checked line targets match HEAD `466c3b9`.
- **Coverage of 9 Surprises:** 7/9 explicit, 2/9 implicit (#4, #5), 1/9 uncited but non-blocking (#8).
- **CLAUDE.md/AGENTS.md semantics:** Accurate but Slice 1a may need `system_prompt` preset flip (NIT-2) to actually activate auto-load.
- **Provider routing & fix routing:** Accurate. `classify_fix_provider` "exported but never called" claim is verified.
- **Team structure:** Feasible per Wave 1a's line topology; Slice 3 / Slice 4 parallel execution safe.
- **No blocking drifts.** Address NIT-1, NIT-2, NIT-3 as light edits during impl kick-off; NIT-4 and INFO-1/2/3 are advisory.
