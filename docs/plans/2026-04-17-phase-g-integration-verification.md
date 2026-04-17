# Phase G — Wave 3 — Integration Verification

**Date:** 2026-04-17
**Author:** `integration-verifier` (Phase G Wave 3)
**Repository:** `C:\Projects\agent-team-v18-codex`
**Branch:** `integration-2026-04-15-closeout` HEAD `466c3b9`
**Mode:** PLAN ONLY — no source modified.
**Inputs verified:**
- `docs/plans/2026-04-17-phase-g-pipeline-design.md` (Wave 2a, 1376 lines)
- `docs/plans/2026-04-17-phase-g-prompt-engineering-design.md` (Wave 2b, 1873 lines)
- Wave 1a/1b/1c findings consulted for ambiguity resolution
- `PHASE_G_INVESTIGATION.md` Exit Criteria

---

## Executive Summary

Wave 2a (pipeline) and Wave 2b (prompts) are **~85% internally consistent**; the remaining 15% requires explicit reconciliation before Wave 4 synthesis.

### Conflict verdicts (5 pre-flagged)

| # | Topic | Verdict |
|---|---|---|
| 1 | Merged Wave D flag-gating vs. complete prompt collapse | **PASS (nit)** — timeline aligns if 2b's "Delete" is labeled G-3-scheduled |
| 2 | Legacy recovery `[SYSTEM:]` path | **GAP** — Wave 2b proposes kill; Wave 2a silent. Needs Wave 2a acceptance or rejection |
| 3 | Compile-Fix routing | **CONFLICT** — Wave 2b pins to Codex `high`; Wave 2a has no flag/code path for compile-fix routing |
| 4 | Audit-Fix routing (patch vs. full) | **PASS (nit)** — Wave 2b's single-finding prompt is correctly patch-scoped; Appendix A should say so explicitly |
| 5 | SHARED_INVARIANTS consolidation | **PASS (nit)** — Wave 2a's CLAUDE.md and AGENTS.md templates are missing 1–2 of Wave 2b's 3 canonical invariants |

### Verification check verdicts (10 required)

| # | Check | Verdict |
|---|---|---|
| 1 | Every wave has a prompt design | **PASS** |
| 2 | Every prompt targets the right model | **PASS (nit)** — Compile-Fix model mismatch inherits from Conflict 3 |
| 3 | A.5 + T.5 have complete designs | **PASS** |
| 4 | ARCHITECTURE.md flows correctly | **CONFLICT** — path and injection-tag divergence between 2a and 2b |
| 5 | Codex fix routing coherent | **PASS** |
| 6 | No prompt contradictions (IMMUTABLE / CORE_PRINCIPLE / anti-band-aid) | **PASS** — all LOCKED wording verbatim |
| 7 | Feature flag impact complete | **GAP** — Wave 2a missing GATE 8/9, mcp_doc_context wiring, T.5 → Wave E / TEST_AUDITOR fan-out |
| 8 | Backward compat + rollback | **PASS (nit)** — recovery-kill is only non-flag-gated change (links to Conflict 2) |
| 9 | Cost estimate | **PASS (nit)** — Compile-Fix cost not priced (links to Conflict 3) |
| 10 | Implementation order | **GAP** — 5 Wave 2b C.4 action items not in Wave 2a §9 slice plan |

### Critical issues for Wave 4 synthesis

**Blocking (Wave 4 cannot synthesize cleanly until resolved):**

1. **Conflict 3 — Compile-Fix routing.** Wave 2b designs a Codex `high` compile-fix prompt; Wave 2a has no config flag, no transport selector for compile-fix, and no modification to `_build_compile_fix_prompt` at `wave_executor.py:2391`. **Escalate to team-lead.**
2. **Check 4 — ARCHITECTURE.md path + injection-tag contract.** Wave 2a: root-level `<cwd>/ARCHITECTURE.md` written by python helper; injected as `[PROJECT ARCHITECTURE]` block. Wave 2b: per-milestone `.agent-team/milestone-{id}/ARCHITECTURE.md` written by Wave A Claude agent; injected as `<architecture>` XML tag. **Escalate to team-lead.**

**Non-blocking but required fixes:**

3. **Conflict 2 — Recovery path.** Wave 2a should explicitly accept or reject Wave 2b's proposal to kill the `recovery_prompt_isolation` flag + legacy `[SYSTEM: ...]` code path. Current state: Wave 2b assumes kill; Wave 2a doesn't mention it. User memory supports kill ("Prefer structural fixes over containment").
4. **Check 7 GAPs** — Wave 2a must add: (a) GATE 8/9 pipeline enforcement code site, (b) mcp_doc_context wiring for Wave A + Wave T, (c) Wave T.5 gap-list consumption by Wave E + TEST_AUDITOR.
5. **Check 10 GAPs** — Wave 2a §9 slice plan must absorb the 5 Wave 2b C.4 items listed above.

---

## Part 1: Conflict Analysis (5 pre-flagged)

### Conflict 1 — Merged Wave D: flag-gated rollout vs. complete prompt collapse

**Wave 2a position (§1.1, §3, §8.2):** D-merge is flag-gated with `v18.wave_d_merged_enabled` default False. When off, legacy D (Codex) + D.5 (Claude) runs unchanged. When on, merged Claude Wave D replaces D+D5. Wave 2a §8.2 spells out a phased retirement: G-1 keeps legacy; G-2 flips default True; G-3 removes the legacy D/D.5 code entirely.

**Wave 2b position (Part 4, Appendix A):** Designs a single Claude prompt with `<visual_polish>` block (merged functional + polish). Appendix A lists `build_wave_d5_prompt` with action "Delete" and `CODEX_WAVE_D_PREAMBLE`/`SUFFIX` as "Delete". No explicit mention of legacy path preservation.

**Analysis:** Wave 2a's staged rollout and Wave 2b's "Delete" are not contradictory in substance — they are on different timelines. Wave 2b's Appendix A delete instructions are the **eventual** target state that Wave 2a schedules at Phase G-3. When Wave 2a's flag is OFF, the legacy `build_wave_d_prompt` (with `CODEX_WAVE_D_PREAMBLE`) and `build_wave_d5_prompt` run unchanged — Wave 2b's new merged prompt is the `build_wave_d_merged_prompt` alternative entry selected only when the flag is ON.

