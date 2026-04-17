# Phase G — Wave 7e — Impl Plan Review vs Wave 2b Findings

**Reviewer:** `impl-review-wave2b`
**Target:** `PHASE_G_IMPLEMENTATION.md` (587 lines)
**Ground truth:** `docs/plans/2026-04-17-phase-g-prompt-engineering-design.md` (1873 lines, Wave 2b)
**Master report delegate:** `docs/plans/2026-04-17-phase-g-investigation-report.md` Part 5 (consolidates Wave 2b + R6 + R7)
**Date:** 2026-04-17

---

## Executive Summary

**Overall verdict:** MAJOR GAPS. Impl plan covers Slices 1–5 at the code-wiring level but **omits two whole prompt-engineering deliverables** from Wave 2b: (1) `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` update (Wave 2b Part 12 — XML-structure, GATE 8/9 rules IN PROMPT BODY, injection-re-emit rule, empty-milestone rule, completion-echo collapse, `<conflicts>` block), and (2) `SCORER_AGENT_PROMPT` 17-key schema addition (Wave 2b Part 11.8 — addresses build-j:1423 `audit_id` omission). The impl plan also entirely skips **Wave 2b Part 11.1–11.7** (7 audit-agent content changes). One LOCKED-wording mislabeling: impl plan line 259 claims CLAUDE.md embeds "3 canonical invariants per R8: IMMUTABLE, WAVE_T_CORE_PRINCIPLE, _ANTI_BAND_AID_FIX_RULES" — this conflates Appendix B LOCKED wording with R8 SHARED_INVARIANTS (two different lists).

**Reachability of referenced prompt text:** All 7 Part 5.X sections the impl plan cites (5.1, 5.2, 5.4, 5.5, 5.6, 5.8, 5.9 of the master report) DO contain reachable prompt text — either inline (5.1, 5.4, 5.5, 5.7, 5.8, 5.9, 5.10) or via an in-report pointer to §4.8/§4.9 which carry the complete skeleton + full JSON Schema (5.2, 5.6). The full text also exists in Wave 2b Parts 1, 2, 4, 5, 6, 8, 9 respectively.

**LOCKED wording transfer:** Correct cites. `agents.py:8803-8808` (IMMUTABLE) and `agents.py:8374-8388` (WAVE_T_CORE_PRINCIPLE) match source. `_ANTI_BAND_AID_FIX_RULES` inheritance in Slice 2a (audit-fix) and Slice 2b (compile-fix) is explicit (line 302: "LOCKED `_ANTI_BAND_AID_FIX_RULES`").

**R7 Audit-Fix patch-mode:** PARTIAL. Impl plan line 285 scopes Slice 2a to `_run_audit_fix_unified` (which per Wave 2b Appendix A R7 note IS patch-mode-specific) and line 287 wires to `cli.py:6441` (the ClaudeSDKClient patch-mode call site). However, the impl plan does NOT explicitly state "patch-mode only; full-build mode unchanged" anywhere. R7 qualifier is inferable but not documented. NIT/MEDIUM.

**R2 Recovery kill:** CORRECT. All 3 code sites (`cli.py:9526-9531`, `config.py:863`, `config.py:2566`) match Wave 2b §5.10 + R2.

**R6 "Delete after G-3 flip":** Impl plan implicitly correct — Wave D prompt changes are gated behind `wave_d_merged_enabled=False` default (line 336), and `_wave_sequence` mutator strips D5 only when merged flag is True (line 328). But the impl plan never cites R6 nor explicitly says "D5 prompts are retained while flag is False". Downstream readers of Appendix A must consult the master report to see the "retain while flag off" intent.

**Total comments:** 3 BLOCKING, 4 NIT, 2 INFO.

---

## Check 1 — Part 5.X prompt text reachability

Each Part 5.X section cited by the impl plan was verified in the master investigation report (which consolidates Wave 2b with R6/R7 absorbed). Reachability status:

