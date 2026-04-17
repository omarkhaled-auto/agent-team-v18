# PHASE G — Pipeline Restructure + Prompt Engineering (IMPLEMENTATION)

**Repository:** `C:\Projects\agent-team-v18-codex`
**Branch base:** `integration-2026-04-15-closeout` HEAD `466c3b9` (after Phase F merge). Contains ALL Phases A-F.
**Implementation contract:** `docs/plans/2026-04-17-phase-g-investigation-report.md` Part 7 (THE CONTRACT). Execute it EXACTLY.
**Supporting docs (read as needed, do NOT re-investigate):**
- `docs/plans/2026-04-17-phase-g-pipeline-design.md` (wave sequences + provider routing)
- `docs/plans/2026-04-17-phase-g-prompt-engineering-design.md` (all 12 prompts rewritten)
- `docs/plans/2026-04-17-phase-g-integration-verification.md` (conflict resolutions)
- `docs/plans/2026-04-17-phase-g-wave5a-accuracy-audit.md` (accuracy patches)
- `docs/plans/2026-04-17-phase-g-wave5b-completeness-audit.md` (completeness patches)
**Test baseline:** 10,636 passed / 0 failed after Phase F.

---

## CONTEXT — THE FINAL CODE PUSH

Phase G investigation produced 12,488 lines of design across 9 deliverables. 7 agents across 5 waves investigated the entire pipeline + every prompt + context7-verified prompting best practices for both Claude and Codex. The investigation report Part 7 is the binding implementation contract.

This session EXECUTES that contract. No re-investigation. No re-design. The design is done — now we build it.

**What we're implementing (5 slices + 2 non-flag-gated structural fixes, ~2,025 LOC):**

| Slice | Scope | LOC | Key Change |
|-------|-------|-----|-----------|
| 1 (Foundations) | 1a setting_sources fix, 1b transport selector, 1c ARCHITECTURE.md writer (cumulative), 1d CLAUDE.md + AGENTS.md renderers (R8 invariants, LOCKED wording NOT duplicated), 1e recovery kill (NON-FLAG-GATED), **1f SCORER 17-key schema (NEW, NON-FLAG-GATED — build-j:1423 fix)** | ~545 | Enable CLAUDE.md auto-load, unlock app-server transport, persistent architecture docs (cumulative), kill legacy `[SYSTEM:]`, fix scorer parser failure |
| 2 (Codex fix routing) | 2a Audit-fix classifier wire-in (patch-mode only per R7), 2b compile-fix Codex routing (depends on 2a) | ~260 | Route fixes to Codex for root-cause debugging strength |
| 3 (Wave D merge) | 3a Merged prompt builder (IMMUTABLE verbatim, `[EXPECTED FILE LAYOUT]` rename, `[TEST ANCHOR CONTRACT]` preserved), 3b WAVE_SEQUENCES update (all 3 templates), 3c provider flip D→Claude, 3d compile-gate + D5 rollback (distinct sites), 3e Slice-3/4 collision coordination | ~300 | Single Claude frontend wave (eliminates D.5, fixes build-j orphan-tool wedge) |
| 4 (Wave A.5 + T.5 + GATE 8/9 + Orchestrator) | 4a A.5 dispatch, 4b T.5 dispatch, 4c sequences update, 4d integration hooks, 4e GATE 8/9 + `GateEnforcementError`, **4f Orchestrator prompt rewrite (NEW — Wave 2b Part 12)** | ~700 | Cross-model plan review + edge-case test audit + orchestrator prompt knows about A.5/T.5 |
| 5 (Prompt integration wiring) | 5a Wave A prompt rewrite (mcp_doc_context + **R3 per-milestone ARCHITECTURE.md MUST**), 5b Wave T prompt update, 5c **`<architecture>` XML injection into B/D/T/E (R3)**, 5d T.5→Wave E, 5e T.5→TEST_AUDITOR, 5f .codex/config.toml | ~220 | Framework idioms for Wave A/T, R3 per-milestone doc flow, T.5 gap propagation |

**New routing table (post-implementation):**
A(Claude) → A.5(Codex medium) → Scaffold(Python) → B(Codex high) → C(Python) → D-merged(Claude) → T(Claude) → T.5(Codex high) → E(Claude) → Audit(Claude) → Fix(Codex high) → Compile-Fix(Codex high)

**All new features behind flags defaulting OFF.** Exception: Slice 1e recovery kill is non-flag-gated (structural, behavior-neutral under existing default per R2).

**LOCKED items preserved verbatim:** IMMUTABLE rule, WAVE_T_CORE_PRINCIPLE, _ANTI_BAND_AID_FIX_RULES.

---

## PRE-FLIGHT (MANDATORY)

1. Confirm branch state:
   - `git checkout integration-2026-04-15-closeout && git pull`
   - `git log -1` — confirm HEAD is `466c3b9` (Phase F merge)
   - `git log --oneline | head -10` — verify 9-commit chain
   - `pip show agent-team-v15` — editable path is current worktree
2. Create fresh branch: `git checkout -b phase-g-pipeline-restructure`
3. Run `pytest tests/ -v --tb=short` — **confirm baseline: 10,636 passing + 0 failed.**
4. Capture baseline into `session-G-validation/preexisting-baseline.txt`.

**HALT if baseline diverges from 10,636 / 0.**

---

## AGENT TEAM STRUCTURE — EXHAUSTIVE PATTERN

### Team Composition (8 agents)

| Agent Name | Type | MCPs | Role |
|------------|------|------|------|
| `phase-g-architecture-discoverer` | `superpowers:code-reviewer` | context7, sequential-thinking | Wave 1 (solo) — reads current code at file:line targets from Part 7; confirms nothing shifted since investigation |
| `slice1-foundations-impl` | `general-purpose` | context7, sequential-thinking | Wave 2 — Slice 1 (**1a + 1b + 1c + 1d + 1e + 1f**). 1f is the SCORER_AGENT_PROMPT 17-key schema fix (non-flag-gated; audit_prompts.py:1292). |
| `slice2-codex-fix-impl` | `general-purpose` | context7, sequential-thinking | Wave 2 — Slice 2 (2a + 2b), depends on Slice 1b |
| `slice3-wave-d-merge-impl` | `general-purpose` | context7, sequential-thinking | Wave 3 (after Slice 2) — Slice 3 (merged D prompt + sequences + provider flip) |
| `slice4-new-waves-impl` | `general-purpose` | context7, sequential-thinking | Wave 3 (parallel with Slice 3) — Slice 4 (**A.5 + T.5 + GATE 8/9 + 4f orchestrator prompt rewrite**). 4f is the TEAM_ORCHESTRATOR_SYSTEM_PROMPT rewrite at agents.py:1668 + _DEPARTMENT_MODEL_ENTERPRISE_SECTION at agents.py:1864 (non-flag-gated). |
| `slice5-prompt-wiring-impl` | `general-purpose` | context7, sequential-thinking | Wave 4 (after Slices 3+4) — Slice 5 (**5a Wave A rewrite + R3 per-milestone MUST, 5b Wave T update, 5c `<architecture>` XML injection into Wave B/D/T/E, 5d T.5→Wave E, 5e T.5→TEST_AUDITOR, 5f .codex/config.toml**) |
| `phase-g-test-engineer` | `general-purpose` | sequential-thinking | Wave 5 — writes all 24 test files (18 original + 5 review-driven + 1 locked-wording), runs pytest, iterates |
| `phase-g-wiring-verifier` | `general-purpose` | context7, sequential-thinking | Wave 5 (parallel) — verifies every slice triggers correctly |

### Coordination Flow

