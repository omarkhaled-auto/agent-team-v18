# Phase G — Wave 7b — Impl Plan Review vs Wave 1b Findings

**Date:** 2026-04-17
**Reviewer:** `impl-review-wave1b` (team `phase-g-investigation`)
**Target:** `PHASE_G_IMPLEMENTATION.md` (587 lines, HEAD `466c3b9`)
**Ground truth:** `docs/plans/2026-04-17-phase-g-prompt-archaeology.md` (Wave 1b, 1051 lines)
**Companion:** `docs/plans/2026-04-17-phase-g-investigation-report.md` (Parts 5.X + Part 7)

---

## Executive Summary

**Verdict: APPROVE WITH 2 NITS.** The impl plan faithfully carries Wave 1b's findings into Part 7 contract execution. Every cross-prompt finding has a resolution path in the master report. Build evidence citations (BUILD_LOG:837-840, BUILD_LOG:1502-1529) match exactly. LOCKED-wording line targets (`agents.py:8803-8808`, `agents.py:8374-8388`, `cli.py:6168-6193`) verified verbatim against current code.

**Drift counts:**
- BLOCKING: 0
- NIT: 2 (off-by-one-line drift on recovery citation; one inherited paraphrase risk flagged — not a drift)
- INFO: 3

---

## Check 1 — Build evidence citation accuracy

**Line 28:** "Single Claude frontend wave (eliminates D.5, fixes build-j orphan-tool wedge)."

- Wave 1b Part 1 `build_wave_d_prompt`:192 / Part 8 table row 965 cites `build-j BUILD_LOG.txt:837-840`: *"Wave D (Codex) orphan-tool wedge detected on command_execution (item_id=item_8), fail-fast at 627s idle (budget: 600s)."*
- I verified the BUILD_LOG at offset 837: `[Wave D] orphan-tool wedge detected on command_execution (item_id=item_8), fail-fast at 627s idle (budget: 600s)`.
- Impl plan's claim "eliminates D.5, fixes build-j orphan-tool wedge" is accurate. The wedge was a Codex persistence failure on Wave D; the merge flips provider to Claude (Slice 3c) and eliminates Codex-persistence as a class.
- **PASS.**

**Line 274:** "Build-j BUILD_LOG:1502-1529 is the direct evidence: Claude refused the `[SYSTEM:]` pseudo-tag as injection."

- Wave 1b Part 3 `_build_recovery_prompt_parts`:644 cites `build-j BUILD_LOG.txt:1502-1529`. Wave 1b evidence table (row 973) also uses `1502-1529`.
- Verified BUILD_LOG at offsets 1502-1530: Claude's refusal explicitly cites *"this is the **first message in our conversation**"* and identifies the `[SYSTEM: ...]` labels as user-message labels, not real system instructions.
- Impl plan's citation matches Wave 1b exactly.
- **PASS.**

## Check 2 — Prompt text reference existence (Part 5.X in master)

Every Part 5.X cited by the impl plan **exists** in `docs/plans/2026-04-17-phase-g-investigation-report.md`:

| Impl plan line | Citation | Master report line | Exists? | Usable prompt text? |
|---|---|---|---|---|
| 302 | Part 5.8 (compile-fix Codex) | 2189 | ✓ | ✓ (flat rules + `<missing_context_gating>` + LOCKED anti-band-aid + `output_schema`) |
| 293 | Part 5.9 (audit-fix Codex) | 2265 | ✓ | ✓ (Codex high, patch-mode only, LOCKED `_ANTI_BAND_AID_FIX_RULES`) |
| 321 | Part 5.4 (merged Wave D) | 1898 | ✓ | ✓ (XML-structured body with LOCKED IMMUTABLE, `<visual_polish>`, test-anchor preservation, `blockers[]`) |
| 349 | Part 5.2 (Wave A.5) | 1791 | ✓ | ✓ (Codex medium plan-review prompt) |
| 356 | Part 5.6 (Wave T.5) | 2114 | ✓ | ✓ (Codex high edge-case auditor prompt) |
| 400 | Part 5.1 (Wave A mcp_doc_context) | 1716 | ✓ | ✓ (`<framework_idioms>{mcp_doc_context}</framework_idioms>` block) |
| 404 | Part 5.5 (Wave T mcp_doc_context) | 2025 | ✓ | ✓ (same XML block) |

All 7 Part 5.X references are present, numbered consistently, and address the Wave 1b gap each slice targets.

- **PASS.**

## Check 3 — 8 cross-prompt findings resolution

Wave 1b Part 7 surfaced 8 cross-prompt issues. Each is addressed:

| # | Wave 1b finding | Master report resolution | Impl plan slice |
|---|---|---|---|
| 1 | Wave D Claude-styled body routed to Codex (build-j orphan wedge) | Part 5.4 Wave D merged, pinned to Claude; Part 5.13-5.14 AGENTS.md consolidation | Slice 3 (lines 314-336) |
| 2 | AUD-009..023 block duplicated (~3 KB/wave) | Part 5.14 — dedupe into AGENTS.md `## Canonical Backend Patterns` | Slice 1d (lines 256-265) via `constitution_templates.py` |
| 3 | `[SYSTEM:]` refusal (recovery) | Part 5.10 recovery legacy KILLED per R2 | Slice 1e (lines 266-274) — `cli.py:9526-9531` deleted, `recovery_prompt_isolation` field removed |
| 4 | Scorer `audit_id` omission (build-j:1423) | Part 5.11 SCORER_AGENT_PROMPT — enumerated 17 top-level keys | Deferred to "audit prompt updates" row in Part 7 §7.1 mapping (per master report line 3960). *Not in a Slice-numbered block — see INFO below.* |
| 5 | context7 pre-fetch gap for Wave A / T | Part 5.15 — expand `mcp_doc_context` to A and T | Slice 5a+5b (lines 398-405) |
| 6 | Wave D "client-gap notice" contradiction | Part 5.4 merged prompt resolves both `immutable` block + `blockers[]` structured signal | Slice 3a (lines 318-325) |
| 7 | 30-finding cap vs adversarial directive | Part 5.11 shared changes — two-block emission (primary + `<findings_continuation>`) | Deferred like #4 — see INFO below. |
| 8 | `SHARED_INVARIANTS` does not exist | Part 5.13 — decision R8 ships invariants via AGENTS.md + CLAUDE.md, not as a Python constant | Slice 1d — `constitution_templates.py` carries 3 invariants verbatim |

All 8 addressed in the master report; 6 of 8 are **Slice-numbered** in the impl plan, 2 are bundled into the master report's "audit prompt updates" row (findings #4 and #7 — covered by Part 5.11 but not called out in any impl-plan slice section).