| Impl plan line | Claim | Master report §5.X | Inline text? | Status |
|---|---|---|---|---|
| 400 | "Emit `<framework_idioms>` … per Part 5.1" (Wave A) | §5.1 | YES (lines 1734-1785 of report) | PASS |
| 349 | "Prompt text from Part 5.2 of investigation report" (Wave A.5) | §5.2 | No inline — points to §4.8 + Wave 2b Part 2; §4.8 has complete skeleton + full JSON Schema (report lines 1463-1489) | PASS (navigable) |
| 321 | "Use EXACT prompt text from Part 5.4 of investigation report" (Wave D merged) | §5.4 | YES (report lines 1928-2019) | PASS |
| 404 | "Emit `<framework_idioms>` block per Part 5.5" (Wave T) | §5.5 | YES (report lines 2043-2106) | PASS |
| 356 | "Prompt text from Part 5.6 of investigation report" (Wave T.5) | §5.6 | No inline — points to §4.9 + Wave 2b Part 6; §4.9 has complete skeleton + full JSON Schema (report lines 1540-1612) | PASS (navigable) |
| 298, 302 | "rewrite for Codex shell per Part 5.8" (Compile-Fix) | §5.8 | YES (report lines 2213-2253) | PASS |
| 293 | "Prompt text for Codex audit-fix from Part 5.9" | §5.9 | YES (report lines 2284-2329) | PASS |

**Verdict:** PASS on reachability. Every impl plan reference to Part 5.X resolves to usable prompt text — 5 sections have inline text, 2 sections (5.2, 5.6) are split between a pointer AND the complete skeleton + full JSON Schema in adjacent §4.8/§4.9 sections. An implementer following the impl plan citation can reach usable text without consulting the 1873-line Wave 2b design doc directly.

**Minor navigation hazard:** The master report's §5.2/§5.6 are one-line pointers. An inattentive reader might miss §4.8/§4.9 because the impl plan does not mention them. Recommend adding a navigation breadcrumb.

---

## Check 2 — LOCKED wording transfer instructions

Wave 2b Appendix B defines three LOCKED wording items (verbatim from current code). Impl plan references:

**Slice 3 — IMMUTABLE block** (impl plan line 322):
> "IMMUTABLE block at `agents.py:8803-8808` transfers VERBATIM"

- **Source cite:** CORRECT. Verified against `src/agent_team_v15/agents.py:8800-8808`. Source lines 8803-8808 contain the IMMUTABLE rule; Wave 2b Appendix B.1 (line 1744) reproduces it verbatim.
- **Transfer instruction:** CORRECT. Slice 3 is the merged Wave D prompt — per Wave 2b §5.4, IMMUTABLE must be wrapped in `<immutable>` XML block. Test file `test_wave_d_merged.py` (line 444) verifies "IMMUTABLE verbatim" — matches Wave 2b Part 6.3 audit expectation.

**Slice 2b — Compile-Fix inherits `_ANTI_BAND_AID_FIX_RULES`** (impl plan line 302):
> "Prompt text from Part 5.8: flat rules + `<missing_context_gating>` + LOCKED `_ANTI_BAND_AID_FIX_RULES` + `output_schema`."

- CORRECT. Matches Wave 2b §5.8 + report §5.8 line 2218: `{_ANTI_BAND_AID_FIX_RULES}   <!-- LOCKED; see Appendix B -->`.
- Source line cite (`cli.py:6168-6193`, impl plan line 208) matches Wave 2b Appendix B.3 (line 1770).

**Slice 2a — Audit-Fix inherits `_ANTI_BAND_AID_FIX_RULES`** (impl plan line 293):
> "Prompt text for Codex audit-fix from Part 5.9 of investigation report."

- PARTIAL. Impl plan cites Part 5.9 (which DOES include `{_ANTI_BAND_AID_FIX_RULES}` at report line 2289), but the impl plan itself does not call out "inherits `_ANTI_BAND_AID_FIX_RULES` verbatim" the way Slice 2b does on line 302. An implementer reading Slice 2a alone might omit the LOCKED block. **NIT:** add the same explicit "LOCKED `_ANTI_BAND_AID_FIX_RULES`" phrasing to Slice 2a summary.

**Slice 5 / Slice 3 — `WAVE_T_CORE_PRINCIPLE` preservation:**
Wave 2b §5.5 (report line 2048) wraps `WAVE_T_CORE_PRINCIPLE` in `<core_principle>` XML but keeps verbatim text. Wave 2b Appendix B.2 locks it.