```
Wave 1 (solo): phase-g-architecture-discoverer
    │
    Reads current code at EVERY file:line from Part 7 §7.1.
    Confirms: line numbers haven't shifted since investigation.
    Confirms: all 9 "Surprises" from Wave 1a still present.
    Confirms: LOCKED wording at agents.py:8803-8808 (IMMUTABLE),
              agents.py:8374-8388 (WAVE_T_CORE_PRINCIPLE),
              cli.py:6168-6193 (_ANTI_BAND_AID_FIX_RULES).
    If ANY line target has shifted → update the map for impl agents.
    │
    Produces: docs/plans/2026-04-17-phase-g-impl-line-map.md
    │
    HALT POINT: team lead reviews line map.
    If all targets match → proceed. If shifted → impl agents use updated map.
    │
Wave 2 (parallel, 2 agents):
    │
    slice1-foundations-impl → Slice 1a, 1b, 1c, 1d, 1e, 1f
      Files: cli.py:~430 (1a setting_sources),
             cli.py:3182 (1b transport selector),
             NEW architecture_writer.py (1c cumulative doc),
             NEW constitution_templates.py + constitution_writer.py (1d),
             cli.py:9526-9531 + config.py:863 + config.py:2566 (1e recovery kill),
             audit_prompts.py:1292 (1f SCORER_AGENT_PROMPT 17-key schema — NEW),
             config.py (flags + removals)

    slice2-codex-fix-impl → Slice 2a, 2b (AFTER 1b completes)
      Files: cli.py:6441 (audit-fix classifier wire-in, patch-mode only per R7),
             wave_executor.py:2391 + wave_executor.py:2888 (compile-fix Codex routing),
             NEW codex_fix_prompts.py (wrap_fix_prompt_for_codex),
             config.py (fix routing flags)
    │
    NOTE: Slice 2 depends on Slice 1b (transport selector).
    slice1 agent MUST complete 1b before slice2 starts 2a.
    Slice 2b additionally depends on Slice 2a (reuses _dispatch_codex_fix helper).
    Orchestrator: launch both; slice2 reads 1b output before starting.
    │
Wave 3 (parallel, 2 agents — AFTER Wave 2):
    │
    slice3-wave-d-merge-impl → Slice 3a-3e
      Files: agents.py:8696-8858 (build_wave_d_prompt merged kwarg, 3a),
             agents.py:9018-9131 (dispatcher, 3a),
             wave_executor.py:307-311 (WAVE_SEQUENCES all 3 templates, 3b),
             wave_executor.py:395-403 (_wave_sequence mutator, 3b),
             provider_router.py:27-42 (WaveProviderMap A5/T5/D flip, 3c),
             cli.py:3184-3187 (WaveProviderMap construction, 3c — SHARED with Slice 4),
             wave_executor.py:~3295 (compile-gate, 3d),
             wave_executor.py:~3357-3375 (D5 rollback, 3d — distinct from 3295)

    slice4-new-waves-impl → Slice 4a-4f
      Files: wave_executor.py:~3250 (A.5 dispatch hook, 4a),
             wave_executor.py:~3260 (T.5 dispatch hook, 4b),
             NEW _execute_wave_a5 + _execute_wave_t5 in wave_executor.py or cli.py,
             agents.py:NEW A.5 prompt + T.5 prompt (below existing build_wave_* builders),
             cli.py gate logic with GateEnforcementError class (4e),
             agents.py:1668 + agents.py:1864 (4f orchestrator prompt rewrite — NEW; TEAM_ORCHESTRATOR_SYSTEM_PROMPT + _DEPARTMENT_MODEL_ENTERPRISE_SECTION),
             cli.py:3184-3187 (WaveProviderMap A5/T5 construction — SHARED with Slice 3c),
             config.py (A.5/T.5 flags + gate flags)

    These touch DIFFERENT sections of shared files (confirmed by Wave 1a line topology):
    - slice3 touches agents.py prompt builders (8696-8858, 9018-9131) + wave_executor.py sequences (307-403, ~3295-3375)
    - slice4 touches wave_executor.py NEW insertion points (~3250-3260) + cli.py gate logic + agents.py NEW prompts (appended) + agents.py:1668+1864 orchestrator rewrite
    - SHARED collision: cli.py:3184-3187 WaveProviderMap construction touched by both 3c and 4. Team lead verifies per Wave 1a line map; one slice lands first, other rebases.
    │
Wave 4 (solo, AFTER Wave 3): slice5-prompt-wiring-impl → Slice 5a-5f
    │
    Depends on Slice 4b (T.5 dispatch must exist for gap fan-out)
    Depends on Slice 3a (merged Wave D body must exist for <architecture> injection)
    Files: agents.py:7750 (5a Wave A rewrite + mcp_doc_context + R3 per-milestone MUST),
           agents.py:8391 (5b Wave T update + mcp_doc_context),
           build_wave_b_prompt + build_wave_d_prompt (merged) + build_wave_t_prompt + agents.py:8147 build_wave_e_prompt (5c <architecture> XML injection per R3),
           agents.py:8147 (5d T.5→Wave E),
           audit_prompts.py:651 TEST_AUDITOR_PROMPT (5e T.5 gap injection),
           cli.py:3976 _n17_prefetch_cache (5a/5b cache broadening for Wave A + T keyword sets),
           constitution_writer.py (5f .codex/config.toml snippet at project root),
           config.py (wiring flags)
    │
Wave 5 (parallel): test-engineer + wiring-verifier
    │
    test-engineer: writes all 24 test files from §7.8 + review-driven additions
    wiring-verifier: traces every slice end-to-end (including 1f scorer schema, 4f orchestrator prompt, 5c <architecture> injection)
    │
Wave 6: test-engineer runs full pytest; iterates until green
    │
Wave 7: team lead consolidates → PHASE_G_REPORT.md + commit
```

### Critical Rules

- **MCPs mandatory:** context7 + sequential-thinking on every agent EXCEPT test-engineer (sequential-thinking only).
- **The investigation report Part 7 is the CONTRACT.** Implement EXACTLY what it specifies. Don't re-design.
- **The prompt engineering design (Part 5) has the EXACT prompt text.** Use it. Don't invent.
- **LOCKED wording transfers VERBATIM.** IMMUTABLE block, WAVE_T_CORE_PRINCIPLE, _ANTI_BAND_AID_FIX_RULES — copy-paste, don't paraphrase.
- **All new flags default OFF** except Slice 1e recovery kill (non-flag-gated per R2).
- **Mid-flight halt discipline.** If any file:line target has shifted, HALT. Use the updated line map.
- **No regressions.** Baseline 10,636 / 0.
- **Phase consolidation discipline.** Fresh branch from `466c3b9`. Merge to integration at exit.

---

## WAVE 1 — LINE MAP VERIFICATION

**Agent:** `phase-g-architecture-discoverer`
**Type:** `superpowers:code-reviewer`
**MCPs:** `context7`, `sequential-thinking`

### Task

Read the current code at every file:line target listed in Part 7 §7.1. Confirm they haven't shifted since the investigation (HEAD was `466c3b9` — same as our branch base).

### Specific Line Targets to Verify

**Slice 1a:**
- `cli.py:339-450` — `_build_options` function, specifically `opts_kwargs` dict at `:427-444`

**Slice 1b:**
- `cli.py:3182` — hard-coded Codex transport import

**Slice 1c:**
- `wave_executor.py:~3150` — M1 dispatch start point
- `wave_executor.py:~3542-3548` — `persist_wave_findings_for_audit` hook point

**Slice 1d:**
- `config.py:791` — near V18Config flags section (for new flag additions)