**Verdict: PASS (nit).** Wave 2b's Appendix A should explicitly label deletions as "G-3 scheduled" or "after merged-D smoke proves stable" to avoid a reader assuming immediate removal. Recommend: update Wave 2b Appendix A entries for `CODEX_WAVE_D_PREAMBLE`, `CODEX_WAVE_D_SUFFIX`, `build_wave_d5_prompt` from "Delete" to "Delete after G-3 flip (retained while `v18.wave_d_merged_enabled=False`)".

---

### Conflict 2 — Legacy recovery `[SYSTEM:]` path

**Wave 2a position:** Silent. Recovery-prompt isolation is not in Wave 2a's brief-mandated "five pipeline changes". Wave 2a §9 implementation order does not list recovery-path modification. Wave 2a §8 feature flag plan does not list `recovery_prompt_isolation` for retirement.

**Wave 2b position (Part 10, Appendix C.4):** Explicit kill decision. Removes the `else` branch at `cli.py:9526-9531` that emits `[SYSTEM: ...]` in the user message; keeps only the isolated shape. Flags to Wave 2a under C.4: *"Delete the legacy `[SYSTEM: ...]` recovery path; remove the `recovery_prompt_isolation` flag entirely."*

**Analysis:** Source verification: `cli.py:9501, 9526, 9531` — `recovery_prompt_isolation` flag and the legacy `[SYSTEM: ...]` pseudo-tag still exist at HEAD. Wave 2b's rationale is build-log evidence (build-j:1502-1529 Claude Sonnet refusal) plus user memory ("Prefer structural fixes over containment"). Wave 2a can accept the kill by adding a Slice 1e item (behavior-neutral removal when flag is already the default on — which it is, per `config.py:863`), OR reject with rationale (e.g., "keep as rollback for isolation-regression").

**Risk of keeping legacy path:** Exact prompt pattern that caused build-j production-critical rejection is still reachable if any deployment accidentally sets `recovery_prompt_isolation=False`.

**Risk of killing:** None observed — the isolated shape has been default since D-05 with no regression.

**Verdict: GAP.** Requires team-lead decision.

**Concrete recommendation:** Team-lead accepts Wave 2b's kill. Add to Wave 2a §9 as **Slice 1e (Foundations) — legacy recovery kill:**
- Delete the `else` branch at `cli.py:9526-9531`.
- Remove `recovery_prompt_isolation` flag from `config.py:863` and its coerce at `config.py:2566`.
- This is behavior-neutral under the existing default (`recovery_prompt_isolation=True`).
- Add a unit test asserting the recovery prompt uses `system_prompt_addendum` only (no `[SYSTEM:]` tag in user body).

---

### Conflict 3 — Compile-Fix routing

**Wave 2a position (§2 routing table, §3.4, §4.1):** Compile-Fix is NOT in the main provider routing table. Wave 2a §3.4 describes a new `_run_wave_d_compile_fix` helper for merged Wave D (modeled on `_run_wave_b_dto_contract_guard`), but does not specify the provider for that helper — it is implicitly Claude (the merged Wave D is Claude). Wave 2a §4 ("Codex Fix Routing Design") is scoped to audit-fix patch mode only.

**Wave 2b position (Part 8):** Pins Compile-Fix to Codex `reasoning_effort=high`. Rewrites `_build_compile_fix_prompt` at `wave_executor.py:2391` to Codex-native shell (flat rules + `<missing_context_gating>` + `output_schema`). Inherits `_ANTI_BAND_AID_FIX_RULES`.

**Analysis:** Wave 2a has no config flag, no code-wiring site, and no transport selection for compile-fix → Codex routing. The Wave 2a flag plan (§8) covers `codex_fix_routing_enabled` for audit-fix patch mode only. If Wave 2b's Codex compile-fix prompt is adopted as designed, it requires:
1. A new config flag (e.g., `v18.compile_fix_codex_enabled: bool = False`).
2. Modification of the compile-fix helper callers (e.g., `_run_wave_b_dto_contract_guard` at `wave_executor.py:2888`; the new `_run_wave_d_compile_fix` Wave 2a is adding).
3. Access to `_provider_routing["codex_transport"]` from the helper — which means the compile-fix invocation must occur in a context where `_provider_routing` is threaded through (currently the helpers are called from `_execute_wave_sdk` which does have `_provider_routing` when routing is enabled).

Wave 2a's compile-fix helper is described in §3.4 as "2 attempts" with rollback on exhaustion — but the execution channel is implicit Claude. Wave 2b's prompt is Codex-shaped and cannot run on a Claude channel without a rewrite.

**Verdict: CONFLICT.** Blocking for Wave 4 synthesis.

**Concrete recommendation:** Either
- **(Option A) Wave 2a extends scope.** Add Compile-Fix to §2 routing table (`Fix-Compile | Codex | high | new flag `v18.compile_fix_codex_enabled``). Add a new slice (or fold into Slice 2) for compile-fix routing wiring. Thread `_provider_routing` through `_run_wave_b_dto_contract_guard` and new `_run_wave_d_compile_fix`.
- **(Option B) Wave 2b narrows scope.** Accept Compile-Fix remains Claude for Phase G; defer Codex routing to Phase H. Rewrite Wave 2b Part 8 as a Claude prompt with XML structure, inheriting `_ANTI_BAND_AID_FIX_RULES`.

Recommend **Option A** because Wave 1c §5 Wave Fix evidence supports Codex for tight-scope compile repair. Option A fits Slice 2 cleanly.

---

### Conflict 4 — Audit-Fix routing (patch-mode restriction)

**Wave 2a position (§4.1):** Codex fix routing is a **patch-mode feature**. Full-build mode is a subprocess escalation that spawns a fresh builder; the spawned child inherits `v18.provider_routing` and runs its own wave dispatch. No changes to full-build fix flow.

**Wave 2b position (Part 9, Appendix A):** Rewrites audit-fix prompt for Codex `high`. The prompt is "Fix exactly the finding below" (one finding per invocation) — inherently a patch-mode shape. Appendix A lists both `_run_audit_fix` (cli.py:6242) and `_run_audit_fix_unified` (cli.py:6271) under the Codex rewrite, without qualifier.

