# Phase G — Wave 7d — Impl Plan Review vs Wave 2a Findings

**Reviewer:** `impl-review-wave2a` (Task #14)
**Target:** `PHASE_G_IMPLEMENTATION.md` (587 lines)
**Ground truth:** `docs/plans/2026-04-17-phase-g-pipeline-design.md` (Wave 2a, 1377 lines)
**Also consulted:** `docs/plans/2026-04-17-phase-g-investigation-report.md` Part 7 (contract absorbing R1–R10)
**Mandate:** "PERFECT and ACCURATE."

---

## Executive Summary

The implementation plan is **substantially accurate** against Wave 2a + R1–R10
resolutions. All 10 major resolutions (R1–R10) are represented. The five
slices match Wave 2a §9 / investigation-report Part 7 dependency graph and LOC
estimates.

**Findings: 1 BLOCKING, 7 NITs, 3 INFOs.**

The single BLOCKING item is a **flag-count miscount** in the Exit Criteria:
line 539 of the impl plan states "All 23 feature flags in config.py" but the
authoritative §7.7 flag table enumerates **30 flags** (22 original Wave 2a
§8.1 + 7 R9 additions + 1 that leaked from Wave 2a §5c.6 — `agents_md_max_bytes`).
Wave 2a §8.1 table has 22 entries; Part 4.11 R9-expanded table has 29; Part 7.7
has 30. The impl plan's "23" does not match any of the three.

Seven NITs concern minor inconsistencies in slice dependencies vs. Part 7 graph,
unstated dispatcher gate wiring, and coordination notes that could mislead
implementers. Three INFOs flag places where the impl plan could be tightened
but are not wrong.

---

## Check 1 — New Wave Sequences

**Impl plan line 33:**
`A(Claude) → A.5(Codex medium) → Scaffold(Python) → B(Codex high) → C(Python) → D-merged(Claude) → T(Claude) → T.5(Codex high) → E(Claude) → Audit(Claude) → Fix(Codex high) → Compile-Fix(Codex high)`

**Wave 2a §4.1 (lines 52-57) full table:**
- `full_stack`: A → **A.5** → Scaffold → B → C → **D (merged)** → T → **T.5** → E
- `backend_only`: A → **A.5** → Scaffold → B → C → T → **T.5** → E
- `frontend_only`: A → Scaffold → **D (merged)** → T → **T.5** → E

**Verdict:** Impl plan line 33 shows the full routing table (all LLM+provider
pairs) but only implicitly references `full_stack`. The three-template variant
is never surfaced as an implementation deliverable. The slice 3b description
(line 326-328) says "add A5/T5 entries (gated by flag)" without specifying
**per-template** treatment.

**NIT #1 [line 328]:** Slice 3b specification should enumerate all three
templates per Wave 2a §1.2 (the literal `WAVE_SEQUENCES` constant). The impl
plan risks the implementer forgetting to update `backend_only` or `frontend_only`.

---

## Check 2 — Slice Definitions Match Wave 2a Design

### Slice 1a — setting_sources
- **Impl plan line 234-239**: `cli.py:~430` add `setting_sources=["project"]` when flag on, plus new `claude_md_setting_sources_enabled` flag.
- **Wave 2a §5b.2 + Part 7.1 Slice 1a**: same.
- **Verdict:** MATCH.

### Slice 1b — transport selector
- **Impl plan line 240-244**: `cli.py:3182` replace hard-coded import with flag-gated branch; uses existing `codex_transport_mode`.
- **Wave 2a §4.3 + Part 7.1 Slice 1b**: same.
- **Verdict:** MATCH.

### Slice 1c — ARCHITECTURE.md writer
- **Impl plan line 246-254**: NEW `architecture_writer.py` with 3 helpers, 2 hooks at `~3150` and `~3542-3548`, 3 new flags.
- **Wave 2a §5a.3-5a.8 + Part 7.1 Slice 1c**: same.
- **Verdict:** MATCH.

### Slice 1d — CLAUDE.md + AGENTS.md renderers
- **Impl plan line 256-264**: NEW `constitution_templates.py` + `constitution_writer.py`, 3 flags, 32 KiB cap.
- **Wave 2a §5b.5 + §5c.5 + Part 7.1 Slice 1d + R8 (invariants)**: same, plus Part 4.6/4.7 invariants requirement.
- **Verdict:** MATCH. Good call-out of "3 canonical invariants per R8" at line 259.

### Slice 1e — Recovery kill (per R2)
- **Impl plan line 266-274**: DELETE `cli.py:9526-9531`, `config.py:863`, `config.py:2566`. Non-flag-gated.
- **Wave 2a §3-updated + Part 7.2 (per R2)**: same.
- **Verdict:** MATCH.

### Slice 2a — Audit-fix classifier wire-in
- **Impl plan line 284-294**: `cli.py:6441` branch, new `_dispatch_codex_fix`, 3 flags.
- **Wave 2a §4.2 + §4.8 + Part 7.1 Slice 2a**: same.
- **Verdict:** MATCH.

### Slice 2b — Compile-fix Codex (per R1)
- **Impl plan line 296-302**: `wave_executor.py:2391` rewrite `_build_compile_fix_prompt`, thread `_provider_routing` at 2888, new `compile_fix_codex_enabled` flag.
- **Wave 2a (NEW per R1) + Part 7.3 + Part 7.1 Slice 2b**: same.
- **Verdict:** MATCH.

### Slice 3 — Wave D merge
- **Impl plan line 316-336**: 3a merged prompt builder, 3b WAVE_SEQUENCES update, 3c provider flip D→Claude, 3d compile-fix-then-rollback.
- **Wave 2a §3 + Part 7.1 Slice 3**: same.
- **Verdict:** MATCH.

### Slice 4 — Wave A.5 + T.5 + GATE 8/9
- **Impl plan line 346-382**: 4a A.5 dispatch, 4b T.5 dispatch, 4c sequences (coordinated with 3b), 4d hooks, 4e GATE 8/9.
- **Wave 2a §6, §7 + Part 7.1 Slice 4 + R4 (gates)**: same.
- **Verdict:** MATCH.

### Slice 5 — Prompt integration wiring (per R10)
- **Impl plan line 398-422**: 5a/5b `mcp_doc_context` into A/T, 5c/5d T.5 gap injection into E + TEST_AUDITOR, 5e .codex/config.toml bundle.
- **Wave 2a §4.11 additions + Part 7.1 Slice 5 + R10**: same.
- **Verdict:** MATCH.

---

## Check 3 — Wave D Merge Specification

**Impl plan Slice 3a (line 318-324):**
- Extend `build_wave_d_prompt` with `merged: bool = False`.
- Combine D functional wiring + D.5 design tokens + polish rules.
- Use EXACT prompt text from Part 5.4 of investigation report.
- IMMUTABLE block transfers VERBATIM.
- REMOVE Codex autonomy directives.
- REMOVE D.5's "don't change functionality" restriction.

**Wave 2a §3.1 KEPT:** `[GENERATED API CLIENT]`, `[CODEBASE CONTEXT]`, `[STATE
COMPLETENESS]`, `[I18N]`, `[RTL]`, `[RULES]` incl. IMMUTABLE (LOCKED),
`[FILES YOU OWN]`, `[CURRENT FRAMEWORK IDIOMS]`.

**Wave 2a §3.2 KEPT from D.5:** `[APP CONTEXT]`, `[DESIGN SYSTEM]`,
`[DESIGN STANCE]`, `[PRESERVE FOR WAVE T AND WAVE E]` (renamed
`[TEST ANCHOR CONTRACT]`), `[YOU CAN DO]`, `[PROCESS]`, `[VERIFICATION]`,
`[CODEX OUTPUT TOPOGRAPHY]` (renamed `[EXPECTED FILE LAYOUT]`).

**Wave 2a §3.3 DROPPED:**
- `CODEX_WAVE_D_PREAMBLE` (wholly).
- `CODEX_WAVE_D_SUFFIX` (fold IMMUTABLE reiteration into main rules).
- D.5's `[YOU MUST NOT DO]` narrow restriction.

**Verdict:** The impl plan's "REMOVE Codex autonomy directives" (line 323)
and "REMOVE D.5's don't change functionality restriction" (line 324) both
trace correctly to Wave 2a §3.3. BUT:

**NIT #2 [line 322]:** "IMMUTABLE block at `agents.py:8803-8808` transfers
VERBATIM" is consistent with Wave 2a §3.1 + §3.3 second bullet (fold
CODEX_WAVE_D_SUFFIX IMMUTABLE reiteration into main rules block — so there's
ONE IMMUTABLE, not two). Impl plan line 322 only asserts verbatim transfer
but doesn't warn against duplicating. Risk: implementer copies both sources,
IMMUTABLE appears twice.