- Impl plan line 403-404 (Slice 5b): "add `mcp_doc_context` parameter; emit `<framework_idioms>` block per Part 5.5".
- **GAP:** Slice 5b only adds `mcp_doc_context` param. It does NOT instruct the implementer to also rewrite `build_wave_t_prompt` with the full Wave 2b §5.5 structural changes: `<core_principle>` XML wrap, `wave-t-summary` → `<handoff_summary>` conversion, 8-block ordering, "run test suite" MUST, pre-existing test rule, `structural_findings` emission.
- This is ambiguous scope. Wave 2b Part 5 design is a PROMPT REWRITE, not just a context-injection addition. Impl plan Slice 5b reduces it to a parameter addition. See Check 5 below for similar ambiguity on Wave A.

---

## Check 3 — R1 Compile-Fix Codex

**Wave 2b Part 8 design** (report §5.8, lines 2189-2263):
- Pin to Codex `reasoning_effort=high`.
- Inherit `_ANTI_BAND_AID_FIX_RULES` verbatim.
- Add `<missing_context_gating>`.
- Add `output_schema` (JSON with `fixed_errors`, `still_failing`, `assumptions_made`, `residual_error_count`).
- Remove loose "do not delete working code" line (covered by anti-band-aid).
- Add post-fix typecheck + residual failure count.

**Impl plan Slice 2b** (lines 295-302):
> "`wave_executor.py:2391`: rewrite `_build_compile_fix_prompt` for Codex shell per Part 5.8"
> "Prompt text from Part 5.8: flat rules + `<missing_context_gating>` + LOCKED `_ANTI_BAND_AID_FIX_RULES` + `output_schema`."

**Verdict:** PASS on content. All Wave 2b §5.8 design elements are named in Slice 2b.

**Minor:**
- Wave 2b §5.8 adds a `{build_command}` context field so the agent can run typecheck after fixing (report line 2209: "ADD build command reference"). Impl plan Slice 2b does not explicitly mention threading `{build_command}` into the prompt template. NIT — the impl plan's "per Part 5.8" does implicitly cover this, but a hurried implementer could miss it.
- Wiring of `_provider_routing` into `_run_wave_b_dto_contract_guard` (line 299) matches Wave 2b §5.8 "Wiring requirements" + R1 Appendix D line 3831.

---

## Check 4 — R7 Audit-Fix patch-mode

**Wave 2b Part 9 (R7-absorbed)** (report §5.9, lines 2265-2335):
- Applies to `_run_audit_fix_unified` **patch-mode only**.
- Full-build mode continues to use per-wave prompts via subprocess.
- R7 Appendix D line 3882: *"Rewrite for Codex shell; patch-mode only (full-build mode continues to use per-wave prompts via subprocess)."*

**Impl plan Slice 2a** (lines 284-293):
- Line 287: `cli.py:6441`: branch on `classify_fix_provider()` result when `v18.codex_fix_routing_enabled=True`
- Line 288: Wire `provider_router.py:481-504` `classify_fix_provider()`
- Line 291: "Fallback: on Codex failure, fall back to Claude branch"