**Analysis:** Wave 2b's prompt is single-finding narrow. That is **only compatible with patch mode** — full-build mode generates a FIX PRD and spawns a subprocess that runs waves against the whole PRD, which has its own per-wave prompts (not "one finding per invocation"). So Wave 2b's audit-fix prompt, as designed, applies only to patch-mode dispatches (`_run_patch_fixes` at `cli.py:6385-6449`).

Wave 2a §4.1 acknowledges this: full-build mode is unchanged. The prompts used inside the subprocess are the wave prompts (A/B/C/D/T/E) which Wave 2b rewrites separately. So there is no actual contradiction — just ambiguity in Wave 2b Appendix A.

**Verdict: PASS (nit).**

**Concrete recommendation:** Update Wave 2b Appendix A entry for `_run_audit_fix_unified` to read: "Rewrite for Codex shell; **patch-mode only** (full-build mode continues to use per-wave prompts via subprocess)."

---

### Conflict 5 — SHARED_INVARIANTS consolidation location

**Wave 2a position (§5b.3 CLAUDE.md template, §5c.2 AGENTS.md template):** Both files ship with stack conventions + forbidden patterns + coding standards.

**Wave 2b position (Appendix C.1):** Do NOT create a Python `SHARED_INVARIANTS` constant. Ship 3 canonical invariants in both AGENTS.md (Codex auto-load) and CLAUDE.md (via `setting_sources=["project"]`). The 3 invariants:
1. "Do NOT create a parallel `main.ts`, `bootstrap()`, or `AppModule`. A second one is a FAIL."
2. "Do NOT modify `packages/api-client/*` except in Wave C. That directory is the frozen Wave C deliverable for all other waves."
3. "Do NOT `git commit` or create new branches. The agent team manages commits."

**Analysis:** Cross-checking Wave 2a's content templates against Wave 2b's 3 canonical invariants:
- Wave 2a CLAUDE.md "Forbidden patterns" (§5b.3):
  - "Never edit `packages/api-client/*`" → **matches invariant 2** ✓
  - Invariant 1 (parallel main.ts) — **MISSING**
  - Invariant 3 (no git commits) — **MISSING**
- Wave 2a AGENTS.md "Do Not" (§5c.2):
  - "Do not edit `packages/api-client/*`" → **matches invariant 2** ✓
  - "Do not `git commit` or create new branches" → **matches invariant 3** ✓
  - Invariant 1 (parallel main.ts) — **MISSING**

**Verdict: PASS (nit).**

**Concrete recommendation:** Update Wave 2a §5b.3 CLAUDE.md "Forbidden patterns" to include all 3 canonical invariants. Update Wave 2a §5c.2 AGENTS.md "Do Not" to include invariant 1 (parallel main.ts). Both templates should cite Wave 2b Appendix C.1 as the canonical source list.

---

## Part 2: Verification Checks (10 required)

### Check 1 — Every wave has a prompt design

Wave 2a waves: A, A.5, Scaffold, B, C, D-merged, T, T.5, E, Audit, Fix.

Wave 2b prompt coverage:
- Part 1: Wave A (Claude)
- Part 2: Wave A.5 (Codex `medium`, NEW)
- Part 3: Wave B (Codex `high`)
- Part 4: Wave D merged (Claude; D + D.5 collapsed)
- Part 5: Wave T (Claude)
- Part 6: Wave T.5 (Codex `high`, NEW)
- Part 7: Wave E (Claude)
- Part 8: Compile-Fix (Codex `high`) — see Conflict 3
- Part 9: Audit-Fix (Codex `high`, patch-mode)
- Part 10: Recovery Agents (Claude)
- Part 11: Audit Agents — 7 prompts (Claude)
- Part 12: Orchestrator (Claude)

Wave C (OpenAPI generator, Python) and Wave Scaffold (scaffold_verifier, Python) correctly omitted.

**Verdict: PASS.**

---

### Check 2 — Every prompt targets the right model

| Wave / Prompt | Wave 2a target | Wave 2b target | Match |
|---|---|---|---|
| A | Claude | Claude | ✓ |
| A.5 | Codex `medium` | Codex `medium` | ✓ |
| B | Codex `high` | Codex `high` | ✓ |
| D (merged) | Claude (under flag) | Claude | ✓ |
| T | Claude (hard-bypass) | Claude | ✓ |
| T.5 | Codex `high` | Codex `high` | ✓ |
| E | Claude | Claude | ✓ |
| Compile-Fix | Unspecified (implicit Claude) | Codex `high` | **✗ (Conflict 3)** |
| Audit-Fix patch | Codex (via classifier) | Codex `high` | ✓ |
| Recovery | Claude | Claude | ✓ |
| Audit agents | Claude | Claude | ✓ |
| Orchestrator | Claude | Claude | ✓ |

**Verdict: PASS (nit).** All align except Compile-Fix (see Conflict 3).

---

### Check 3 — Wave A.5 and T.5 have complete designs

**Wave A.5:**

| Spec element | Wave 2a | Wave 2b |
|---|---|---|
| Prompt text | Skeleton (§6.3) | Full text (Part 2) |
| Input context | §6.2 | Inlined in prompt |
| Output format | JSON schema (§6.4) | JSON + `output_schema` (Part 2) |
| Integration point | §6.5 `wave_executor.py:~3250` | Flagged to Wave 2a |
| Cost estimate | §6.7 ~$0.20/invocation | Matches |
| Skip conditions | §6.6 (5 conditions) | Referenced via Wave 2a |
| Config flags | §6.9 | Uses Wave 2a's |

**Wave T.5:**

| Spec element | Wave 2a | Wave 2b |
|---|---|---|
| Prompt text | Skeleton (§7.3) | Full text (Part 6) |
| Input context | §7.2 | Inlined |
| Output format | JSON (§7.4) | JSON + `output_schema` (Part 6) |
| Integration point | §7.5 `wave_executor.py:~3260` | Flagged to Wave 2a |
| Cost estimate | §7.7 ~$0.80/invocation | Matches |
| Skip conditions | §7.10 (3 conditions) | Wave 2a (T empty → skip) |
| Config flags | §7.9 | Uses Wave 2a's |

**Verdict: PASS.** Both fully specified. Minor divergence: Wave 2b's full prompt text is more detailed than Wave 2a's skeleton — consistent but Wave 2a's skeleton should reference Wave 2b for verbatim body.

---

