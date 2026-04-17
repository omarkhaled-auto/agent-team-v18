# Phase G Wiring Verification
**Branch:** phase-g-pipeline-restructure
**Date:** 2026-04-17
**Verifier:** phase-g-wiring-verifier
**Base SHA:** 466c3b9 + Slices 1–5

## Re-verification (2026-04-17)

Both defects called out in the original report have been fixed and re-verified.

### Fix 1 — Slice 1a/1c/1d coerce entries (slice1's fix): **CONFIRMED PASS**
- All 7 flags now appear as explicit `_coerce_bool` / `_coerce_int` entries inside `_dict_to_config` at `config.py:2567-2602`:
  - `claude_md_setting_sources_enabled` at config.py:2567-2572 (`_coerce_bool`)
  - `architecture_md_enabled` at config.py:2574-2577 (`_coerce_bool`)
  - `architecture_md_max_lines` at config.py:2578-2583 (`_coerce_int`)
  - `architecture_md_summarize_floor` at config.py:2584-2590 (`_coerce_int`)
  - `claude_md_autogenerate` at config.py:2591-2594 (`_coerce_bool`)
  - `agents_md_autogenerate` at config.py:2595-2598 (`_coerce_bool`)
  - `agents_md_max_bytes` at config.py:2599-2602 (`_coerce_int`)
- End-to-end smoke check: `python -c "from agent_team_v15.config import _dict_to_config; cfg, _ = _dict_to_config({'v18':{...}}); ..."` printed `True True 999 9 True True 99999` — YAML-layer overrides now flow through to `V18Config` correctly.
- Coerce-miss count drops from 7 → 0. Flag table rows 1–7 updated from FAIL → PASS.

### Fix 2 — GATE 8/9 caller wiring (slice4's fix): **CONFIRMED PASS**
- `_enforce_gate_a5` is now imported and called at `wave_executor.py:4058,4070` inside the `elif wave_letter == "A5":` branch (lines 4051-4118). A bounded re-run loop dispatches Wave A with `[PLAN REVIEW FEEDBACK]` (formatted by `_format_plan_review_feedback`) and re-executes A.5; bound is enforced by `wave_a5_max_reruns` inside `_enforce_gate_a5`.
- `_enforce_gate_t5` is now imported and called at `wave_executor.py:4125,4136` inside the `elif wave_letter == "T5":` branch (lines 4119+). Similar bounded re-run loop injects gap list and re-runs Wave T iteration 2.
- Grep confirms: `_enforce_gate_a5` / `_enforce_gate_t5` now have 2 non-comment hits each in `wave_executor.py` (import + call), in addition to the original definitions at `cli.py:9674,9728`.
- Orphan gate-function defect resolved. Trace #10 (Slice 4) upgraded from **PARTIAL PASS** → **PASS**.

**Updated summary counts:**
- Traces: **11/11 PASS** (was 10/11 PASS + 1/11 PARTIAL)
- Flags: **30/30 defined + consumed + coerced** (was 30/30 defined + consumed, 23/30 coerced)
- Removed: 3/3 gone (unchanged)
- Strict orphans: 0 (unchanged)
- Defect classes: **0** (was 2 — both resolved)

All Phase G wiring verification checks are now GREEN.

---

## End-to-End Trace Results