**Analysis:**
- Line 176-178 of impl plan correctly identifies the two-entry-point context:
  - `cli.py:6271` — `_run_audit_fix_unified` entry (patch-mode router)
  - `cli.py:6441` — ClaudeSDKClient call in patch mode (confirmed patch-mode per impl plan's own line 178)
- Slice 2a scopes to `cli.py:6441` — correctly targets patch mode.
- **BUT:** the impl plan NEVER says "patch-mode only; full-build mode unchanged" in prose. A reader who is not already aware of R7 could interpret "Audit-fix classifier wire-in" as affecting both modes.
- Line 291 ("Fallback: on Codex failure, fall back to Claude branch") matches Wave 2b §5.9 resilience intent but is not the same as R7's "full-build mode uses different code path" scoping.

**Verdict:** PARTIAL. Wiring is scoped correctly (patch-mode only), but the R7 qualifier is not explicitly documented. NIT/MEDIUM — an implementer could inadvertently apply the rewrite to the full-build path (subprocess codex-exec call).

---

## Check 5 — R2 Recovery kill

**Wave 2b Part 10** (report §5.10, lines 2337-2410) + R2 Appendix D line 3835:
- DELETE `cli.py:9526-9531` legacy `[SYSTEM:]` branch.
- REMOVE `recovery_prompt_isolation` field at `config.py:863`.
- REMOVE coerce at `config.py:2566`.
- Unit test: no `[SYSTEM:]` in recovery prompt output.
- Non-flag-gated (behavior-neutral under current default).

**Impl plan Slice 1e** (lines 266-274):
> "DELETE `cli.py:9526-9531` (legacy `[SYSTEM:]` recovery branch)"
> "DELETE `config.py:863` (`recovery_prompt_isolation: bool = True` field)"
> "DELETE `config.py:2566` (corresponding coerce)"
> "Only the isolated shape (system_addendum + user body) remains"

**Verdict:** PASS. All three line cites match Wave 2b R2. Test file `test_recovery_prompt.py` (line 441) covers the unit-test requirement. Non-flag-gated status documented (line 35, line 266, line 527, line 561). Direct evidence cite `build-j BUILD_LOG:1502-1529` (line 274) matches Wave 2b §5.10 + R2.

**Minor:** Impl plan does not mention Wave 2b §5.10's additional content changes to the surviving isolated-shape prompt itself:
- Remove redundant "standard review verification step" line (Wave 1b:652)
- Add "Pipeline log history lives in `.agent-team/STATE.json` and `.agent-team/BUILD_LOG.txt`"
- Add current-run mention (milestone_id, wave_letter, review_cycles)

These are described as "prompt text" changes in Wave 2b §5.10 "Recommended Changes" + "New Prompt Text". The impl plan covers the STRUCTURAL kill but not the CONTENT update of the surviving branch. **NIT:** add "update surviving isolated-shape prompt per Wave 2b §5.10 / Part 10" to Slice 1e.

---

## Check 6 — A.5 / T.5 output_schema references

**Wave 2b Part 2 (A.5)** has the full Codex `output_schema` JSON Schema (Wave 2b lines 268-293 — verdict + findings with 7 category enum values, 4 severities).
**Wave 2b Part 6 (T.5)** has the full Codex `output_schema` JSON Schema (Wave 2b lines 994-1022 — gaps array + files_read top-level).

**Master report cross-reference:**
- §4.8 embeds the full A.5 JSON Schema verbatim (report lines 1463-1489) — "verbatim from Wave 2b prompt-engineering-design.md lines 268-293".
- §4.9 embeds the full T.5 JSON Schema verbatim (report lines 1584-1612) — "verbatim from Wave 2b prompt-engineering-design.md lines 994-1022".

**Impl plan Slice 4a (A.5)** (line 349): "Prompt text from Part 5.2 of investigation report"
**Impl plan Slice 4b (T.5)** (line 356): "Prompt text from Part 5.6 of investigation report"

**Verdict:** PASS. Both impl plan references are navigable. Part 5.2/5.6 in master report are one-line pointers that delegate to §4.8/§4.9 (which have the full JSON Schemas). A diligent implementer can find the schemas. However:

**INFO:** The impl plan does not explicitly instruct "wire `output_schema` into Codex SDK call via `output_schema=` parameter" (Wave 1c §2.4). An experienced Codex implementer would know this, but less experienced implementers might wire the prompt text without configuring the Codex SDK's structured output feature. Recommend an explicit line in Slice 4a/4b pointing to "wire `output_schema=` per Wave 1c §2.4 + report §4.8/§4.9".

---

## Check 7 — Orchestrator prompt update

**Wave 2b Part 12** (Wave 2b lines 1568-1693) is a complete orchestrator prompt REWRITE:
- XML-section the body (`<role>`, `<wave_sequence>`, `<delegation_workflow>`, `<gates>`, `<escalation>`, `<completion>`, `<enterprise_mode>`)
- Collapse 4× completion-criteria echoes to single `<completion>` block
- Update wave sequence: A → A.5 → Scaffold → B → C → D (merged) → T → T.5 → E → Audit → Audit-Fix
- **NEW GATE 8 and GATE 9 IN THE PROMPT BODY** (distinct from orchestrator code-level enforcement):
  - GATE 8: A.5 verdict FAIL blocks Wave B
  - GATE 9: T.5 CRITICAL gaps block Wave E
- NEW escalation rule: "Phase-lead rejection with injection-like reason → re-emit via system-addendum shape"
- NEW escalation rule: "Empty milestone → emit to .agent-team/PLANNER_ERRORS.md; skip"
- NEW `<conflicts>` block: "gate in this prompt WINS" over `$orchestrator_st_instructions`
- Wrap `_DEPARTMENT_MODEL_ENTERPRISE_SECTION` in `<enterprise_mode>` tags
- Source: `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` at `agents.py:1668`, `_DEPARTMENT_MODEL_ENTERPRISE_SECTION` at `agents.py:1864`

Wave 2b Appendix A (line 1730-1731) also lists:
- `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` | agents.py:1668 | "XML-structure + GATE 8/9 + injection-re-emit rule"
- `_DEPARTMENT_MODEL_ENTERPRISE_SECTION` | agents.py:1864 | "Wrap in `<enterprise_mode>` only"

**Impl plan search results** (grep `TEAM_ORCHESTRATOR|orchestrator.*prompt|agents.py:1668|agents.py:1864`):
- **Zero matches for `TEAM_ORCHESTRATOR_SYSTEM_PROMPT`.**
- **Zero matches for `agents.py:1668`.**
- All "orchestrator" mentions in the impl plan refer to ORCHESTRATOR-LEVEL CODE enforcement (Slice 4e GATE 8/9 runtime gates in `cli.py`), NOT to the prompt constant update.

**Verdict: BLOCKING GAP.** Wave 2b Part 12 designs a full orchestrator prompt rewrite; the impl plan implements the CODE-LEVEL enforcement (Slice 4e) but completely skips the PROMPT-LEVEL redesign. An implementation following the impl plan will ship:
- Code-level GATE 8/9 runtime gates (Slice 4e) — OK
- A 10-wave pipeline — OK
- BUT: the orchestrator system prompt will still describe the OLD wave sequence (no A.5/T.5 references), will still have 4× completion echoes, will still lack the injection-re-emit rule, will still lack the empty-milestone rule, will still lack the conflicts-with-st-instructions rule.
- Wave A.5/T.5 gates exist in code but are not documented in the orchestrator's own system prompt — the orchestrator will be coordinating waves it has no prompt-level knowledge of.

Missing impl plan content should be a new sub-slice (e.g., Slice 4f or Slice 6) covering:
1. `agents.py:1668` `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` rewrite per Wave 2b §12 / report §5.12 (if mirrored there).
2. `agents.py:1864` `_DEPARTMENT_MODEL_ENTERPRISE_SECTION` XML wrapping.
3. Test: `test_orchestrator_prompt_gate8_gate9.py` — assert wave sequence lists A.5/T.5; assert GATE 8/9 appear in prompt body; assert completion block is singular.

---

## Check 8 — Scorer 17-key schema

**Wave 2b Part 11.8** (Wave 2b lines 1513-1546) — Critical fix for build-j:1423:
- `SCORER_AGENT_PROMPT` at `audit_prompts.py:1292`
- PROBLEM: build-j:1423 `"Failed to parse AUDIT_REPORT.json: 'audit_id'"` — parser fails if any of 17 top-level keys is missing.
- SOLUTION: Enumerate all 17 required top-level keys verbatim in the prompt (schema_version, generated, milestone, audit_cycle, overall_score, max_score, verdict, threshold_pass, auditors_run, raw_finding_count, deduplicated_finding_count, findings, fix_candidates, by_severity, by_file, by_requirement, audit_id).
- Rationale: *"If ANY of the 17 keys is missing, the downstream parser fails and the audit cycle is lost."*

Wave 2b Appendix A (line 1727): `SCORER_AGENT_PROMPT` | audit_prompts.py:1292 | **"Enumerate 17-key AUDIT_REPORT.json schema"**

**Impl plan search results** (grep `SCORER_AGENT|audit_prompts.py:1292|17.key|audit_id`):
- **Zero matches for `SCORER_AGENT_PROMPT`.**
- **Zero matches for `audit_prompts.py:1292`.**
- **Zero matches for `17-key` / `17 keys` / `audit_id`.**

**Verdict: BLOCKING GAP.** Wave 2b Part 11.8 is the HIGHEST-PRIORITY, LOWEST-COST fix in the entire investigation report (Wave 2b line 1515: *"Critical fix (Wave 1b finding 4): Enumerate the required top-level AUDIT_REPORT.json keys verbatim"*). It directly addresses a documented parser failure (build-j:1423) that causes audit cycles to be silently lost. Cost: +~200 tokens per scorer invocation. Benefit: prevents repeated build-j parser failures.

The impl plan covers `audit_prompts.py:651` (TEST_AUDITOR_PROMPT for T.5 injection, Slice 5d) but skips `audit_prompts.py:1292` (SCORER_AGENT_PROMPT 17-key enumeration) entirely. This is a glaring omission for a plan styled as "the final code push."

Missing impl plan content should be a new sub-slice (e.g., Slice 5f or bolt onto Slice 5d) covering:
1. `audit_prompts.py:1292` `SCORER_AGENT_PROMPT` — add `<output_schema>` block with 17 enumerated keys per Wave 2b §11.8.
2. Test: `test_scorer_audit_id_enumeration.py` — assert all 17 keys appear in rendered prompt.
3. Non-flag-gated (same rationale as Slice 1e: bug fix, not a feature).

**Additional audit-prompt gap (INFO):** Wave 2b Parts 11.1–11.7 define content changes for SIX OTHER auditor prompts (REQUIREMENTS_AUDITOR, TECHNICAL_AUDITOR, INTERFACE_AUDITOR, TEST_AUDITOR structural changes beyond T.5 injection, MCP_LIBRARY_AUDITOR, PRD_FIDELITY_AUDITOR, COMPREHENSIVE_AUDITOR). The impl plan does not cover any of these. Partial scope is acceptable for Phase G's "5 slices" framing, but the impl plan should explicitly defer Parts 11.1–11.7 rather than silently skip.

---

## Comments Index

| Severity | Line(s) | Comment |
|---|---|---|
| **BLOCKING** | whole-plan (missing slice) | **Wave 2b Part 12 orchestrator prompt rewrite is entirely omitted.** Impl plan Slice 4e covers code-level GATE 8/9 enforcement in `cli.py`, but the `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` at `agents.py:1668` is never updated. Missing: XML-structure, new wave sequence (A.5/T.5 in `<wave_sequence>`), GATE 8/9 in `<gates>` block, injection-re-emit rule, empty-milestone rule, 4× completion-echo collapse, `<conflicts>` block, `_DEPARTMENT_MODEL_ENTERPRISE_SECTION` wrap. Also missing: the 1-line reference at `agents.py:1668` and `agents.py:1864` in Wave 1 line-map verification targets. Add a new sub-slice (e.g., Slice 4f) or extend Slice 4e. |
| **BLOCKING** | whole-plan (missing slice) | **Wave 2b Part 11.8 SCORER_AGENT_PROMPT 17-key schema is entirely omitted.** This is the single highest-priority, lowest-cost fix in the investigation report — directly addresses build-j:1423 audit parser failure. `audit_prompts.py:1292` must be updated to enumerate all 17 required AUDIT_REPORT.json top-level keys. Add as a non-flag-gated sub-slice alongside Slice 1e (both are bug fixes with direct build-log evidence). Also add test `test_scorer_audit_id_enumeration.py`. |
| **BLOCKING** | 259 | **LOCKED-wording mislabel.** Impl plan Slice 1d says CLAUDE.md template carries "3 canonical invariants per R8: IMMUTABLE, WAVE_T_CORE_PRINCIPLE, _ANTI_BAND_AID_FIX_RULES verbatim". This is wrong: per Wave 2b Appendix C.1 + R8 (investigation report Appendix D line 3885), the 3 canonical invariants are: (1) no parallel main.ts/bootstrap()/AppModule, (2) no editing packages/api-client/*, (3) no git commit or new branches. IMMUTABLE/WAVE_T_CORE_PRINCIPLE/_ANTI_BAND_AID_FIX_RULES are the 3 Appendix B LOCKED wording items — a separate list. Conflating these will cause `constitution_templates.py` to embed the wrong invariants in CLAUDE.md. Fix: update impl plan line 259 to the correct R8 invariant list; verify `test_constitution_templates.py` asserts R8 strings, not Appendix B strings. |
| **NIT** | 293 | Slice 2a (Audit-Fix Codex rewrite) does not explicitly state "inherits `_ANTI_BAND_AID_FIX_RULES` verbatim" the way Slice 2b does on line 302. An implementer reading only Slice 2a could omit the LOCKED block. Add: "Part 5.9 text: flat rules + scope guards + LOCKED `_ANTI_BAND_AID_FIX_RULES` + `output_schema` + one-finding-per-invocation." |
| **NIT** | 284-293 | R7 patch-mode qualifier is not explicitly documented. Slice 2a correctly scopes code to `cli.py:6441` (patch-mode call site), but the prose never says "patch-mode only; full-build mode unchanged". Add a one-line scope comment: "Per R7, this slice applies to patch mode only; full-build subprocess path (`_run_audit_fix` at `cli.py:6196`) is unchanged." This matches Wave 2b Appendix A R7 note (investigation report Appendix D line 3880). |
| **NIT** | 266-274 | Slice 1e (Recovery kill) covers the STRUCTURAL delete but not the CONTENT update to the surviving isolated-shape prompt. Wave 2b §5.10 + Part 10 specify: remove redundant "standard review verification step" line, add "Pipeline log history lives in `.agent-team/STATE.json` / `.agent-team/BUILD_LOG.txt`", add current-run mention. Add: "Update surviving `_build_recovery_prompt_parts` body per Wave 2b §5.10 / Part 10." |
| **NIT** | 399-404 | Slice 5a/5b reduces Wave 2b §5.1 / §5.5 prompt REWRITES to mere parameter additions. Wave 2b §5.1 (Wave A) specifies full rewrite: XML sections (`<context>`, `<rules>`, `<precognition>`, `<output>`), over-engineering block, explicit migration MUST, `<output_contract>` block. Wave 2b §5.5 (Wave T) specifies full rewrite: `<core_principle>` XML wrap, 8-block ordering, "run test suite" MUST, `structural_findings` emission, pre-existing test rule. Impl plan Slice 5a/5b appears to ONLY add `mcp_doc_context` — missing the structural rewrites. Clarify whether Slice 5 scope includes the full §5.1/§5.5 rewrite or only the framework_idioms injection. |
| **INFO** | 342, 349, 356 | Impl plan cites Part 5.2/5.6 for Wave A.5 and T.5 prompt text. Master report §5.2/§5.6 are one-line pointers delegating to §4.8/§4.9 (which have the complete skeletons + full JSON Schemas, verbatim from Wave 2b Parts 2/6). Recommend adding breadcrumb: "See also report §4.8/§4.9 for the complete `output_schema` JSON Schemas wired into Codex SDK `output_schema=` per Wave 1c §2.4." |
| **INFO** | whole-plan | Wave 2b Parts 11.1–11.7 (six other audit-agent prompt content changes — REQUIREMENTS_AUDITOR evidence-ledger, TECHNICAL_AUDITOR architecture violations, INTERFACE_AUDITOR GraphQL/WebSocket, TEST_AUDITOR structural changes beyond T.5, PRD_FIDELITY_AUDITOR shared, COMPREHENSIVE_AUDITOR template-aware weights + nested category_scores) are not in the impl plan. Acceptable if explicitly deferred; not acceptable if silently skipped. Recommend adding a "Parts 11.1–11.7 DEFERRED" note in the Inviolable Rules section with rationale. |

---

## Summary of required impl plan additions

1. **New sub-slice (Slice 4f or Slice 6):** `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` rewrite per Wave 2b Part 12 — XML-structure, GATE 8/9 in prompt body, injection-re-emit + empty-milestone + conflicts rules, `_DEPARTMENT_MODEL_ENTERPRISE_SECTION` wrapping. Add line-map target `agents.py:1668` and `agents.py:1864` to Wave 1. Add test `test_orchestrator_prompt_gate8_gate9.py`.

2. **New non-flag-gated sub-slice (alongside Slice 1e):** `SCORER_AGENT_PROMPT` at `audit_prompts.py:1292` — enumerate 17 AUDIT_REPORT.json keys per Wave 2b Part 11.8. Add line-map target. Add test `test_scorer_audit_id_enumeration.py`.

3. **Fix line 259 LOCKED-wording conflation:** CLAUDE.md canonical invariants per R8 are 3 project-convention strings, not the 3 Appendix B LOCKED wording items. Update `constitution_templates.py` description accordingly.

4. **Clarify Slice 5 scope** (lines 399-411): is this ONLY adding `mcp_doc_context` parameter, or does it include the full Wave 2b §5.1 / §5.5 prompt rewrites? If only injection: state so explicitly and defer §5.1 / §5.5 structural rewrites to a future slice. If full rewrite: expand Slice 5a/5b to enumerate all §5.1 / §5.5 structural changes.

5. **Add 3 scope clarifications** (NITs): R7 patch-mode qualifier in Slice 2a; LOCKED `_ANTI_BAND_AID_FIX_RULES` explicit mention in Slice 2a; surviving-prompt content update in Slice 1e.

6. **Add defer-list note** for Wave 2b Parts 11.1–11.7 (six audit-agent content changes not currently in impl plan).