### Check 4 — ARCHITECTURE.md flows correctly

**Wave 2a design (§5a):**
- **Writer:** Python helper `architecture_writer.init_if_missing(cwd)` + `architecture_writer.append_milestone(milestone_id, wave_artifacts, cwd)` — deterministic, no LLM.
- **Path:** `<generated-project-cwd>/ARCHITECTURE.md` (repo root, project-level).
- **Injection:** Wave prompts for M2+ receive `[PROJECT ARCHITECTURE]` block near top of prompt.
- **Config:** `architecture_md_enabled: bool = False`; `architecture_md_max_lines: int = 500`.

**Wave 2b design (per-wave prompts):**
- Wave A (Part 1 rules line 8): Claude agent writes `.agent-team/milestone-{milestone_id}/ARCHITECTURE.md` describing entities, relations, indexes, migration filenames, service-layer seams. **Per-milestone scratch path.**
- Wave B (Part 3), Wave D (Part 4), Wave T (Part 5), Wave E (Part 7): all consume `{wave_a_artifact_architecture_md}` via `<architecture>` XML tag injection. **Wave A's output is the source.**

**Divergences:**

1. **Path mismatch:**
   - Wave 2a: `<cwd>/ARCHITECTURE.md` (project root, persistent across milestones)
   - Wave 2b: `.agent-team/milestone-{id}/ARCHITECTURE.md` (per-milestone scratch, written by Claude)
2. **Writer mismatch:**
   - Wave 2a: python helper extracts from `wave_artifacts["A"]` structured output
   - Wave 2b: Wave A Claude agent writes the file directly as a MUST
3. **Injection tag mismatch:**
   - Wave 2a: `[PROJECT ARCHITECTURE]` (Claude positions documents FIRST per Wave 1c §1.5)
   - Wave 2b: `<architecture>` XML tag per Wave 1c §1.1

**Analysis:** These are two different design models:
- **Model A (Wave 2a):** Root-level cumulative `ARCHITECTURE.md` persistent across milestones. Python-authored for determinism.
- **Model B (Wave 2b):** Per-milestone `ARCHITECTURE.md` authored by Wave A as a handoff to Wave B/D/T/E within the same milestone.

These can be reconciled cleanly IF **both** artifacts exist:
- Wave A writes `.agent-team/milestone-{id}/ARCHITECTURE.md` (per-milestone scratch, read by Wave B/D/T/E downstream within the same milestone).
- Python helper at milestone-end extracts from `wave_artifacts["A"]` and appends a milestone section to `<cwd>/ARCHITECTURE.md` (cumulative across milestones, read by M2+ waves at prompt start).
- Injection: waves inject EITHER (both?) — decide `[PROJECT ARCHITECTURE]` for the cumulative doc (Wave 2a's design intent) and `<architecture>` XML for the per-milestone doc (Wave 2b's design intent), named differently.

**Verdict: CONFLICT.** Blocking for Wave 4 synthesis. Designs differ on purpose-of-file, writer, path, and injection tag. Without reconciliation, Wave 4 cannot produce consistent wave prompts.

**Concrete recommendations:**
- **(Preferred)** Adopt both models as complementary:
  - Per-milestone scratch: `.agent-team/milestone-{id}/ARCHITECTURE.md` written by Wave A (Wave 2b design). Injected as `<architecture>` into Wave B/D/T/E prompts of the same milestone.
  - Cumulative: `<cwd>/ARCHITECTURE.md` built by python helper from per-milestone artifacts (Wave 2a design). Injected as `[PROJECT ARCHITECTURE]` into wave prompts of M2+.
- **(Alternative)** Collapse to Model B only: kill the python-authored cumulative doc; all consumers read per-milestone files directly (Wave 2a loses cumulative-architecture functionality).
- **(Alternative)** Collapse to Model A only: rewrite Wave 2b prompts to reference root `<cwd>/ARCHITECTURE.md` via `[PROJECT ARCHITECTURE]` tag.

Recommend the **Preferred** path — it satisfies both designs' stated purposes with minimal conflict.

---

### Check 5 — Codex fix routing coherent

**Wave 2a §4 design:** Patch-mode classifier-routed at `cli.py:6441`. Transport via `_provider_routing["codex_transport"]` (so transport selector at Slice 1b is a dependency). Codex timeout 900s (`codex_fix_timeout_seconds: int = 900`). Fallback to Claude on Codex failure (mirrors `provider_router.py:378-393`).

**Wave 2b Part 9:** Audit-fix prompt Codex-shaped, one finding per invocation, inherits `_ANTI_BAND_AID_FIX_RULES`, emits `fixed_finding_ids` + `files_changed` + `structural_note` JSON.

**Integration check:**
- Transport: Wave 2a §4.3 ensures app-server transport reachable (Slice 1b → Surprise A fix). Slice 2a depends on Slice 1b. ✓
- Prompt wrapping: Wave 2a §4.4 specifies `wrap_fix_prompt_for_codex` helper — consistent with Wave 2b's Codex-shaped body. ✓
- Dispatch path: Wave 2a's `_dispatch_codex_fix` helper call site at `cli.py:6441` matches Wave 2b's expectation (one invocation per feature). ✓
- Anti-band-aid: Wave 2a wraps in `<anti_band_aid>` tags (§4.5). Wave 2b Part 9 inherits verbatim. ✓

**Verdict: PASS.**

---

### Check 6 — No prompt contradictions (LOCKED wording verbatim)

See Part 3 for full verbatim audit. Summary:

- **IMMUTABLE rule** (source `agents.py:8803-8808`): verbatim preserved in Wave 2b Appendix B.1 and Wave 2b Part 4 `<immutable>` block. Wave 2a §3.1 references "KEEP verbatim (LOCKED per brief)". No drift.
- **`WAVE_T_CORE_PRINCIPLE`** (source `agents.py:8374-8388`): verbatim preserved in Wave 2b Appendix B.2 and Wave 2b Part 5 `<core_principle>` block. No drift.
- **`_ANTI_BAND_AID_FIX_RULES`** (source `cli.py:6168-6193`): verbatim preserved in Wave 2b Appendix B.3. Embedded in Wave 2b Part 8 (Compile-Fix) and Part 9 (Audit-Fix) as `{_ANTI_BAND_AID_FIX_RULES}` placeholder. Wave 2a §4.4/4.5 wraps in `<anti_band_aid>` tags without modifying wording. No drift.