**Slice 1e:**
- `cli.py:9526-9531` — legacy `[SYSTEM:]` recovery branch
- `config.py:863` — `recovery_prompt_isolation` field
- `config.py:2566` — corresponding coerce

**Slice 2a:**
- `cli.py:6271` — `_run_audit_fix_unified` entry
- `cli.py:6441` — ClaudeSDKClient call in patch mode
- `provider_router.py:481-504` — `classify_fix_provider` (exported, never called)

**Slice 2b:**
- `wave_executor.py:2391` — `_build_compile_fix_prompt`
- `wave_executor.py:2888` — `_run_wave_b_dto_contract_guard`

**Slice 3:**
- `agents.py:8696-8858` — `build_wave_d_prompt`
- `agents.py:9018-9131` — `build_wave_prompt` dispatcher
- `provider_router.py:27-42` — `WaveProviderMap`
- `wave_executor.py:307-311` — `WAVE_SEQUENCES`
- `wave_executor.py:395-403` — `_wave_sequence` mutator
- `wave_executor.py:~3295-3305` — compile-fix-then-rollback point

**Slice 4:**
- `wave_executor.py:~3250` — pre-Wave-B insertion point for A.5
- `wave_executor.py:~3260` — post-Wave-T insertion point for T.5
- `agents.py` — where new prompts should go (near existing `build_wave_*_prompt` functions)

**Slice 5:**
- `agents.py:7750` — `build_wave_a_prompt`
- `agents.py:8391` — `build_wave_t_prompt`
- `agents.py:8147` — `build_wave_e_prompt`
- `audit_prompts.py:651` — `TEST_AUDITOR_PROMPT`
- `cli.py:3976` — `_n17_prefetch_cache`