- **PASS.** (Findings #4 and #7 are routed through Part 5.11 which the impl plan references via line 3960 of the master report's §7.1 mapping table. The impl plan's Wave 5 test engineer is not asked to write a dedicated `test_scorer_audit_id.py` or `test_30_finding_cap_continuation.py` — see INFO 1.)

## Check 4 — LOCKED wording citation consistency

Three LOCKED blocks, cited at impl plan lines 79-81, 206-208, 322, and 455.

| LOCKED block | Impl plan cite | Wave 1b cite | Actual current code | Match? |
|---|---|---|---|---|
| IMMUTABLE (`packages/api-client/*`) | line 79, 206, 322 — `agents.py:8803-8808` | Wave 1b `build_wave_d_prompt` prompts at `agents.py:8803` (evidence table row 966) | Verified at `agents.py:8803-8808` — exact match with current file content; verbatim reproduction in master report Part 5.4 `<immutable>` block | **✓** |
| WAVE_T_CORE_PRINCIPLE | line 80, 207 — `agents.py:8374-8388` | Wave 1b `build_wave_t_prompt`:266 cites the constant at `agents.py:8374` | Verified at `agents.py:8374-8388` — 15 lines, matches impl plan range | **✓** |
| `_ANTI_BAND_AID_FIX_RULES` | line 81, 208 — `cli.py:6168-6193` | Wave 1b Part 3 cites `cli.py:6168` | Verified at `cli.py:6168-6193` — exact range, 26 lines, content matches Wave 1b quoted rules verbatim | **✓** |

All LOCKED citations are consistent between impl plan, Wave 1b, master report Part 5.4/5.5/5.8/5.9, and current source. Impl plan line 455 adds `test_locked_wording_verbatim.py` which asserts all three appear verbatim downstream — appropriate guardrail.

- **PASS.**

## Check 5 — Wave D merge addresses build-j wedge

**Impl plan Slice 3 (lines 314-336):**
- 3a: Merged prompt builder via `merged=True` kwarg, prompt text from Part 5.4.
- 3b: WAVE_SEQUENCES update — strip D5 when `wave_d_merged_enabled=True`.
- 3c: **Provider flip D→Claude** — `provider_router.py:27-42` forces D to Claude regardless of `provider_map_d` when merged flag on.
- 3d: Compile-fix-then-rollback.

**Wave 1b diagnosis of build-j wedge** (Part 1 `build_wave_d_prompt` §Known issues + Part 7 §Model mismatches #1):
- Primary root cause: Wave D body is Claude-styled prose (~1,500 tokens of "Do NOT X, MUST Y") but Codex was the **default router** (build-j:837-840 orphan-tool wedge is the direct symptom).
- Codex needs `<tool_persistence_rules>` + short directives to sustain tool calling across long turns.

**Impl plan's approach — provider flip D→Claude via merged prompt — matches Wave 1b's diagnosis:**
- Merged prompt is purpose-built for Claude (long-context ordering, XML blocks, `<visual_polish>` section inline per Part 5.4).
- Codex-persistence class is eliminated for Wave D entirely (no Codex wrapper retained — Part 5.4 routes Codex wrappers to deletion after `wave_d_merged_enabled` flip).
- Slice 3c hard-forces Claude regardless of `provider_map_d`, so even if operator sets Codex, the merge supersedes.

- **PASS.** The fix is structural (remove Codex from a path that was evidence-driven broken), not a containment layer, which matches the user's memory preference (prefer structural fixes over containment).

---

## Comments Index

- **[NIT]** — Impl plan line 274 — "Build-j BUILD_LOG:1502-1529 is the direct evidence: Claude refused the `[SYSTEM:]` pseudo-tag as injection." Wave 1b Part 1 cites the refusal at `BUILD_LOG.txt:1502-1530` (30 lines) whereas the Wave 1b evidence table at row 973 uses `1502-1529` (29 lines). Both are acceptable — the refusal block runs 1502-1530 but the injection-refusal-proper ends at 1529 (line 1530 is a continuation paragraph). Impl plan's `1502-1529` matches the evidence-table form. **No correction required**; flagging for awareness of the 1-line spread between Wave 1b narrative and evidence table.

- **[NIT]** — Impl plan lines 432-453 — The 18-test matrix (Wave 5) does **not** include a dedicated test for Wave 1b cross-prompt findings #4 (`audit_id` omission fix) or #7 (30-finding cap / `<findings_continuation>`). Master report Part 5.11 prescribes the fix (enumerated 17 top-level keys + two-block emission), but the Wave 5 test list covers only the Slice-numbered artifacts. Consider adding `test_scorer_audit_report_schema.py` (asserts all 17 keys present) and `test_audit_finding_cap_continuation.py` (asserts `<findings_continuation>` parse path). **Low priority — both findings are below "build-j wedge" severity and map to "audit prompt updates" in master report §7.1.**

- **[INFO]** — Wave 1b finding #1 (Wave D Codex orphan wedge) is resolved by provider flip, not by adding a Codex `<tool_persistence_rules>` block. This is deliberate per Part 5.4 ("Model: Pin to Claude"). For downstream waves where Codex persistence **is** retained (Wave B, compile-fix, audit-fix, Wave A.5, Wave T.5), Part 5.3/5.6/5.8/5.9 each carry the `<tool_persistence_rules>` block per Wave 1c §2.2. No impl plan action needed.

- **[INFO]** — Impl plan line 264 — "AGENTS.md must stay under 32 KiB (Codex default cap; raised to 64 KiB via `.codex/config.toml` in Slice 5e)." Wave 1b did not surface a 32 KiB cap (that's a Wave 1c / R10 finding). Consistency: the impl plan correctly cross-references Slice 5e, which Wave 1b's consolidation decision (Part 5.13) depends on since moving AUD-009..023 + invariants into AGENTS.md would otherwise exceed the default cap.

- **[INFO]** — Wave 1b Appendix B #10 — "`SHARED_INVARIANTS` doesn't exist as a named constant." Impl plan Slice 1d addresses this by shipping invariants through `constitution_templates.py` (3 canonical invariants verbatim: IMMUTABLE, WAVE_T_CORE_PRINCIPLE, _ANTI_BAND_AID_FIX_RULES + project conventions) rather than introducing a new Python constant. This matches master report Part 5.13 R8 decision. No action needed.

---

## Deliverable summary

- Verdict: **APPROVE WITH 2 NITS.**
- All build evidence cites verified against current BUILD_LOG artifacts.
- All Part 5.X references exist in the master report and contain usable prompt text for their respective Wave 1b gaps.
- All 8 cross-prompt findings from Wave 1b have resolution paths (6 via Slice-numbered blocks, 2 via Part 5.11 "audit prompt updates" row).
- LOCKED-wording line targets verified at current HEAD (`466c3b9`): IMMUTABLE at `agents.py:8803-8808`, WAVE_T_CORE_PRINCIPLE at `agents.py:8374-8388`, `_ANTI_BAND_AID_FIX_RULES` at `cli.py:6168-6193`.
- Wave D merge approach (provider flip D→Claude via merged prompt) matches Wave 1b's diagnosis of the build-j orphan-tool wedge.