**Verdict: PASS.**

---

### Check 7 — Feature flag impact

Wave 2a §8.1 flag table verified complete for its own scope. Cross-checking against Wave 2b implicit flag expectations and C.4 action items:

| Wave 2b expectation | In Wave 2a §8 or §9? | Status |
|---|---|---|
| `wave_d_merged_enabled` | §8.1, §3 | ✓ |
| `wave_a5_enabled` | §8.1, §6.9 | ✓ |
| `wave_t5_enabled` | §8.1, §7.9 | ✓ |
| `codex_fix_routing_enabled` (audit-fix) | §8.1, §4.8 | ✓ |
| `codex_transport_mode` (Surprise A fix) | §4.3 (already declared) | ✓ |
| `claude_md_setting_sources_enabled` | §8.1, §5b.2 | ✓ |
| `claude_md_autogenerate` | §8.1, §5b.6 | ✓ |
| `agents_md_autogenerate` | §8.1, §5c.6 | ✓ |
| `architecture_md_enabled` | §8.1, §5a.8 | ✓ |
| **Compile-Fix → Codex flag** | **NOT present** | **GAP (Conflict 3)** |
| **Recovery-path kill / `recovery_prompt_isolation` retirement** | **NOT present** | **GAP (Conflict 2)** |
| **GATE 8 (A.5 verdict) enforcement flag/code** | **Partial — §6.5 describes gating but no orchestrator-level flag** | **GAP** |
| **GATE 9 (T.5 CRITICAL gaps) enforcement flag/code** | **Partial — §7.5 feeds Wave T fix loop but not orchestrator-level gate** | **GAP** |
| **mcp_doc_context wiring for Wave A + Wave T** | **NOT present** | **GAP** |
| **T.5 gap list injected into Wave E prompt** | **Partial — §7.5 feeds T fix loop, not Wave E** | **GAP** |
| **T.5 gap list injected into TEST_AUDITOR_PROMPT** | **NOT present** | **GAP** |
| **Codex `project_doc_max_bytes` config** | **NOT present** | **GAP** |

**Verdict: GAP.** Wave 2a's flag plan covers its own §1–§7 scope but doesn't absorb all of Wave 2b's wiring expectations. At minimum, Wave 2a §8 must add:
- Compile-Fix Codex routing flag (dependent on Conflict 3 resolution).
- Recovery-path kill (dependent on Conflict 2 resolution).
- `wave_a5_gate_enforcement: bool = False` (GATE 8) and `wave_t5_gate_enforcement: bool = False` (GATE 9).
- `mcp_doc_context_waves: list[str] = ["A", "B", "T", "D"]` (add A + T to current B + D scope).
- T.5 gap list propagation to Wave E prompt builder and TEST_AUDITOR.

---

### Check 8 — Backward compatibility + rollback

Wave 2a §8.3: "Every new capability is gated. Rollback = flip flag to `False` and re-run." Slice 1 is behavior-neutral per decision 9.

**Wave 2b exception:** Part 10 recovery-path kill is NOT behind a flag (intentional — user memory supports structural fix over containment).

**Analysis:** Slice 1 behavior-neutrality depends on ALL Phase G flag defaults staying False. Verified:
- `claude_md_setting_sources_enabled: False` ✓
- `claude_md_autogenerate: False` ✓
- `agents_md_autogenerate: False` ✓
- `architecture_md_enabled: False` ✓
- Transport selector: defaults to legacy `exec` ✓

So Slice 1 IS behavior-neutral when all flags are OFF. The recovery-path kill (Conflict 2) is the only exception and must be explicitly called out if adopted.

**Verdict: PASS (nit).** Wave 2a §8.3 should be updated to note: *"One exception: if recovery-path kill is adopted (Wave 3 escalation to team-lead), removing the legacy `[SYSTEM: ...]` code path is behavior-neutral ONLY if `recovery_prompt_isolation=True` (the current default); deployments that explicitly set False will behave differently post-kill."*

---

### Check 9 — Cost estimate

**Wave 2a Appendix B.2 incremental costs:**
- A.5 `medium`: +$0.20/milestone
- T.5 `high`: +$0.80/milestone
- D merge (Codex → Claude): −$0.40/milestone net
- Codex fix routing: −$0.20/milestone net
- Setting_sources + CLAUDE.md load: ~$0.05
- ARCHITECTURE.md inject: ~$0.05
- **Total: +$0.45/milestone**