| # | Slice | Trace | Verdict | Evidence |
|---|-------|-------|---------|----------|
| 1 | 1a | `setting_sources=["project"]` added to `ClaudeAgentOptions` when `claude_md_setting_sources_enabled=True` | **PASS** | `cli.py:450-451` inside `_build_options` appends `opts_kwargs["setting_sources"] = ["project"]` when flag on; `opts_kwargs` flows to `ClaudeAgentOptions(**opts_kwargs)` at `cli.py:458` |
| 2 | 1b | Transport selector routes to `codex_appserver` when `codex_transport_mode="app-server"` | **PASS** | `cli.py:3229-3233` reads `getattr(v18, "codex_transport_mode", "exec")` and branches: `import agent_team_v15.codex_appserver` on `"app-server"`, else `codex_transport` |
| 3 | 1c | `<cwd>/ARCHITECTURE.md` written at M1 start; updated at milestone end; summarization triggered at >max_lines | **PASS** | Init at `wave_executor.py:3888-3894` (flag-gated `architecture_writer.init_if_missing`); append at `wave_executor.py:4485-4498` (calls `append_milestone` then `summarize_if_over` with `max_lines=architecture_md_max_lines`, `summarize_floor=architecture_md_summarize_floor`) |
| 4 | 1d | CLAUDE.md + AGENTS.md + .codex/config.toml rendered at pipeline start when flags on; AGENTS.md size enforced at runtime | **PASS** | `wave_executor.py:3896-3907` calls `constitution_writer.write_all_if_enabled`; the writer at `constitution_writer.py:119-147` reads all three flags and `constitution_writer.py:128-135` enforces `agents_md_max_bytes` via `AgentsMdOverflowError` (runtime, not merely declared) |
| 5 | 1e | Zero `[SYSTEM:]` tags in recovery prompt output (structural removal) | **PASS** | `_build_recovery_prompt_parts` at `cli.py:9844-9859+` returns `(system_addendum, user_prompt)` unconditionally; legacy `[SYSTEM: ...]` branch GONE; only two narrative comment strings (`cli.py:402`, `cli.py:9854`) reference the retired pseudo-tag historically |
| 6 | 1f | Scorer prompt body contains all 17 AUDIT_REPORT keys | **PASS** | `audit_prompts.py:1292-1316` SCORER_AGENT_PROMPT embeds `<output_schema>` listing 17 keys: schema_version, generated, milestone, audit_cycle, overall_score, max_score, verdict, threshold_pass, auditors_run, raw_finding_count, deduplicated_finding_count, findings, fix_candidates, by_severity, by_file, by_requirement, audit_id |
| 7 | 2a | `classify_fix_provider()` called when `codex_fix_routing_enabled=True` AND patch-mode | **PASS** | `cli.py:6605-6615` in `_run_audit_fix_unified` (patch-mode, before `ClaudeSDKClient` call at `cli.py:6441`): gates on `v18.codex_fix_routing_enabled` AND `_provider_routing`, imports and calls `classify_fix_provider(affected_files=target_files, issue_type=feature_name)` (R7 patch-mode qualifier honored) |
| 8 | 2b | Compile-fix routes to Codex when `compile_fix_codex_enabled=True` | **PASS** | `wave_executor.py:3063-3079`: `use_codex = bool(compile_fix_codex_enabled AND provider_routing)` → `_build_compile_fix_prompt(..., use_codex_shell=True)`; wrap at `codex_fix_prompts.py` (referenced in module header line 5–6) |
| 9 | 3 | Merged-D prompt contains IMMUTABLE verbatim; D5 stripped; provider flipped to Claude | **PASS** | `agents.py:9030-9038` emits the IMMUTABLE + INTERPRETATION block verbatim (matches LOCKED `agents.py:8803-8808` byte-for-byte); D5 stripped via `wave_executor.py:412-421` (D5 re-insertion gated by `not wave_d_merged_enabled`); provider flipped at `cli.py:3239-3243` (`D="claude" if wave_d_merged else provider_map_d`) |
| 10 | 4 | A.5 fires between A and Scaffold; T.5 fires between T and E; GATE 8/9 enforce; orchestrator prompt has XML sections + GATE 8/9 + injection re-emit + empty-milestone + `<conflicts>` + "Build is COMPLETE" once | **PASS** ✅ (upgraded 2026-04-17 after slice4's fix) | Sequence: `WAVE_SEQUENCES["full_stack"]=["A","A5","Scaffold","B","C","D","T","T5","E"]` at `wave_executor.py:308`; A.5/T.5 dispatch `elif` branches at `wave_executor.py:3509` and `:3521` + `:4019`/`:4031`/`:4051`/`:4119`; orchestrator prompt at `agents.py:1668+` has `<role>`/`<wave_sequence>`/`<gates>`/`<escalation>`/`<completion>`/`<conflicts>` sections with GATE 8 (`:1774-1778`), GATE 9 (`:1779-1782`), injection re-emit (`:1791-1794`), empty-milestone rule (`:1795-1797`), `<conflicts>` block (`:1845-1848`), and "Build is COMPLETE" appears exactly once. **GATE 8/9 Python-side enforcement now wired:** `wave_executor.py:4058,4070` imports + calls `_enforce_gate_a5` in a bounded re-run loop (Wave A re-dispatched with `[PLAN REVIEW FEEDBACK]` via `_format_plan_review_feedback`; bound by `wave_a5_max_reruns`); `wave_executor.py:4125,4136` imports + calls `_enforce_gate_t5` in a matching loop that re-runs Wave T iteration 2. Both loops raise `GateEnforcementError` on exhaustion — HALT contract honored. |
| 11 | 5 | Wave A/T prompts contain `<framework_idioms>` when flag on; Wave E contains `<wave_t5_gaps>` when flag on; `<architecture>` XML injected into B/D/T/E | **PASS** | `<framework_idioms>` Wave A at `agents.py:7895-7901`, Wave T at `:8603-8608` (both flag-gated on `mcp_doc_context_wave_a/t_enabled`); `<wave_t5_gaps>` in Wave E at `agents.py:7795-7819` (flag-gated on `wave_t5_gap_list_inject_wave_e`); `<architecture>` XML injection hooks at `agents.py:7996` (A), `:8078` (B), `:8320` (E), `:8582` (T), `:8924` (D) — B/D/T/E covered. `_n17_wave_prefetch_enabled` at `cli.py:1955-1965` broadened to A/T when flags on. |

**Traces summary: 11/11 full PASS** (Slice 4 upgraded from PARTIAL → PASS after slice4's 2026-04-17 fix wired `_enforce_gate_a5` / `_enforce_gate_t5` callers in `wave_executor.py`).

## 30 Feature Flag Verification

| # | Slice | Flag | Default | Coerce | Consumed At |
|---|-------|------|---------|--------|-------------|
| 1 | 1a | `claude_md_setting_sources_enabled` | `bool = False` (config.py:793) | **PASS** ✅ (config.py:2567-2572, `_coerce_bool`) | `cli.py:450` |
| 2 | 1c | `architecture_md_enabled` | `bool = False` (config.py:795) | **PASS** ✅ (config.py:2574-2577, `_coerce_bool`) | `wave_executor.py:3888`, `:4485`; `agents.py:7760`,`:7861`,`:8000`,`:8081`,`:8321`,`:8585`,`:8926` |
| 3 | 1c | `architecture_md_max_lines` | `int = 500` (config.py:796) | **PASS** ✅ (config.py:2578-2583, `_coerce_int`) | `wave_executor.py:4497` |
| 4 | 1c | `architecture_md_summarize_floor` | `int = 5` (config.py:797) | **PASS** ✅ (config.py:2584-2590, `_coerce_int`) | `wave_executor.py:4498` |
| 5 | 1d | `claude_md_autogenerate` | `bool = False` (config.py:799) | **PASS** ✅ (config.py:2591-2594, `_coerce_bool`) | `wave_executor.py:3900`; `constitution_writer.py:119` |
| 6 | 1d | `agents_md_autogenerate` | `bool = False` (config.py:800) | **PASS** ✅ (config.py:2595-2598, `_coerce_bool`) | `wave_executor.py:3901`; `constitution_writer.py:126`,`:141` |
| 7 | 1d | `agents_md_max_bytes` | `int = 32768` (config.py:801) | **PASS** ✅ (config.py:2599-2602, `_coerce_int`) | `constitution_writer.py:128` |
| 8 | 2a | `codex_fix_routing_enabled` | `bool = False` (config.py:848) | **PASS** (config.py:2664-2670) | `cli.py:6607` (patch-mode gate) |
| 9 | 2a | `codex_fix_timeout_seconds` | `int = 900` (config.py:849) | **PASS** (config.py:2671-2677) | `cli.py:6291`; `wave_executor.py:2436` (both via getattr-fallback) |
| 10 | 2a | `codex_fix_reasoning_effort` | `str = "high"` (config.py:850) | **PASS** (config.py:2678-2684) | `cli.py:6292`; `wave_executor.py:2437` (getattr-fallback) |
| 11 | 2b | `compile_fix_codex_enabled` | `bool = False` (config.py:855) | **PASS** (config.py:2685-2691) | `wave_executor.py:3067` |
| 12 | 3 | `wave_d_merged_enabled` | `bool = False` (config.py:840) | **PASS** (config.py:2602-2605) | `cli.py:3239`; `agents.py:9455`; `wave_executor.py:417`,`:3015`,`:3989`,`:4177` |
| 13 | 3 | `wave_d_compile_fix_max_attempts` | `int = 2` (config.py:841) | **PASS** (config.py:2606-2612) | `wave_executor.py:3016` |
| 14 | 3 | `provider_map_a5` | `str = "codex"` (config.py:831) | **PASS** (config.py:2594-2597) | `cli.py:3241` |
| 15 | 3 | `provider_map_t5` | `str = "codex"` (config.py:832) | **PASS** (config.py:2598-2601) | `cli.py:3244` |
| 16 | 4 | `wave_a5_enabled` | `bool = False` (config.py:864) | **PASS** (config.py:2692-2695) | `wave_executor.py:402` (sequence strip); `wave_a5_t5.py` (guard) |
| 17 | 4 | `wave_a5_reasoning_effort` | `str = "medium"` (config.py:865) | **PASS** (config.py:2696-2699) | `wave_a5_t5.py:618` |
| 18 | 4 | `wave_a5_max_reruns` | `int = 1` (config.py:866) | **PASS** (config.py:2700-2703) | `cli.py:9712` (inside `_enforce_gate_a5`) |
| 19 | 4 | `wave_a5_skip_simple_milestones` | `bool = True` (config.py:867) | **PASS** (config.py:2704-2710) | `wave_a5_t5.py:189` |
| 20 | 4 | `wave_a5_simple_entity_threshold` | `int = 3` (config.py:868) | **PASS** (config.py:2711-2717) | `wave_a5_t5.py:190` |
| 21 | 4 | `wave_a5_simple_ac_threshold` | `int = 5` (config.py:869) | **PASS** (config.py:2718+) | `wave_a5_t5.py:191` |
| 22 | 4 | `wave_a5_gate_enforcement` | `bool = False` (config.py:870) | **PASS** | `cli.py:9697` (inside `_enforce_gate_a5`; function is defined but never called — see orphan section) |
| 23 | 4 | `wave_t5_enabled` | `bool = False` (config.py:877) | **PASS** (config.py:2732-2735) | `wave_executor.py:406` (sequence strip); `wave_a5_t5.py:746`,`:751` |
| 24 | 4 | `wave_t5_reasoning_effort` | `str = "high"` (config.py:878) | **PASS** (config.py:2736-2739) | `wave_a5_t5.py:788` |
| 25 | 4 | `wave_t5_skip_if_no_tests` | `bool = True` (config.py:879) | **PASS** (config.py:2740-2746) | `wave_a5_t5.py:747` |
| 26 | 4 | `wave_t5_gate_enforcement` | `bool = False` (config.py:880) | **PASS** (config.py:2747-2753) | `cli.py:9752` (inside `_enforce_gate_t5`; function is defined but never called — see orphan section) |
| 27 | 5 | `mcp_doc_context_wave_a_enabled` | `bool = False` (config.py:894) | **PASS** (config.py:2754-2760) | `cli.py:1962`; `agents.py:7895` |
| 28 | 5 | `mcp_doc_context_wave_t_enabled` | `bool = False` (config.py:895) | **PASS** (config.py:2761-2767) | `cli.py:1964`; `agents.py:8603` |
| 29 | 5 | `wave_t5_gap_list_inject_wave_e` | `bool = False` (config.py:896) | **PASS** (config.py:2768-2774) | `agents.py:7795` |
| 30 | 5 | `wave_t5_gap_list_inject_test_auditor` | `bool = False` (config.py:897) | **PASS** (config.py:2775-2781) | `audit_prompts.py:1554` |

**Flag summary: 30/30 fields present at correct type+default; 30/30 coerced; 30/30 consumed at least once in production.**

**Coerce gap RESOLVED (2026-04-17):** slice1 added explicit coerce entries for the 7 Slice 1a/1c/1d flags at `config.py:2567-2602`. Smoke check confirmed YAML-layer overrides now flow through `V18Config` correctly (`True True 999 9 True True 99999`). Original FAIL verdicts above converted to PASS.

## Removed Flags Verification

- `recovery_prompt_isolation` field: **REMOVED** — only `config.py:942` comment remains (`# The recovery_prompt_isolation flag is retired.`) inside the surrounding commented block `config.py:938-942`. No `V18Config` attribute; no `_coerce_bool(recovery_prompt_isolation=...)` entry.
- `recovery_prompt_isolation` coerce: **REMOVED** — zero live references in config.py beyond the narrative comment.
- `[SYSTEM:]` cli.py legacy branch: **REMOVED** — zero active-code occurrences of `[SYSTEM:` in `cli.py`; only two comment-lines survive: `cli.py:402` ("the system channel instead of embedding a fake `[SYSTEM: ...]` tag in") describing the fix, and `cli.py:9854` inside the `_build_recovery_prompt_parts` docstring ("the legacy ``[SYSTEM: ...]`` pseudo-tag shape was deleted"). The legacy else-branch at `cli.py:9525-9539` is gone; function returns `(system_addendum, user_prompt)` unconditionally.

**Removed flags summary: 3/3 confirmed gone.**

## Orphan Flag Report

Flags defined AND read at least once in production code (non-test) are NOT orphans per verifier rules. Running that check against the 30 flags above:

- 30/30 Phase G flags have at least one live consumer outside config.py.
- Zero traditional orphan flags (flag declared and never read).
- **All defect classes from the original report are RESOLVED (2026-04-17):**
  - Coerce-layer orphans (7 flags) — **FIXED** by slice1 at `config.py:2567-2602`. YAML overrides confirmed via smoke test.
  - Gate-function orphans (2 functions) — **FIXED** by slice4. `_enforce_gate_a5` imported + called at `wave_executor.py:4058,4070`; `_enforce_gate_t5` imported + called at `wave_executor.py:4125,4136`. Both inside bounded re-run loops that propagate `GateEnforcementError` on exhaustion.

**Orphan flag summary: 0 strict orphans; 0 defect classes (all resolved).**

## Summary

- **Traces:** **11/11 PASS** (Slice 4 upgraded PARTIAL → PASS after fix)
- **Flags:** **30/30 defined + consumed + coerced** (was 23/30 coerced; 7 coerce entries added by slice1)
- **Removed:** 3/3 confirmed gone (recovery_prompt_isolation field, coerce, `[SYSTEM:]` branch)
- **Orphans:** 0 strict, 0 defect classes (both original defect classes resolved)
- **LOCKED wording:** preserved verbatim in merged-D (IMMUTABLE block bytewise matches `agents.py:8803-8808` at `agents.py:9033-9038`)
- **Deliverable path:** `docs/plans/2026-04-17-phase-g-wiring-verification.md`

All Phase G wiring verification checks are GREEN. No outstanding follow-ups.