**LOCKED wording (verbatim check):**
- `agents.py:8803-8808` — IMMUTABLE packages/api-client/* block
- `agents.py:8374-8388` — WAVE_T_CORE_PRINCIPLE
- `cli.py:6168-6193` — _ANTI_BAND_AID_FIX_RULES

### Deliverable

`docs/plans/2026-04-17-phase-g-impl-line-map.md`:
- For each target: confirmed at exact line OR shifted to new line (with new line number)
- LOCKED wording: confirmed verbatim OR flag discrepancy
- Any post-Phase-F additions that might affect insertion points

### HALT POINT

If all targets match → Wave 2 proceeds using Part 7 line numbers directly.
If any shifted → Wave 2 uses the updated line map.

---

## WAVE 2 — SLICES 1 + 2 (PARALLEL)

### Agent: `slice1-foundations-impl`

**MCPs:** `context7`, `sequential-thinking`

**Reads:** Part 7 §7.1 Slices 1a-1e + line map from Wave 1.

**Implementation order:** 1a → 1b → 1c → 1d (depends on 1a) → 1e (depends on 1a)

#### Slice 1a — setting_sources fix (~10 LOC)

Per Part 7 §7.1 Slice 1a:
- `cli.py:~430`: add `setting_sources=["project"]` when `v18.claude_md_setting_sources_enabled=True`
- `config.py`: add `claude_md_setting_sources_enabled: bool = False`

**Design note on preset flip (per Wave 2a decision 6 + master Part 7 Slice 1a):** Context7 research (Wave 1c §4.1) shows that `setting_sources=["project"]` and `system_prompt={"type":"preset","preset":"claude_code"}` are normally paired. **Phase G deliberately sets ONLY `setting_sources`** and does NOT flip the system_prompt to the `claude_code` preset, because doing so would overwrite the D-05 prompt-injection isolation fix at `cli.py:390-408`. CLAUDE.md is composed with the hand-built system prompt rather than replacing it — Wave 1c §4.1 confirms CLAUDE.md is delivered as a user-turn message AFTER the system prompt, so composition works cleanly without the preset flip. This is a deliberate design compromise, not an oversight. If the compromise fails to load CLAUDE.md at runtime, the follow-up (Phase H) is to find a non-destructive preset composition.

#### Slice 1b — Transport selector (~15 LOC)

Per Part 7 §7.1 Slice 1b:
- `cli.py:3182`: replace hard-coded import with flag-gated branch
- Uses existing `codex_transport_mode` flag at `config.py:811`

#### Slice 1c — ARCHITECTURE.md writer (~200 LOC, R3 TWO-DOC MODEL)

Per Part 7 §7.1 Slice 1c + master §4.5 (R3 two-doc complementary model):

**R3 mandates TWO architecture documents with different lifecycles. Both MUST be implemented:**

**Part 1 — Cumulative `<cwd>/ARCHITECTURE.md` (python-written, this slice):**
- NEW `src/agent_team_v15/architecture_writer.py` with `init_if_missing(cwd)`, `append_milestone(milestone_id, wave_artifacts, cwd)`, `summarize_if_over(max_lines, summarize_floor)`
- `wave_executor.py:~3150`: hook `init_if_missing(cwd)` before M1 dispatch
- `wave_executor.py:~3542-3548`: hook `append_milestone()` alongside `persist_wave_findings_for_audit()`
- `config.py`: add `architecture_md_enabled: bool = False`, `architecture_md_max_lines: int = 500`, `architecture_md_summarize_floor: int = 5`
- Injected into M2+ wave prompts as `[PROJECT ARCHITECTURE]` block at prompt start
- Content template: master §4.5 + pipeline-design.md §5a.2 (8 sections: Summary, Entities, Endpoints, per-milestone, Decisions, etc.)

**Part 2 — Per-milestone `.agent-team/milestone-{id}/ARCHITECTURE.md` (Wave A Claude MUST):**
- This file is NOT python-written. It is authored by Wave A (Claude) as a prompt-level MUST.
- Per master §4.5 + prompt-engineering-design.md Part 1 §5a (Wave 2b Wave A design): Wave A prompt MUST instruct the agent to write `.agent-team/milestone-{id}/ARCHITECTURE.md` describing entities, relations, indexes, migration filenames, service-layer seams.
- Injected as `<architecture>` XML tag into Wave B / D / T / E prompts WITHIN the same milestone.
- **This MUST is added to Wave A prompt in Slice 5a** (see below). Slice 1c python writer does NOT handle the per-milestone doc — only the cumulative doc.

**Two docs, different purposes, no duplication:**
- Per-milestone doc = Wave A's intra-milestone handoff to B/D/T/E (written by Claude, injected as `<architecture>` XML)
- Cumulative doc = cross-milestone knowledge accumulator for M2+ waves (written by python helper at milestone-end, injected as `[PROJECT ARCHITECTURE]` block)

Content templates: master §4.5 of investigation report.

#### Slice 1d — CLAUDE.md + AGENTS.md renderers (~250 LOC)

Per Part 7 §7.1 Slice 1d + master Appendix D R8:
- NEW `src/agent_team_v15/constitution_templates.py` — template constants for CLAUDE.md and AGENTS.md content. **The 3 canonical invariants per R8 (master Appendix D R8 + prompt-engineering-design.md:1816-1820) are project conventions, NOT LOCKED wording:**
  1. "Do NOT create a parallel `main.ts`, `bootstrap()`, or `AppModule`. A second one is a FAIL."
  2. "Do NOT modify `packages/api-client/*` except in Wave C. That directory is the frozen Wave C deliverable for all other waves."
  3. "Do NOT `git commit` or create new branches. The agent team manages commits."
- **DO NOT copy LOCKED wording** (IMMUTABLE packages/api-client rule, WAVE_T_CORE_PRINCIPLE, `_ANTI_BAND_AID_FIX_RULES`) into CLAUDE.md/AGENTS.md. Per Wave 1c §4.4 (docs/plans/2026-04-17-phase-g-model-prompting-research.md), LOCKED wording stays in system prompts only — duplicating into CLAUDE.md/AGENTS.md is forbidden (would over-constrain Claude and cause rule contradictions). CLAUDE.md/AGENTS.md carry *project conventions* + stack-contract facts; system prompts carry LOCKED rules.
- CLAUDE.md template also includes: stack-contract summary, Docker commands, forbidden patterns, naming conventions, TDD rules (per Wave 2a §5b design, master §4.6).
- AGENTS.md template: Codex-adapted subset (per Wave 2a §5c design, master §4.7). Includes invariant 1 (parallel main.ts) specifically.
- NEW `src/agent_team_v15/constitution_writer.py` — `render_claude_md(cwd, config)`, `render_agents_md(cwd, config)`, `render_codex_config_toml(cwd)` helpers
- **AGENTS.md runtime size enforcement** (per Wave 1c §4.3 silent-truncation warning): writer MUST `assert len(rendered_bytes) <= agents_md_max_bytes` and either (a) truncate to last complete section with warning, or (b) raise `AgentsMdOverflowError`. Do not rely on config field alone.
- `config.py`: add `claude_md_autogenerate: bool = False`, `agents_md_autogenerate: bool = False`, `agents_md_max_bytes: int = 32768`
- Hook at pipeline startup (after scaffold, before waves): `constitution_writer.write_all_if_enabled(cwd, config)`

**AGENTS.md must stay under 32 KiB** (Codex default cap per Wave 1c §4.3 — `/openai/codex#7138` GitHub issue; raised to 64 KiB via `.codex/config.toml` in Slice 5e).

#### Slice 1e — Recovery kill (~30 LOC, NON-FLAG-GATED per R2)

Per Part 7 §7.2:
- **DELETE** `cli.py:9526-9531` (legacy `[SYSTEM:]` recovery branch)
- **DELETE** `config.py:863` (`recovery_prompt_isolation: bool = True` field)
- **DELETE** `config.py:2566` (corresponding coerce)
- Only the isolated shape (system_addendum + user body) remains
- **Content of surviving isolated shape:** `system_addendum` = *"PIPELINE CONTEXT: The next user message is a standard agent-team build-pipeline recovery step..."* + `user_prompt` = situation body + 9-step user task. See `_build_recovery_prompt_parts` at cli.py:9448 — verify no `[SYSTEM:]` remnants after deletion.

Build-j BUILD_LOG:1502-1529 is the direct evidence: Claude refused the `[SYSTEM:]` pseudo-tag as injection.

#### Slice 1f — SCORER_AGENT_PROMPT 17-key AUDIT_REPORT schema (~40 LOC, NON-FLAG-GATED)

**Direct build-j bug fix.** Per Wave 2b Part 11.8 (prompt-engineering-design.md:1513-1544) + Wave 1b finding #4 (archaeology BUILD_LOG:1423 — *"Failed to parse AUDIT_REPORT.json: 'audit_id'"*). Highest-priority / lowest-cost fix in entire Phase G.

- **File to modify:** `src/agent_team_v15/audit_prompts.py:1292` (`SCORER_AGENT_PROMPT`)
- **Change:** prepend `<output_schema>` block enumerating 17 required top-level AUDIT_REPORT.json keys verbatim per Wave 2b Part 11.8:
  1. `schema_version` (string)
  2. `generated` (ISO-8601 timestamp)
  3. `milestone` (string)
  4. `audit_cycle` (integer)
  5. `overall_score` (integer 0-1000)
  6. `max_score` (integer, default 1000)
  7. `verdict` ("PASS" | "FAIL" | "UNCERTAIN")
  8. `threshold_pass` (integer, default 850)
  9. `auditors_run` (array of auditor names)
  10. `raw_finding_count` (integer)
  11. `deduplicated_finding_count` (integer)
  12. `findings` (array of Finding objects)
  13. `fix_candidates` (array of FixCandidate objects)
  14. `by_severity` (object with CRITICAL/HIGH/MEDIUM/LOW integer counts)
  15. `by_file` (object mapping relative path → integer count)
  16. `by_requirement` (object mapping requirement_id → integer count)
  17. `audit_id` (UUID v4 string) — **REQUIRED — parser fails without this**
- Rule: *"If ANY of the 17 keys is missing, the downstream parser fails and the audit cycle is lost. Emit ALL 17 keys, even if a value is an empty array or 0."*
- **Non-flag-gated** like Slice 1e — direct bug fix with concrete build evidence; no gradual rollout needed.
- **Estimated LOC:** ~40 (prompt addition + regression test).
- **Dependencies:** None.
- **Tests to add:** `tests/test_scorer_audit_report_schema.py` — assert all 17 keys enumerated in prompt; assert AUDIT_REPORT.json parser accepts output with all 17 keys; regression test against build-j:1423 failure mode.
- **Rollback strategy:** revert prompt addition (NOT flag-gated — structural fix).

### Agent: `slice2-codex-fix-impl`

**MCPs:** `context7`, `sequential-thinking`

**Reads:** Part 7 §7.1 Slices 2a-2b + Part 5.8 (compile-fix Codex prompt) + Part 5.9 (audit-fix Codex prompt) + line map.

**WAIT for Slice 1b** (transport selector) before starting.

#### Slice 2a — Audit-fix classifier wire-in (~120 LOC)

Per Part 7 §7.1 Slice 2a + **R7 patch-mode qualifier**:

**R7 scope (per master Appendix D R7 + Wave 3 Conflict 4 resolution):** This slice is **PATCH-MODE ONLY**. Full-build audit-fix (subprocess escalation spawning a fresh builder) continues to use per-wave prompts — unchanged in Phase G. The Codex audit-fix prompt designed in Wave 2b Part 9 is single-finding narrow ("Fix exactly the finding below"), which is only compatible with patch-mode dispatch (`_run_patch_fixes` at `cli.py:6385-6449`).

- `cli.py:6441`: branch on `classify_fix_provider()` result when `v18.codex_fix_routing_enabled=True` (patch mode only — `_run_audit_fix_unified` patch branch)
- Wire `provider_router.py:481-504` `classify_fix_provider()` — it's exported but never called; now it gets called
- NEW helper `_dispatch_codex_fix()` or reuse transport from Slice 1b
- `config.py`: add `codex_fix_routing_enabled: bool = False`, `codex_fix_timeout_seconds: int = 900`, `codex_fix_reasoning_effort: str = "high"`
- Fallback: on Codex failure, fall back to Claude branch (mirror of `provider_router.py:378-393`)
- **Inherits LOCKED** `_ANTI_BAND_AID_FIX_RULES` from `cli.py:6168-6193` verbatim per Part 6.3.3 + Wave 2b Appendix B.3.

Prompt text for Codex audit-fix from master **§5.9** of investigation report (Wave 2b Part 9). Helper `wrap_fix_prompt_for_codex()` defined in NEW `codex_fix_prompts.py` or extension of `codex_prompts.py`.

#### Slice 2b — Compile-fix Codex routing (~140 LOC)

Per Part 7 §7.3 + R1 (master Appendix D):

**Dependencies:** Slice 1b (transport selector) + **Slice 2a** (audit-fix routing foundation — reuses `_dispatch_codex_fix` helper; if implementation order swaps, Slice 2b may need to define the helper itself).

- `wave_executor.py:2391`: rewrite `_build_compile_fix_prompt` for Codex shell per master **§5.8** (Wave 2b Part 8)
- `wave_executor.py:2888` (`_run_wave_b_dto_contract_guard`): thread `_provider_routing` parameter; branch on `v18.compile_fix_codex_enabled`
- New helper `_run_wave_d_compile_fix` (created in Slice 3): same `_provider_routing` threading
- `config.py`: add `compile_fix_codex_enabled: bool = False`
- **Inherits LOCKED** `_ANTI_BAND_AID_FIX_RULES` from `cli.py:6168-6193` verbatim (no mutation).

Prompt text from master §5.8: flat rules + `<missing_context_gating>` + LOCKED `_ANTI_BAND_AID_FIX_RULES` (verbatim) + `output_schema` JSON Schema (Wave 1c §2.4 pattern).

---

## WAVE 3 — SLICES 3 + 4 (PARALLEL, AFTER WAVE 2)

### Agent: `slice3-wave-d-merge-impl`

**MCPs:** `context7`, `sequential-thinking`

**Reads:** Part 7 §7.1 Slice 3 + Part 5.4 (merged Wave D prompt) + line map.

#### Slice 3 — Wave D merge (~300 LOC)

Per Part 7 §7.1 Slice 3:

**3a. Merged prompt builder:**
- `agents.py:8696-8858`: extend `build_wave_d_prompt` with `merged: bool = False` kwarg
- When `merged=True`: combine Wave D functional wiring + Wave D.5 design tokens + polish rules into single prompt
- Use EXACT prompt text from master **§5.4** of investigation report (Wave 2b Part 4)
- **IMMUTABLE block at `agents.py:8803-8808` transfers VERBATIM** — LOCKED per master Part 6.3.1. Do not fold `CODEX_WAVE_D_SUFFIX` separately; the IMMUTABLE rule appears ONCE in merged prompt (anti-duplication).
- REMOVE Codex autonomy directives (lines from `CODEX_WAVE_D_PREAMBLE`/`CODEX_WAVE_D_SUFFIX` per Wave 2a §3 sections "Dropped")
- REMOVE D.5's "don't change functionality" restriction (merged D does BOTH)
- **RENAME** `[CODEX OUTPUT TOPOGRAPHY]` (from D.5 at `agents.py:8929-8943`) → `[EXPECTED FILE LAYOUT]` per Wave 2a §3 "Kept from D.5" + Wave 2b §5.4
- **KEEP** `[TEST ANCHOR CONTRACT — preserved for Wave T / E]` (renamed from D.5's `[PRESERVE FOR WAVE T AND WAVE E]` at `agents.py:8945-8956`) per Wave 2a §3

**3b. WAVE_SEQUENCES update — all 3 templates:**
- `wave_executor.py:307-311`: update all three template sequences per master §4.1:
  - `full_stack`: `["A", "A5", "Scaffold", "B", "C", "D", "T", "T5", "E"]`
  - `backend_only`: `["A", "A5", "Scaffold", "B", "C", "T", "T5", "E"]`
  - `frontend_only`: `["A", "Scaffold", "D", "T", "T5", "E"]`
- `wave_executor.py:395-403`: extend `_wave_sequence` mutator — strip D5 when `wave_d_merged_enabled=True`; strip A5 when `wave_a5_enabled=False`; strip T5 when `wave_t5_enabled=False`

**3c. Provider flip D→Claude:**
- `provider_router.py:27-42`: update `WaveProviderMap` dataclass — add A5/T5 fields; set D default to `"claude"` when `wave_d_merged_enabled=True` (regardless of `provider_map_d`)
- `cli.py:3184-3187`: construct updated `WaveProviderMap` with A5, T5, conditional D per master §4.2 apply-site example.

**3d. Compile-fix + D5 rollback (distinct sites):**
- **Compile-gate** at `wave_executor.py:~3295`: merged-D compile-fix dispatch. Uses Slice 2b's Codex compile-fix when `compile_fix_codex_enabled=True` AND `wave_d_merged_enabled=True`.
- **D5 rollback** at `wave_executor.py:~3357-3375`: if merged-D compile-fix exhausts `wave_d_compile_fix_max_attempts` (default 2), rollback to legacy D+D5 sequence for that milestone only.
- Note: earlier drafts conflated these into "~3295-3305"; they are two separate code sites — cite both distinctly when implementing.
- `config.py`: add `wave_d_merged_enabled: bool = False`, `wave_d_compile_fix_max_attempts: int = 2`, `provider_map_a5: str = "codex"`, `provider_map_t5: str = "codex"`

**3e. Shared-file coordination with Slice 4 (parallel execution safety):**
- Slice 3 touches `agents.py:8696-8858` (build_wave_d_prompt), `agents.py:9018-9131` (dispatcher), `wave_executor.py:307-403` (sequences), `wave_executor.py:~3295-3375` (compile-fix/rollback).
- Slice 4 touches `agents.py:NEW` (A.5/T.5 prompts, added below existing prompts), `wave_executor.py:~3250-3260` (A.5/T.5 dispatch hooks), `cli.py` (gate enforcement), `cli.py:3184-3187` (WaveProviderMap — shared with 3c).
- **Collision point:** `cli.py:3184-3187` is touched by both slices. Team-lead verifies per Wave 1a Appendix A line index; one slice lands WaveProviderMap construction, other rebases.
- No overlap in `agents.py` or `wave_executor.py` line ranges (verified by Wave 1a line topology review).

### Agent: `slice4-new-waves-impl`

**MCPs:** `context7`, `sequential-thinking`

**Reads:** Part 7 §7.1 Slice 4 + Part 5.2 (Wave A.5 prompt) + Part 5.6 (Wave T.5 prompt) + Part 7 §7.5 (GATE 8/9) + line map.

#### Slice 4 — Wave A.5 + T.5 + GATE 8/9 (~450 LOC)

**4a. _execute_wave_a5 dispatch:**
- NEW function `_execute_wave_a5()` in `wave_executor.py` or `cli.py`
- Dispatches to Codex with `reasoning_effort=medium`
- Prompt text from Part 5.2 of investigation report
- Persists findings to `.agent-team/milestones/{id}/WAVE_A5_REVIEW.json`
- Skip condition: `wave_a5_skip_simple_milestones=True` AND entity_count < 3 AND ac_count < 5

**4b. _execute_wave_t5 dispatch:**
- NEW function `_execute_wave_t5()` in `wave_executor.py` or `cli.py`
- Dispatches to Codex with `reasoning_effort=high`
- Prompt text from Part 5.6 of investigation report
- Persists gaps to `.agent-team/milestones/{id}/WAVE_T5_GAPS.json`
- Skip condition: `wave_t5_skip_if_no_tests=True` AND no test files from Wave T

**4c. WAVE_SEQUENCES update:** coordinated with Slice 3b (same files — team lead verifies edit ranges)

**4d. Integration hooks:** wire A.5 between Wave A and Scaffold; wire T.5 between Wave T and Wave E

**4e. GATE 8/9 orchestrator gating:**
Per Part 7 §7.5:
- GATE 8 after A.5: if `wave_a5_gate_enforcement=True` AND verdict FAIL + CRITICAL → re-run Wave A with feedback → re-run A.5 → block Wave B if persists
- GATE 9 after T.5: if `wave_t5_gate_enforcement=True` AND CRITICAL gaps → loop to Wave T iteration 2 → re-run T.5 → block Wave E if persists

**Config flags (from Part 7 §7.7):**
```python
wave_a5_enabled: bool = False
wave_a5_reasoning_effort: str = "medium"
wave_a5_max_reruns: int = 1
wave_a5_skip_simple_milestones: bool = True
wave_a5_simple_entity_threshold: int = 3
wave_a5_simple_ac_threshold: int = 5
wave_a5_gate_enforcement: bool = False
wave_t5_enabled: bool = False
wave_t5_reasoning_effort: str = "high"
wave_t5_skip_if_no_tests: bool = True
wave_t5_gate_enforcement: bool = False
```

**GATE enforcement error class:** define `GateEnforcementError(RuntimeError)` in `cli.py` or a new `gates.py` module. Raised when GATE 8/9 blocks progression after `wave_a5_max_reruns` exhausted. Caught by orchestrator main loop for clean recovery dispatch.

**`output_schema` JSON Schemas for A.5 and T.5:** use the full validated JSON Schemas inlined at master **§4.8** (Wave A.5, lines 1463-1489) and **§4.9** (Wave T.5, lines 1584-1612) — NOT the informal JSON examples. These are the strict schemas with `additionalProperties: false`, `enum` constraints, and `required` arrays required for Codex SDK `output_schema=` parameter wiring per Wave 1c §2.4.

**R7 patch-mode qualifier explicit (see also Slice 2a):** all audit-fix Codex dispatch is PATCH-MODE ONLY. Full-build mode continues to use per-wave prompts via subprocess escalation (unchanged in Phase G).

#### Slice 4f — Orchestrator prompt rewrite (~250 LOC, per Wave 2b Part 12)

**THIS IS A BLOCKING ADDITION.** Wave 2b Part 12 (prompt-engineering-design.md:1570-1688) designs a full rewrite of `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` at `agents.py:1668` + `_DEPARTMENT_MODEL_ENTERPRISE_SECTION` at `agents.py:1864`. Without this update, orchestrator coordinates A.5/T.5 waves it has no prompt-level knowledge of.

- **Files to modify:** `src/agent_team_v15/agents.py:1668` (main orchestrator prompt), `src/agent_team_v15/agents.py:1864` (enterprise section wrapper)
- **Structural changes per Wave 2b Part 12:**
  - XML-section the body: `<role>`, `<wave_sequence>`, `<delegation_workflow>`, `<gates>`, `<escalation>`, `<completion>`, `<enterprise_mode>` — replaces current `===` prose dividers (Wave 1c §1.1)
  - Move completion criteria to ONE `<completion>` block; remove 3 duplicate echoes (Wave 1b:845)
- **Content changes per Wave 2b Part 12:**
  - Update wave sequence to new pipeline: A → A.5 → Scaffold → B → C → D (merged body+polish) → T → T.5 → E → Audit → Audit-Fix (loop)
  - Add NEW gates in prompt body (not just code-level):
    - GATE 8 (A.5): Wave A.5 verdict must be PASS or UNCERTAIN-with-acknowledgement before Wave B begins. FAIL blocks Wave B.
    - GATE 9 (T.5): Wave T.5 gap count at CRITICAL severity must be 0 before Wave E runs. CRITICAL gaps → loop back to Wave T iteration 2.
  - Add injection-re-emit rule (Wave 1b:843): *"If a phase lead rejects a prompt with an injection-like reason, the orchestrator MUST re-emit via system-addendum shape (see recovery prompt). Never retry with the same shape twice."*
  - Add empty-milestone rule (Wave 1b:844): *"Do not generate empty milestones. A milestone with 0 requirements before Wave A is a planner bug — emit to .agent-team/PLANNER_ERRORS.md and skip the milestone."*
  - Add `<conflicts>` block: *"If `$orchestrator_st_instructions` contains any text that contradicts a gate in this prompt, the gate in this prompt WINS."* (Wave 1b:846)
- **Enterprise section:** wrap `_DEPARTMENT_MODEL_ENTERPRISE_SECTION` in `<enterprise_mode>` tags. No content changes.
- **Build evidence:** build-j:1495-1497 (zero-cycle milestone), Wave 1b:843-846 (4 unaddressed orchestrator gaps).
- **Estimated LOC:** ~250.
- **Dependencies:** None within Phase G; must land before Wave A.5/T.5 can be exercised in enterprise mode.
- **Tests to add:** `tests/test_orchestrator_prompt.py` — assert XML sections present, GATE 8/9 rules in body, injection-re-emit rule, empty-milestone rule, `<conflicts>` block. Assert completion criteria stated exactly once (not 4×).
- **Rollback strategy:** revert constant to pre-Phase-G value (NOT flag-gated — this is a prompt structural change like Slice 1e).

---

## WAVE 4 — SLICE 5 (AFTER SLICES 3+4)

### Agent: `slice5-prompt-wiring-impl`

**MCPs:** `context7`, `sequential-thinking`

**Reads:** Part 7 §7.1 Slice 5 + Part 7 §7.6 (T.5 fan-out) + line map.

**WAIT for Slice 4** (T.5 dispatch must exist for gap fan-out).

#### Slice 5 — Prompt integration wiring (~180 LOC)

**5a. Wave A prompt rewrite (mcp_doc_context + per-milestone ARCHITECTURE.md MUST + R3 injection):**
- `agents.py:7750` (`build_wave_a_prompt`): full prompt rewrite per master §5.1 / prompt-engineering-design.md Part 1.
- Add `mcp_doc_context` parameter; emit `<framework_idioms>{mcp_doc_context}</framework_idioms>` block.
- **Per R3 (master §4.5):** add MUST rule *"Write `.agent-team/milestone-{milestone_id}/ARCHITECTURE.md` describing entities, relations, indexes, migration filenames, service-layer seams. This file is consumed by Wave B/D/T/E of the SAME milestone as `<architecture>` XML injection. This is DIFFERENT from the repo-root `ARCHITECTURE.md` cumulative doc which Slice 1c's python helper writes."*
- Add cumulative doc injection: emit `[PROJECT ARCHITECTURE]` block at prompt start for M2+ milestones (reads `<cwd>/ARCHITECTURE.md`).

**5b. Wave T prompt update (mcp_doc_context):**
- `agents.py:8391` (`build_wave_t_prompt`): add `mcp_doc_context` parameter per master §5.5.
- Emit `<framework_idioms>` block (Jest/Vitest/Playwright idioms).
- Preserve `WAVE_T_CORE_PRINCIPLE` LOCKED block verbatim (agents.py:8374-8388).

**5c. `<architecture>` XML injection into Wave B / D / T / E prompts (per R3):**
- Modify `build_wave_b_prompt`, `build_wave_d_prompt` (merged body from Slice 3), `build_wave_t_prompt`, `build_wave_e_prompt` to read `.agent-team/milestone-{id}/ARCHITECTURE.md` (from Slice 5a Wave A's output) and inject `<architecture>{content}</architecture>` XML tag.
- Per master §4.5 + Wave 2b Parts 3/4/5/7.
- Guard with existence check — if Wave A didn't write the file (prior-milestone compat), skip injection silently.

**5d. T.5 gap list → Wave E prompt:**
- `agents.py:8147` (`build_wave_e_prompt`): inject `<wave_t5_gaps>` block when `v18.wave_t5_gap_list_inject_wave_e=True`
- Read gaps from `.agent-team/milestones/{id}/WAVE_T5_GAPS.json`
- Rule per R5 (master Appendix D): *"For HIGH+ gaps that represent user-visible behavior, include a Playwright test that asserts the described behavior."*

**5e. T.5 gap list → TEST_AUDITOR:**
- `audit_prompts.py:651` (`TEST_AUDITOR_PROMPT`): add rule consuming `WAVE_T5_GAPS.json` when `v18.wave_t5_gap_list_inject_test_auditor=True`
- Rule per R5 + Wave 2b Part 11.4.

**5f. .codex/config.toml snippet:**
- Bundle via `constitution_writer.py` (Slice 1d): write `.codex/config.toml` at project root (same directory where Codex is invoked — `$PWD`, NOT `$CODEX_HOME`; user-specific config at `$CODEX_HOME/config.toml` is separate).
- Content: `[features]\nproject_doc_max_bytes = 65536` per Wave 1c §4.3 (raises AGENTS.md cap from default 32 KiB).

**Config flags:**
```python
mcp_doc_context_wave_a_enabled: bool = False
mcp_doc_context_wave_t_enabled: bool = False
wave_t5_gap_list_inject_wave_e: bool = False
wave_t5_gap_list_inject_test_auditor: bool = False
```

---

## WAVE 5 — TESTS + WIRING VERIFICATION

### Agent: `phase-g-test-engineer`

**MCPs:** `sequential-thinking`

**23 test files to create** (from Part 7 §7.8 + review-driven additions):

| Test File | Slice | What It Tests |
|-----------|-------|--------------|
| `test_claude_md_opt_in.py` | 1a | setting_sources field presence; preserve existing system_prompt (no preset flip) |
| `test_transport_selector.py` | 1b | Module routing by flag |
| `test_architecture_writer.py` | 1c | Cumulative doc: content format, summarization, idempotent init |
| `test_architecture_wave_a_must.py` | 1c/5a | **R3 per-milestone doc**: Wave A prompt contains the MUST; file is written at `.agent-team/milestone-{id}/ARCHITECTURE.md` |
| `test_architecture_injection.py` | 5c | `<architecture>` XML tag injected into Wave B/D/T/E prompts when per-milestone file exists |
| `test_constitution_templates.py` | 1d | Template constants correctness; **3 R8 invariants present** (parallel main.ts, api-client edits, git commit); **LOCKED wording NOT duplicated** into CLAUDE.md/AGENTS.md |
| `test_constitution_writer.py` | 1d | File rendering + **runtime 32 KiB enforcement** (writer asserts / truncates / raises `AgentsMdOverflowError`) |
| `test_recovery_prompt.py` | 1e | No `[SYSTEM:]` in recovery prompts; isolated shape always used |
| `test_scorer_audit_report_schema.py` | **1f (NEW)** | Scorer prompt enumerates all 17 AUDIT_REPORT.json keys; parser accepts output (build-j:1423 regression) |
| `test_audit_fix_classifier.py` | 2a | Codex vs Claude routing by classifier; **patch-mode only** (full-build mode unchanged) |
| `test_compile_fix_codex.py` | 2b | Codex dispatch + flag gating; LOCKED anti-band-aid inherited verbatim |
| `test_wave_d_merged.py` | 3 | Merged prompt content + IMMUTABLE verbatim (agents.py:8803-8808); `[EXPECTED FILE LAYOUT]` rename; `[TEST ANCHOR CONTRACT]` preserved |
| `test_wave_sequence_mutator.py` | 3 | D5 stripped when merged; A5/T5 stripped when disabled; all 3 templates (full_stack/backend_only/frontend_only) |
| `test_orchestrator_prompt.py` | **4f (NEW)** | XML sections; GATE 8/9 rules in body; injection-re-emit rule; empty-milestone rule; `<conflicts>` block; completion stated once (not 4×) |
| `test_wave_a5.py` | 4 | Seeded broken plan → findings JSON + skip conditions + `output_schema` compliance |
| `test_wave_t5.py` | 4 | Seeded weak tests → gaps JSON + skip conditions + `output_schema` compliance |
| `test_gate_enforcement.py` | 4 | `GateEnforcementError` raised; GATE 8 blocks Wave B; GATE 9 blocks Wave E |
| `test_mcp_doc_context_wave_a.py` | 5a | Framework idioms in Wave A prompt |
| `test_mcp_doc_context_wave_t.py` | 5b | Framework idioms in Wave T prompt |
| `test_wave_e_t5_injection.py` | 5d | T.5 gap list in Wave E prompt |
| `test_test_auditor_t5_injection.py` | 5e | T.5 gap list in TEST_AUDITOR |
| `test_codex_config_snippet.py` | 5f | .codex/config.toml written at project root with `project_doc_max_bytes = 65536` |
| `test_audit_finding_cap_continuation.py` | **(NEW)** | 30-finding cap resolution via two-block emission (Wave 2b Part 11 shared audit change) — assertion that MEDIUM findings past cap surface in `<findings_continuation>` block |

**PLUS:** `test_locked_wording_verbatim.py` — asserts IMMUTABLE, WAVE_T_CORE_PRINCIPLE, and _ANTI_BAND_AID_FIX_RULES appear verbatim at `agents.py:8803-8808`, `agents.py:8374-8388`, `cli.py:6168-6193`. Also asserts LOCKED wording does NOT appear in CLAUDE.md/AGENTS.md templates (per Wave 1c §4.4).

**Target:** ~60-90 new tests across 24 files. All must pass. Zero regressions against 10,636 baseline.

**Deferred (not in Phase G scope — flag at kickoff):** Wave 2b Parts 11.1-11.7 designed 6 other auditor prompt updates (requirements, technical, interface, test, MCP/library, PRD fidelity, comprehensive auditors). These are NOT scheduled for Phase G implementation — the only audit-prompts change in Phase G is Slice 1f scorer 17-key schema + Slice 5e TEST_AUDITOR T.5 consumption. The 6 deferred updates are ready design but await Phase H implementation session.

### Agent: `phase-g-wiring-verifier`

**MCPs:** `context7`, `sequential-thinking`

Traces every slice end-to-end:

1. **Slice 1a:** `setting_sources=["project"]` appears in `ClaudeAgentOptions` when flag on
2. **Slice 1b:** transport selector routes to `codex_appserver` when `codex_transport_mode="app-server"`
3. **Slice 1c:** ARCHITECTURE.md written at M1 start; updated at milestone end
4. **Slice 1d:** CLAUDE.md + AGENTS.md + .codex/config.toml rendered at pipeline start
5. **Slice 1e:** zero `[SYSTEM:]` tags in recovery prompt output
6. **Slice 2a:** `classify_fix_provider()` called when `codex_fix_routing_enabled=True`
7. **Slice 2b:** compile-fix routes to Codex when `compile_fix_codex_enabled=True`
8. **Slice 3:** merged-D prompt contains IMMUTABLE verbatim; D5 stripped from sequence
9. **Slice 4:** A.5 fires between A and Scaffold; T.5 fires between T and E; GATE 8/9 enforce
10. **Slice 5:** Wave A/T prompts contain `<framework_idioms>`; Wave E contains `<wave_t5_gaps>`

**Feature flags (all 30 new flags from Part 7 §7.7 — master lines 3449-3495):** verify each flag exists in config.py with correct default. Breakdown: 1 (Slice 1a) + 3 (Slice 1c) + 3 (Slice 1d) + 0 (Slice 1e — removal only) + 3 (Slice 2a) + 1 (Slice 2b) + 4 (Slice 3) + 11 (Slice 4) + 4 (Slice 5) = 30. Plus existing `codex_transport_mode` consumed (no default change) and `recovery_prompt_isolation` retired (Slice 1e).

**Deliverable:** `docs/plans/2026-04-17-phase-g-wiring-verification.md`

---

## WAVE 6 — TEST SUITE VALIDATION

`pytest tests/ -v --tb=short`

**Pass criteria:**
- Baseline 10,636 preserved
- ~50-80 new tests passing
- ZERO new failures

**Iteration protocol:** fix failures. If source code changes needed beyond test files, HALT and authorize.

---

## WAVE 7 — FINAL REPORT + COMMIT

### Team lead deliverables

1. `docs/plans/2026-04-17-phase-g-report.md`:
   - Each slice: files changed, LOC, tests added, flags added
   - Wiring verification: all 10 checks PASS/FAIL
   - LOCKED wording: confirmed verbatim
   - Line map: any shifts documented
   - HALT events + resolutions

2. `v18 test runs/session-G-validation/`:
   - `preexisting-baseline.txt`
   - `line-map-verification.log`
   - `locked-wording-check.log`
   - `transport-selector-test.log`
   - `architecture-writer-test.log`
   - `wave-d-merged-immutable-check.log`
   - `gate-enforcement-test.log`
   - Production-caller-proof scripts

3. Commit on `phase-g-pipeline-restructure` branch.

---

## PHASE G EXIT CRITERIA

### Implementation
- [ ] Slice 1a: `setting_sources` fix — flag gated, default OFF; preset flip NOT applied (preserves D-05 isolation)
- [ ] Slice 1b: transport selector — routes `codex_appserver` when `app-server`
- [ ] Slice 1c: ARCHITECTURE.md cumulative writer — `init_if_missing` + `append_milestone` + summarization (python-written, `<cwd>/ARCHITECTURE.md`)
- [ ] Slice 1d: CLAUDE.md + AGENTS.md renderers — templates with **3 R8 canonical invariants** (project conventions — NOT LOCKED wording) + writer + runtime 32 KiB enforcement (not just config field)
- [ ] Slice 1e: Recovery kill — `[SYSTEM:]` branch deleted, `recovery_prompt_isolation` flag removed (NON-FLAG-GATED per R2)
- [ ] **Slice 1f (NEW): SCORER_AGENT_PROMPT 17-key schema — audit_prompts.py:1292 prepends `<output_schema>` block with all 17 keys enumerated (NON-FLAG-GATED — build-j:1423 fix)**
- [ ] Slice 2a: Audit-fix classifier wired — `classify_fix_provider()` called, Codex dispatch working, **patch-mode only per R7**
- [ ] Slice 2b: Compile-fix Codex — `_build_compile_fix_prompt` Codex-native, flag gated; LOCKED anti-band-aid verbatim
- [ ] Slice 3: Wave D merged — single Claude prompt with IMMUTABLE verbatim, `[EXPECTED FILE LAYOUT]` rename, D5 stripped, provider flipped, all 3 templates updated
- [ ] Slice 4a: Wave A.5 — Codex plan review dispatching, findings JSON, skip conditions, **output_schema from master §4.8 inlined JSON Schema**
- [ ] Slice 4b: Wave T.5 — Codex edge-case audit dispatching, gaps JSON, skip conditions, **output_schema from master §4.9 inlined JSON Schema**
- [ ] Slice 4e: GATE 8/9 — orchestrator enforcement with re-run logic + `GateEnforcementError` class
- [ ] **Slice 4f (NEW): Orchestrator prompt rewrite — `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` at agents.py:1668 + `_DEPARTMENT_MODEL_ENTERPRISE_SECTION` at agents.py:1864; XML sections; GATE 8/9 rules IN PROMPT BODY; injection-re-emit rule; empty-milestone rule; `<conflicts>` block (Wave 2b Part 12)**
- [ ] Slice 5a: Wave A prompt rewrite — mcp_doc_context + **R3 per-milestone ARCHITECTURE.md MUST**
- [ ] Slice 5b: Wave T prompt update — mcp_doc_context
- [ ] **Slice 5c (NEW per R3): `<architecture>` XML injection into Wave B/D/T/E prompts within same milestone**
- [ ] Slice 5d: T.5 gap fan-out to Wave E
- [ ] Slice 5e: T.5 gap fan-out to TEST_AUDITOR
- [ ] Slice 5f: .codex/config.toml at project root with `project_doc_max_bytes = 65536`

### Quality
- [ ] All 30 new feature flags in config.py with correct defaults (Part 7 §7.7 — master lines 3449-3495; breakdown: 1+3+3+0+3+1+4+11+4)
- [ ] All flags default OFF except Slice 1e (recovery kill) and Slice 1f (scorer schema) and Slice 4f (orchestrator prompt) — all three are non-flag-gated structural fixes
- [ ] LOCKED wording verbatim in system prompts: IMMUTABLE (`agents.py:8803-8808`), WAVE_T_CORE_PRINCIPLE (`agents.py:8374-8388`), `_ANTI_BAND_AID_FIX_RULES` (`cli.py:6168-6193`)
- [ ] LOCKED wording NOT duplicated into CLAUDE.md/AGENTS.md (per Wave 1c §4.4)
- [ ] R8 canonical invariants (project conventions) present in CLAUDE.md + AGENTS.md templates (Slice 1d)
- [ ] R3 two-doc ARCHITECTURE.md model functional (cumulative + per-milestone; Slice 1c + Slice 5a + Slice 5c)
- [ ] 24 test files (18 original + 5 review-driven additions + 1 locked-wording test)
- [ ] ~60-90 new tests passing
- [ ] 10,636 baseline preserved
- [ ] ZERO regressions
- [ ] Wiring verification: all 10 checks PASS

### Process
- [ ] Architecture report + wiring verification + final report produced
- [ ] Production-caller-proof artifacts at `session-G-validation/`
- [ ] Commit on `phase-g-pipeline-restructure` branch
- [ ] **Consolidation step:** merge → `integration-2026-04-15-closeout`; verify tests green; confirm HEAD SHA

---

## INVIOLABLE RULES

1. **The investigation report Part 7 is the CONTRACT.** Execute it exactly. Don't re-design.
2. **Part 5 has the EXACT prompt text.** Use it for every prompt rewrite/addition.
3. **LOCKED wording is LOCKED.** IMMUTABLE block, WAVE_T_CORE_PRINCIPLE, _ANTI_BAND_AID_FIX_RULES — verbatim copy.
4. **All new flags default OFF.** Exception: Slice 1e recovery kill (non-flag-gated per R2).
5. **Read before writing.** Every file read fully before first edit.
6. **Mid-flight halts.** If file:line targets shifted, HALT and use updated line map.
7. **No regressions.** 10,636 / 0.
8. **Context7 on every framework/SDK reference.** Claude Agent SDK, Codex CLI, NestJS, Prisma, Next.js.
9. **Sequential-thinking on every non-trivial implementation decision.**
10. **Honest assessment.** If something from the investigation report doesn't match reality, document it. Don't silently adapt.

---

## WHAT TO DO FIRST

1. **Read** `docs/plans/2026-04-17-phase-g-investigation-report.md` Part 7 (the contract)
2. **Skim** Part 5 (prompt designs) — you'll reference it during implementation
3. **Run pre-flight.** Confirm 10,636 / 0. Confirm HEAD `466c3b9`.
4. **Create task list** for all 8 agents.
5. **Launch Wave 1** (line map verification). Wait for map.
6. **HALT POINT.** Review line map. Authorize Wave 2.
7. **Launch Wave 2** (Slices 1 + 2 parallel). Slice 2 waits for Slice 1b.
8. **Launch Wave 3** (Slices 3 + 4 parallel, after Wave 2).
9. **Launch Wave 4** (Slice 5, after Wave 3).
10. **Launch Wave 5** (tests + wiring verification).
11. **Wave 6** (full pytest).
12. **Wave 7** (report + commit).
13. **Consolidation:** merge to integration; verify tests green.

Phase G is the FINAL code change. After this: Phase FINAL smoke. The pipeline will have the optimized wave sequence, model-specific prompts, persistent architecture docs, cross-model plan review, edge-case test auditing, and Codex-routed fixes. Every agent prompt tuned for its target model based on 12,488 lines of context7-verified research + build log evidence.