**Wave 2b reasoning_effort choices:**
- A.5: `medium` (Wave 2a matches) ✓
- T.5: `high` (Wave 2a matches) ✓
- Compile-Fix: `high` (**not priced in Wave 2a** — Conflict 3)
- Audit-Fix: `high` (included in Wave 2a's "Codex fix routing" entry) ✓

**Compile-Fix cost estimate:** Typical ~1.5K prompt + ~600 output tokens. At Codex `high`, that's ~$0.05–$0.20 per invocation. Per-milestone occurrences: 0–3 (Wave B/D/T compile gates). Expected +$0.00–$0.60/milestone if routed to Codex.

**Verdict: PASS (nit).** Wave 2a Appendix B should add a Compile-Fix row with the above band (conditional on Conflict 3 resolution).

---

### Check 10 — Implementation order

Wave 2a §9 slice plan:
- Slice 1 (Foundations): setting_sources + transport selector + ARCHITECTURE.md writer + constitution renderers.
- Slice 2 (Codex fix routing): classifier wire-in + Codex wrapper + timeout config.
- Slice 3 (Wave D merge): merged prompt builder + WAVE_SEQUENCES + provider flip + compile-fix rollback.
- Slice 4 (Wave A.5 + T.5): `_execute_wave_a5` + `_execute_wave_t5` + WAVE_SEQUENCES + integration hooks.

**Wave 2b Appendix C.4 action items (flagged for Wave 2a):**

| C.4 item | Wave 2a slice? | Gap? |
|---|---|---|
| Route A.5/T.5 into pipeline; add GATE 8/9 | Slice 4 (routing); GATE 8/9 **not present** | **GAP** |
| Delete CODEX_WAVE_D_PREAMBLE/SUFFIX/D.5 | Implicit in Slice 3 (merged-D) | ✓ |
| Delete legacy `[SYSTEM:]` recovery path | **NOT in any slice** | **GAP (Conflict 2)** |
| Ship AGENTS.md + CLAUDE.md at repo root | Slice 1d (constitution renderers) | ✓ |
| Enable `setting_sources=["project"]` | Slice 1a | ✓ |
| Configure Codex `project_doc_max_bytes` | **NOT in any slice** | **GAP** |
| Wire mcp_doc_context for Wave A + Wave T | **NOT in any slice** | **GAP** |
| Wire ARCHITECTURE.md consumption across B/D/T/E + audit agents | Partial — Slice 1c covers writer; injection path contract unresolved (Check 4) | **GAP (Check 4 CONFLICT)** |
| Wire Wave T.5 gap-list consumption into TEST_AUDITOR + Wave E | **NOT explicitly in any slice** | **GAP** |
| Wire Wave A.5 verdict consumption into orchestrator | Slice 4 (integration hooks §6.5) | ✓ |

**Verdict: GAP.** Five Wave 2b action items not absorbed by Wave 2a §9:
1. GATE 8/9 orchestrator enforcement code.
2. Recovery path kill (Conflict 2).
3. Codex `project_doc_max_bytes` config (one-line addition).
4. mcp_doc_context wiring for Wave A + Wave T.
5. T.5 gap list propagation to Wave E and TEST_AUDITOR.

**Concrete recommendation:** Wave 2a expand §9 with a **Slice 5 (Prompt integration wiring)** that absorbs items 3, 4, 5. Fold item 1 (GATE 8/9) into Slice 4 orchestrator update. Fold item 2 (recovery kill) into Slice 1 as **Slice 1e**, conditional on team-lead acceptance.

---

## Part 3: LOCKED Wording Verbatim Audit

Three LOCKED items per brief. All verified against source.

### 3.1 IMMUTABLE `packages/api-client/*` rule

**Source (`src/agent_team_v15/agents.py:8803-8808`, Read confirmed at lines 8800-8809):**

Line 8803 (single string, `[RULES]` header preceding):
> *"For every backend interaction in this wave, you MUST import from `packages/api-client/` and call the generated functions. Do NOT re-implement HTTP calls with `fetch`/`axios`. Do NOT edit, refactor, or add files under `packages/api-client/*` - that directory is the frozen Wave C deliverable. If you believe the client is broken (missing export, genuinely unusable type), report the gap in your final summary with the exact symbol and the line that would have called it, then pick the nearest usable endpoint. Do NOT build a UI that only renders an error. Do NOT stub it out with a helper that throws. Do NOT skip the endpoint."*

Lines 8806-8808 (`[INTERPRETATION]` block):
> *"Using the generated client is mandatory, and completing the feature is also mandatory."*
> *"If one export is awkward or partially broken, use the nearest usable generated export and still ship the page."*
> *"Do not replace the feature with a client-gap notice, dead-end error shell, or placeholder route."*

**Wave 2b Appendix B.1:** verbatim match ✓
**Wave 2b Part 4 `<immutable>` block:** verbatim match ✓ (prose rewrap preserves every clause)
**Wave 2a §3.1:** "KEEP verbatim (LOCKED per brief)" — no inline quote, correctly flagged ✓

Also carries into Codex fix prompt short form:
- Wave 2a §4.4: *"IMMUTABLE: zero edits to packages/api-client/*"* (abbreviated)
- Wave 2b Part 2, Part 8, Part 9: short form present ✓

**Verdict: PASS.** No drift.

### 3.2 `WAVE_T_CORE_PRINCIPLE`

**Source (`src/agent_team_v15/agents.py:8374-8388`, Read confirmed):**

```
You are writing tests to prove the code is correct. If a test fails, THE CODE IS WRONG — not the test.

NEVER weaken an assertion to make a test pass.
NEVER mock away real behavior to avoid a failure.
NEVER skip a test because the code doesn't support it yet.
NEVER change an expected value to match buggy output.
NEVER write a test that asserts the current behavior if the current behavior violates the spec.

If the code doesn't do what the PRD says, the test should FAIL and you should FIX THE CODE.
The test is the specification. The code must conform to it.
```

**Wave 2b Appendix B.2:** verbatim match ✓
**Wave 2b Part 5 `<core_principle>` block:** verbatim match ✓

**Verdict: PASS.** No drift.

### 3.3 `_ANTI_BAND_AID_FIX_RULES`

**Source (`src/agent_team_v15/cli.py:6168-6193`, Read confirmed):**

```
[FIX MODE - ROOT CAUSE ONLY]
You are fixing real bugs. Surface patches are FORBIDDEN.

BANNED:
- Wrapping the failing code in try/catch that swallows the error silently.
- Returning a hardcoded value to make the assertion pass.
- Changing the test's expected value to match buggy output (NEVER weaken
  assertions to turn findings green).
- Adding `// @ts-ignore`, `as any`, `// eslint-disable`, or `// TODO`
  to silence the failure.
- Adding a guard that early-returns when the code hits the real code path
  (e.g., `if (!input) return;` when the AC expects a 400 error).
- Creating a stub that just returns `{ success: true }` without doing
  the real work the AC describes.
- Skipping or deleting the test.

REQUIRED approach:
1. Read the finding's expected_behavior and current_behavior fields.
2. Read the actual code at file_path:line_number.
3. Identify WHY the behavior diverges - name the root cause.
4. Change the code so the correct behavior emerges naturally.
5. Verify the fix by re-reading the tests that exercised this path.

If the fix requires more than a bounded change (e.g., it's a missing
service, a wrong architecture, or a schema migration), STOP. Write a
STRUCTURAL note in your summary instead of half-fixing it.
```

**Wave 2b Appendix B.3:** verbatim match ✓
**Wave 2b Part 8 (Compile-Fix):** includes `{_ANTI_BAND_AID_FIX_RULES}` placeholder ✓
**Wave 2b Part 9 (Audit-Fix):** includes `{_ANTI_BAND_AID_FIX_RULES}` placeholder ✓
**Wave 2a §4.4:** wraps in `<anti_band_aid>{_ANTI_BAND_AID_FIX_RULES}</anti_band_aid>` — wrapping only, no mutation ✓
**Wave 2a §4.5:** "no changes — wrapping only" ✓

**Verdict: PASS.** No drift.

---

## Part 4: Phase G Exit Criteria Audit

From `PHASE_G_INVESTIGATION.md` §PHASE G EXIT CRITERIA (lines 769-787):

| Criterion | Status | Evidence |
|---|---|---|
| Pipeline architecture fully documented with file:line evidence | ✓ | Wave 1a findings, 1301 lines |
| Every existing prompt catalogued with model-specific analysis | ✓ | Wave 1b archaeology, 1051 lines |
| Context7-verified prompting best practices for Claude AND Codex | ✓ | Wave 1c research, 764 lines |
| New wave sequences designed (full_stack, backend_only, frontend_only) | ✓ | Wave 2a §1.2 |
| Wave D merge fully specified (combined prompt text) | ✓ | Wave 2a §3 + Wave 2b Part 4 |
| Codex fix routing fully specified | PARTIAL | Wave 2a §4 (audit-fix only); **Compile-Fix gap per Conflict 3** |
| ARCHITECTURE.md fully specified | PARTIAL | Wave 2a §5a — **path/tag contract unresolved per Check 4** |
| CLAUDE.md fully specified | ✓ | Wave 2a §5b |
| AGENTS.md fully specified | ✓ | Wave 2a §5c |
| Wave A.5 fully specified | ✓ | Wave 2a §6 + Wave 2b Part 2 |
| Wave T.5 fully specified | ✓ | Wave 2a §7 + Wave 2b Part 6 |
| EVERY prompt rewritten/designed for its target model | ✓ | Wave 2b Parts 1-12 |
| Integration verification passed (no contradictions) | **THIS WAVE — 1 CONFLICT + multiple GAPs** | See summary above |
| Implementation plan with exact files, LOC, and ordering | PARTIAL | Wave 2a §9 + Appendix A; **missing 5 items per Check 10** |
| All 7 design documents produced | 6 of 7 | This Wave 3 deliverable is the 6th; Wave 4 synthesis remains |
| Master investigation report synthesized | PENDING | Wave 4 |
| ZERO design gaps | **NOT MET** | 1 CONFLICT + 2 GAPs (plus multiple PASS-nits) flagged below |

**Phase G cannot declare "ZERO design gaps" until the Conflict 3 (Compile-Fix routing) and Check 4 (ARCHITECTURE.md contract) resolutions are agreed. Wave 4 must either absorb the fixes or escalate.**

---

## Part 5: File:line Sample Verification

Sampled 3 references each from Wave 2a Appendix A and Wave 2b Appendix A. All verified by direct Read of source at HEAD `466c3b9`.

### Wave 2a samples

1. **`cli.py:339-450` — `_build_options`**
   - Claim: "Constructs `ClaudeAgentOptions` with no `setting_sources` field (`cli.py:427-444`)."
   - Verified: `def _build_options(config, cwd=None, ...)` at line 339. `opts_kwargs` dict constructed at 427-434 with fields `model`, `system_prompt`, `permission_mode`, `max_turns`, `agents`, `allowed_tools`; no `setting_sources` key. ✓

2. **`cli.py:3182` — hard-coded codex transport import**
   - Claim: "Replace hard-coded import with transport selector"
   - Verified: Line 3182 reads `import agent_team_v15.codex_transport as _codex_mod` (hard-coded, no flag check). ✓

3. **`provider_router.py:27-42` — `WaveProviderMap` dataclass**
   - Claim: "Add A5 + T5 fields"
   - Verified: Lines 27-42 define `WaveProviderMap` with fields A/B/C/D/D5/E. Fields A5 and T5 do NOT exist yet. Wave 2a's proposed additions match the gap. ✓

### Wave 2b samples

1. **`agents.py:8803-8808` — IMMUTABLE rule**
   - Claim: "Verbatim from source"
   - Verified: Lines 8803 (primary RULES line) and 8806-8808 (INTERPRETATION block) match Wave 2b Appendix B.1 character-for-character. ✓

2. **`agents.py:8374-8388` — `WAVE_T_CORE_PRINCIPLE`**
   - Claim: "Verbatim from source"
   - Verified: Lines 8374-8388 define the constant; string content matches Wave 2b Appendix B.2 character-for-character. ✓

3. **`cli.py:6168-6193` — `_ANTI_BAND_AID_FIX_RULES`**
   - Claim: "Verbatim from source"
   - Verified: Lines 6168-6193 define the triple-quoted string; content matches Wave 2b Appendix B.3 character-for-character. ✓

**Verdict: All 6 sampled references are accurate.**

---

## Part 6: Recommended Plan Adjustments

### 6.1 Required fixes to Wave 2a design

1. **[Conflict 3 / Check 2 blocker]** Add Compile-Fix to §2 routing table. Add `v18.compile_fix_codex_enabled: bool = False` to §8.1. Add wiring at `_build_compile_fix_prompt` (`wave_executor.py:2391`) and its callers (`_run_wave_b_dto_contract_guard`, new `_run_wave_d_compile_fix`). Fold into Slice 2 or new Slice 2b.
2. **[Conflict 2 GAP]** Accept Wave 2b's recovery-path kill (or reject with rationale). If accepted: add **Slice 1e** to §9. Delete `cli.py:9526-9531` legacy branch + remove `recovery_prompt_isolation` field at `config.py:863`. Add unit test.
3. **[Check 4 CONFLICT]** Adopt the complementary two-doc model (preferred): Wave A writes `.agent-team/milestone-{id}/ARCHITECTURE.md` (Wave 2b design intent preserved); python helper appends to `<cwd>/ARCHITECTURE.md` from `wave_artifacts["A"]` (Wave 2a design intent preserved). Update §5a.5 to specify both injection tags (`<architecture>` for per-milestone, `[PROJECT ARCHITECTURE]` for cumulative).
4. **[Conflict 5 nit]** Add Wave 2b's canonical invariant 1 (no parallel `main.ts`) to §5b.3 CLAUDE.md "Forbidden patterns" and §5c.2 AGENTS.md "Do Not". Add invariant 3 to CLAUDE.md (currently only in AGENTS.md).
5. **[Check 7 GAPs]** Add to §8.1:
   - `wave_a5_gate_enforcement: bool = False` (orchestrator-level GATE 8)
   - `wave_t5_gate_enforcement: bool = False` (orchestrator-level GATE 9)
   - `mcp_doc_context_wave_a_enabled: bool = False`
   - `mcp_doc_context_wave_t_enabled: bool = False`
   - `wave_t5_gap_list_inject_wave_e: bool = False`
   - `wave_t5_gap_list_inject_test_auditor: bool = False`
6. **[Check 10 GAPs]** Expand §9 implementation order with **Slice 5 — Prompt integration wiring**:
   - Wire `mcp_doc_context` into `build_wave_a_prompt` and `build_wave_t_prompt` pathways.
   - Inject Wave T.5 gap list into Wave E prompt and TEST_AUDITOR_PROMPT.
   - Ship `.codex/config.toml` snippet with `project_doc_max_bytes = 65536` if AGENTS.md exceeds 32 KiB.
7. **[Check 8 nit]** Update §8.3 rollback section to note the recovery-path kill exception (conditional on fix 2 above).

### 6.2 Required fixes to Wave 2b design

1. **[Conflict 1 nit]** Update Appendix A entries for `CODEX_WAVE_D_PREAMBLE`, `CODEX_WAVE_D_SUFFIX`, `build_wave_d5_prompt` from "Delete" to "Delete after G-3 flip; retained while `v18.wave_d_merged_enabled=False`".
2. **[Conflict 3]** Either accept Wave 2a extending scope (Option A) or narrow Part 8 to a Claude prompt (Option B). Recommend Option A.
3. **[Conflict 4 nit]** Update Appendix A entry for `_run_audit_fix_unified` to "Rewrite for Codex shell; **patch-mode only** (full-build mode continues to use per-wave prompts via subprocess)."
4. **[Check 4 CONFLICT]** Clarify Wave A's `.agent-team/milestone-{id}/ARCHITECTURE.md` purpose (per-milestone handoff) and confirm consumers inject via `<architecture>` XML tag. Note cumulative doc is Wave 2a's complementary scope.

### 6.3 Open questions requiring team-lead decision

1. **Compile-Fix routing (Conflict 3):** Adopt Wave 2b's Codex pin (Option A — extend Wave 2a) or keep Claude for Phase G (Option B — narrow Wave 2b)?
2. **Recovery-path kill (Conflict 2):** Accept Wave 2b's proposal to remove `recovery_prompt_isolation` flag + legacy `[SYSTEM:]` branch, or keep as rollback?
3. **ARCHITECTURE.md two-doc model (Check 4):** Adopt preferred complementary model (per-milestone + cumulative), or collapse to single model?
4. **GATE 8/9 enforcement severity:** Should GATE 8 FAIL of Wave A.5 block Wave B unconditionally, or allow override via Wave 2a skip-conditions (simple milestones)? Wave 2b Part 12 specifies CRITICAL findings block Wave B; Wave 2a §6.5 mirrors. Low-risk alignment but confirm.
5. **T.5 gap list propagation scope:** Wave 2a §7.5 feeds Wave T fix loop only. Wave 2b Part 7 + Part 11.4 also expect Wave E and TEST_AUDITOR consumption. Is the fan-out the intended scope?

---

## Appendix A: Verification Method

### A.1 Inputs read completely

- `docs/plans/2026-04-17-phase-g-pipeline-design.md` — 1376 lines, end-to-end
- `docs/plans/2026-04-17-phase-g-prompt-engineering-design.md` — 1873 lines, end-to-end
- `PHASE_G_INVESTIGATION.md` — §Report Format + §Phase G Exit Criteria + §Inviolable Rules
- Wave 1a `docs/plans/2026-04-17-phase-g-pipeline-findings.md` — §Executive Summary + §Part 1 + §Part 2 + §Part 3 (for ambiguity resolution)
- Wave 1b `docs/plans/2026-04-17-phase-g-prompt-archaeology.md` — skimmed for cross-references
- Wave 1c `docs/plans/2026-04-17-phase-g-model-prompting-research.md` — skimmed for reasoning_effort defaults

### A.2 Source verification

Direct `Read` of:
- `src/agent_team_v15/agents.py:8370-8398` (WAVE_T_CORE_PRINCIPLE)
- `src/agent_team_v15/agents.py:8800-8824` (IMMUTABLE rule)
- `src/agent_team_v15/cli.py:339-450` (_build_options; setting_sources check)
- `src/agent_team_v15/cli.py:3178-3192` (hard-coded codex import; provider_map)
- `src/agent_team_v15/cli.py:6168-6193` (_ANTI_BAND_AID_FIX_RULES)
- `src/agent_team_v15/cli.py:6438-6449` (Claude dispatch site)
- `src/agent_team_v15/provider_router.py:20-80` (WaveProviderMap + snapshot_for_rollback)
- `src/agent_team_v15/provider_router.py:475-505` (classify_fix_provider)
- `src/agent_team_v15/wave_executor.py:305-315` (WAVE_SEQUENCES)
- `src/agent_team_v15/wave_executor.py:390-410` (_wave_sequence mutator)

### A.3 Tooling used

- `Read` tool for source + design docs (targeted line ranges).
- `Grep` tool for cross-reference scans (`recovery_prompt_isolation`, `classify_fix_provider`, `WAVE_SEQUENCES`, LOCKED quote anchors).
- `Glob` tool for PHASE_G_INVESTIGATION.md location.
- `mcp__sequential-thinking__sequentialthinking` for explicit reasoning on each of 5 Conflicts + 10 Checks (3 thoughts). No context7 queries needed — no SDK behavior claims were load-bearing for any verdict.

### A.4 Verdict framework applied

Per team-lead brief: each verdict is one of PASS / PASS (nit) / CONFLICT / GAP / AMBIGUOUS. Verdict counts:

- PASS: 4 checks (1, 3, 5, 6)
- PASS (nit): 3 conflicts (1, 4, 5) + 3 checks (2, 8, 9)
- CONFLICT: 1 conflict (3) + 1 check (4)
- GAP: 1 conflict (2) + 2 checks (7, 10)
- AMBIGUOUS: 0

**Total blocking verdicts (CONFLICT + GAP requiring team-lead action): 4 items** — all enumerated in Part 6.

---

**Completion:** Wave 3 integration verification complete. Deliverable at `docs/plans/2026-04-17-phase-g-integration-verification.md`. Ready for Wave 4 synthesis after team-lead resolves the 5 open questions in §6.3.