**NIT #3 [line 318-324]:** Impl plan omits the D.5-only `[TEST ANCHOR
CONTRACT]` rename (Wave 2a §3.2 bullet 4) and the `[CODEX OUTPUT TOPOGRAPHY]`
→ `[EXPECTED FILE LAYOUT]` rename (Wave 2a §3.2 final bullet). These
renames are load-bearing for Wave T / E anchor preservation and should
appear as explicit sub-bullets under 3a.

**BLOCKING? No** — impl plan defers to "Part 5.4 of investigation report" for
EXACT prompt text, which has the full spec. But the slice-3a summary risks
underspecifying if the implementer treats Part 5.4 as reference rather than
contract.

---

## Check 4 — ARCHITECTURE.md Two-Doc Model (per R3)

**Impl plan Slice 1c (line 246-254):**
- NEW `architecture_writer.py` with `init_if_missing()`, `append_milestone()`, `summarize_if_over()`.
- Hook at `wave_executor.py:~3150` before M1 dispatch (`init_if_missing(cwd)`).
- Hook at `wave_executor.py:~3542-3548` alongside `persist_wave_findings_for_audit()` (`append_milestone()`).
- "Content template from Part 4.5 of the investigation report."

**Wave 2a §5a** = original ONE-DOC model (cumulative `<cwd>/ARCHITECTURE.md`).
**R3 resolution** = TWO complementary docs:
1. **Per-milestone** `.agent-team/milestone-{id}/ARCHITECTURE.md` written by Wave A (Claude); injected as `<architecture>` XML tag into B/D/T/E prompts of same milestone.
2. **Cumulative** `<cwd>/ARCHITECTURE.md` built by python helper; injected as `[PROJECT ARCHITECTURE]` block into M2+ wave prompts.

**Verdict:** The impl plan's Slice 1c description **ONLY covers the
cumulative path** (python-side helper). It does NOT mention the
per-milestone doc written by Wave A. This is a **BLOCKING omission** for
the R3 two-doc model.

**BLOCKING #1 [line 246-254 / Slice 1c]:** Per R3, ARCHITECTURE.md is
**two complementary files**, not just the python-rendered cumulative one.
The per-milestone doc is written by Wave A (Claude) as part of its MUST
(per investigation report Part 5.1 prompt rules at line 1729: *"add `write
.agent-team/milestone-{id}/ARCHITECTURE.md` MUST (per R3)"*). The impl
plan's Slice 1c should explicitly distinguish:
- (a) python-side cumulative doc (Slice 1c deliverable — helper + hooks)
- (b) per-milestone doc (Wave A prompt MUST — Slice 5a / Part 5.1 deliverable)

Without this distinction, the implementer will build only (a) and miss (b).
Part 7.4 of the investigation report (line 3364-3377) makes this explicit;
the impl plan skips the split.

Also: **NIT #4 [line 254]:** "Content template from Part 4.5 of the
investigation report" — Part 4.5 is the cumulative doc template only.
The per-milestone doc uses a different shape (XML-injected inline context
per R3); Part 7.4 line 3368 clarifies the per-milestone path vs cumulative
path. Impl plan should cite "Part 4.5 AND Part 7.4" or "Parts 4.5 + 5.1"
to cover both.

---

## Check 5 — Flag Plan Completeness

**Impl plan line 476:** "(all 23 from Part 7 §7.7)"
**Impl plan line 539:** "All 23 feature flags in config.py with correct defaults (Part 7 §7.7)"

**Wave 2a §8.1** (lines 1106-1128): 22 flags listed.
**R9 additions** (integration-verification resolution, in investigation
report §4.11 lines 1690-1696): **7 additional flags**:
1. `compile_fix_codex_enabled` (R1/R9)
2. `wave_a5_gate_enforcement` (R4/R9)
3. `wave_t5_gate_enforcement` (R4/R9)
4. `mcp_doc_context_wave_a_enabled` (R10/R9)
5. `mcp_doc_context_wave_t_enabled` (R10/R9)
6. `wave_t5_gap_list_inject_wave_e` (R5/R9)
7. `wave_t5_gap_list_inject_test_auditor` (R5/R9)

**Wave 2a §8.1 + R9 = 22 + 7 = 29 flags in §4.11 table.**

**Investigation report §7.7 (Part 7.7)** enumerates **30 flags** — same 29
as §4.11 PLUS `agents_md_max_bytes: int = 32768` (Slice 1d), which was
declared in Wave 2a §5c.6 but absent from Wave 2a §8.1 and §4.11. So §7.7
is internally inconsistent with §4.11 by one flag, but §7.7 is the contract
the impl plan cites.

**BLOCKING #2? No — classified BLOCKING #1a:**

**BLOCKING #1a [line 476, line 539]:** "23" is **incorrect** against all
three possible counts:
- Wave 2a §8.1 = 22
- §4.11 (R9-expanded) = 29
- §7.7 (impl contract) = 30

The correct number per the source the impl plan cites (§7.7) is **30**.
If `agents_md_max_bytes` is excluded (matching §4.11), it's **29**. Neither
equals 23. The exit-criteria check at line 539 will not verify the full
set; the implementer may ship with 7+ missing flags and still "pass" the
checklist. **Update to 30** (aligning with §7.7, the impl plan's declared
contract).

---

## Check 6 — Slice Dependencies

**Impl plan claims:**
- Line 102: "Slice 2 depends on Slice 1b (transport selector)." ✓ Matches Wave 2a §9.1 + Part 7.1.
- Line 116: "Slice 5 depends on Slice 4b (T.5 dispatch must exist for gap fan-out)" ✓ Matches Part 7.1 Slice 5 dep `[depends on 4b]` for 5c/5d.
- Line 233 implied: Slice 1d depends on 1a (inside slice1-foundations-impl). ✓ Matches §9.1.
- Line 233 implied: Slice 1e depends on 1a. ✓ Matches Part 7.1 dependency graph.

**Part 7.1 dep graph** (investigation-report lines 2970-3017):
- Slice 2a depends on 1b.
- **Slice 2b depends on 1b AND 2a** (Part 7.1 line 2986).
- Slice 4a depends on 1b.
- Slice 4b depends on 1b.
- Slice 5c/5d depend on 4b.

**Verdict:** Impl plan has the right dep for 2a→1b but is silent on 2b→2a.

**NIT #5 [line 276-302]:** Slice 2b's dependency on Slice 2a is not stated.
Part 7.1 Slice 2b line 3208 says *"Dependencies: Slice 1b (transport
selector) + Slice 2a (audit-fix routing foundation provides the
`_dispatch_codex_fix` helper that compile-fix can reuse or mirror)."*
Impl plan assigns both 2a and 2b to the same `slice2-codex-fix-impl` agent
(line 64) and implicitly orders 2a before 2b, but does not document why.
Future refactors that split the agent could inadvertently parallelize.

**NIT #6 [line 194]:** Wave 1 line map includes Slice 4 line target
`wave_executor.py:~3250` for A.5 AND `wave_executor.py:~3260` for T.5. Both
are in the same stretch of `execute_milestone_waves`. If both sites are
within ~10 LOC of each other and Slice 3b also modifies that region
(sequence mutator), the impl plan's "DIFFERENT sections" claim at line
111-114 needs explicit line-range proof. This is the same coordination
issue called out at 4c line 360. Consider adding line-range bounds to the
line map.

---

## Check 7 — GATE 8/9 Enforcement

**Impl plan Slice 4e (line 364-367):**
- GATE 8 after A.5: if `wave_a5_gate_enforcement=True` AND verdict FAIL + CRITICAL → re-run Wave A with feedback → re-run A.5 → block Wave B if persists.
- GATE 9 after T.5: if `wave_t5_gate_enforcement=True` AND CRITICAL gaps → loop to Wave T iteration 2 → re-run T.5 → block Wave E if persists.

**Wave 2a §6.5** (plan gating, original spec) + **R4** spec + **Part 7.5**
pseudocode (lines 3378-3418):

Part 7.5 GATE 8 pseudocode enforces:
1. Re-run Wave A with `[PLAN REVIEW FEEDBACK]`.
2. Decrement `wave_a_reruns_remaining`.
3. If exhausted → raise `GateEnforcementError` → block Wave B.

Bound: `wave_a5_max_reruns=1` (Wave 2a §6.9 flag), matching impl plan Slice
4 flag config at line 374.

**Verdict:** MATCH (in substance).

**NIT #7 [line 366-367]:** "re-run Wave A with feedback → re-run A.5 →
block Wave B if persists" — phrasing compresses three steps into one arrow.
Part 7.5 is more specific: on rerun-exhaust, raise
`GateEnforcementError`. The impl plan should reference Part 7.5
pseudocode explicitly so the implementer knows the exact failure-mode
(exception, not silent skip). Same for GATE 9.

---

## Check 8 — Slice LOC Estimates

**Impl plan line 22-30:**
| Slice | LOC |
|-|-|
| 1 (Foundations, 1a+1b+1c+1d+1e) | ~505 |
| 2 (Codex fix routing, 2a+2b) | ~260 |
| 3 (Wave D merge) | ~300 |
| 4 (A.5 + T.5 + GATE 8/9) | ~450 |
| 5 (Prompt wiring) | ~180 |
| **Total** | **~1,695** |

**Investigation-report §4 LOC table (lines 132-144):**
| Slice | LOC |
|-|-|
| 1a | ~10 |
| 1b | ~15 |
| 1c | ~200 |
| 1d | ~250 |
| 1e | ~30 |
| **Sum 1a–1e** | **~505** ✓ |
| 2a | ~120 |
| 2b | ~140 |
| **Sum 2a–2b** | **~260** ✓ |
| 3 | ~300 ✓ |
| 4 | ~450 ✓ |
| 5 | ~180 ✓ |
| **Total** | **~1,695 LOC** ✓ |

**Verdict:** MATCH exactly. No nit.

---

## Additional Findings

### INFO #1 — Wave 2a §9 implementation-order and the 1a→1e dep
Wave 2a §9.1 (line 1164-1200 graph) puts Slice 1e under the Slice 1
block with "no deps". Part 7.1 (post-R2) updates 1e to "depends on 1a".
Impl plan agent-structure at line 232 correctly orders "1d (depends on 1a)
→ 1e (depends on 1a)". Impl plan follows R2, not Wave 2a §9.1 pre-R2.
This is correct per the contract but worth noting the divergence.

### INFO #2 — Slice 3b and `_wave_sequence` mutator triple coordination
Impl plan Slice 3b (line 326-328) and Slice 4c (line 360) both touch
`wave_executor.py:395-403`. Line 360 says "coordinated with Slice 3b (same
files — team lead verifies edit ranges)". This coordination note is
**correct but thin**. Wave 2a §1.2 specifies the final mutator strips
`A5` / `T5` / `D5` by three separate flag checks — the impl plan could
add a note that 3b owns the D5-strip branch and 4c adds A5/T5-strip
branches, to avoid edit-range collisions.

### INFO #3 — Slice 5e .codex/config.toml bundled via Slice 1d writer
Impl plan line 414 says "Bundle via `constitution_writer.py` (Slice 1d):
write `.codex/config.toml` with `project_doc_max_bytes = 65536`". This is
the correct R10+R9 resolution per Part 7.1 Slice 5 line 3306-3315. But
Slice 1d description at line 256-264 doesn't mention Slice 5e coupling.
Cross-reference would help implementer avoid missing the hook.

---

## Comments Index [BLOCKING/NIT/INFO]

| Severity | Line(s) | Reference | Comment |
|---|---|---|---|
| **BLOCKING** | 246-254 | Wave 2a §5a + R3 + Part 7.4 | Slice 1c ONLY covers cumulative ARCHITECTURE.md; omits per-milestone doc written by Wave A (R3 two-doc model). Add explicit (a) python cumulative + (b) Wave A per-milestone split. |
| **BLOCKING** | 476, 539 | Wave 2a §8.1 (22) + R9 (+7) + §7.7 (30) | "23" flags is wrong. Correct count per cited §7.7 is **30** (or 29 if `agents_md_max_bytes` excluded). Update both lines. |
| NIT #1 | 328 | Wave 2a §1.2 | Slice 3b should enumerate all three templates (`full_stack`, `backend_only`, `frontend_only`) per `WAVE_SEQUENCES` update spec. |
| NIT #2 | 322 | Wave 2a §3.1 + §3.3 | IMMUTABLE "transfers VERBATIM" should include anti-duplication warning (CODEX_WAVE_D_SUFFIX reiteration folded into main rules). |
| NIT #3 | 318-324 | Wave 2a §3.2 | Missing `[TEST ANCHOR CONTRACT]` rename and `[EXPECTED FILE LAYOUT]` rename under Slice 3a summary. |
| NIT #4 | 254 | Part 4.5 + Part 7.4 | "Content template from Part 4.5" is cumulative-only; per-milestone doc requires Part 7.4 / 5.1 rules. Expand reference. |
| NIT #5 | 276-302 | Part 7.1 Slice 2b | Slice 2b→Slice 2a dependency not stated. Document reason (2b reuses 2a's `_dispatch_codex_fix` helper). |
| NIT #6 | 111-114, 194-196 | Wave 2a §1.2 + §6.5 + §7.5 | "DIFFERENT sections" claim for Slice 3 vs 4 in `wave_executor.py:~3250-3260` needs explicit line-range bounds in the Wave 1 line map. |
| NIT #7 | 366-367 | Part 7.5 pseudocode | GATE 8/9 enforcement mechanism (`GateEnforcementError`) should be named, not just "block Wave B". |
| INFO #1 | 232, dep graph | R2 | 1e → 1a dep is post-R2; Wave 2a §9.1 pre-R2 had 1e as no-deps. Impl plan correctly follows post-R2 contract. |
| INFO #2 | 360 | Wave 2a §1.2 | `_wave_sequence` mutator is triple-owned (3b, 4c, recovery of D5-strip). Expand coordination note. |
| INFO #3 | 414 | Part 7.1 Slice 5e | Cross-ref Slice 5e bundling to Slice 1d writer would help implementer. |

---

## Recommendation

1. **Fix BLOCKING #1 (R3 two-doc split in Slice 1c).** Expand Slice 1c to
   explicitly list (a) python cumulative + (b) Wave A per-milestone doc.
   Without this, R3 will not be implemented completely.
2. **Fix BLOCKING #1a (23 → 30 flag count).** Update impl plan lines 476
   and 539 to "30 feature flags" (or audit §7.7 to remove
   `agents_md_max_bytes` if intentionally dropped, then update to "29").
3. Address NITs #1–#7 as inline edits to the affected sections for
   clarity; none block execution on their own.

All matches are otherwise clean. Slice scope, provider routing, LOC
estimates, dep-graph, GATE 8/9 enforcement logic, flag names/defaults, and
LOCKED wording treatment all reconcile with Wave 2a + R1–R10.

---

**Reviewer:** `impl-review-wave2a`
**Deliverable:** `docs/plans/2026-04-17-phase-g-implplan-review-wave2a.md`
**Status:** Complete
