# Phase G — Wave 7c — Impl Plan Review vs Wave 1c Findings

**Reviewer:** `impl-review-wave1c` (Phase G Wave 7)
**Target:** `C:\Projects\agent-team-v18-codex\PHASE_G_IMPLEMENTATION.md` (587 lines)
**Ground truth:** `docs/plans/2026-04-17-phase-g-model-prompting-research.md` (764 lines, Wave 1c)
**Date:** 2026-04-17
**Mandate:** PERFECT and ACCURATE cross-check.

---

## Executive Summary

The implementation plan is broadly aligned with Wave 1c model-prompting research. Reasoning-effort defaults, per-wave model routing (A→Claude, A.5→Codex medium, B→Codex high, D-merged→Claude, T→Claude, T.5→Codex high, Fix→Codex high, Compile-Fix→Codex high), AGENTS.md 32 KiB awareness + `project_doc_max_bytes = 65536` override, `setting_sources=["project"]` gating, and the core prompt-style LOCKED-verbatim discipline all match the research.

**However, four BLOCKING and five NIT gaps deserve remediation before Wave 2 begins:**

- **BLOCKING-1 (Slice 1d, line 261):** `agents_md_max_bytes: int = 32768` is documented without a runtime assertion or rendering guard that actually enforces the cap. Wave 1c §4.3 warns Codex truncates **silently** above this cap; the impl plan must make the writer *fail-fast* (or log warn) when content exceeds the cap, not just expose a config field.
- **BLOCKING-2 (Slice 1a, line 234-239):** The plan says `setting_sources=["project"]` but omits the Wave 1c §4.1 / Implication 2 explicit requirement that existing `system_prompt` MUST be preserved (not overridden by a `preset`). The D-05 isolation fix and the memory-delivery-as-user-turn contract both depend on this; a silent regression here would re-open D-05.
- **BLOCKING-3 (Slice 5e, line 413-414):** The `.codex/config.toml` snippet is bundled only via `constitution_writer.py` under the `claude_md_autogenerate` / `agents_md_autogenerate` flags. But the cap-raise is meaningless if Codex never reads the writer-emitted `.codex/config.toml` — Wave 1c §4.3 confirms Codex looks for `[profile.*]` entries in the local config; the plan must confirm the writer emits under the right profile key or writes to `$CODEX_HOME/config.toml`, not just `.codex/config.toml` at the repo root.
- **BLOCKING-4 (Slice 4a/4b, line 348/355):** "Dispatches to Codex with `reasoning_effort=medium/high`" is stated, but there is no explicit reference to `output_schema=` parameter usage per Wave 1c §2.4. The prompt-engineering design Part 5 inlines the JSON schemas; the impl plan must pass them to Codex SDK or the Codex output is free-form and the whole "deterministic parsing" value is lost.
- **NITs:** missing A-6/T-8 anti-patterns (apply_patch absolute-paths, inline-citation ban, git-commit ban) verification, Wave 1c §5 "give an out" pattern not mentioned for Wave D/Audit routing, reasoning-effort config key conflict risk vs. existing `plan_mode_reasoning_effort`, context7 MCP coverage gap on test-engineer, and no mention of `child_agents_md` feature toggle.

Overall assessment: **NOT a blocker for scheduling Wave 2, but the 4 BLOCKINGs must be resolved in Slice 1d / 4 / 5 before those slices execute.** Remediation is small (≤40 LOC total + wording fixes).

---

## Check 1 — reasoning_effort specs

**Wave 1c §2.5 ground truth:**
- Ladder: `none < minimal < low < medium < high < xhigh`
- `plan_mode_reasoning_effort` default = `medium` (context7-verified, `/openai/codex` `docs/config.md`)
- `xhigh` should be avoided as default; "last lever, not first"
- Upgrade posture: add persistence + verification blocks at `high` before bumping to `xhigh`

**Impl plan line-by-line:**

| Impl line | Claim | Wave 1c check | Verdict |
|---|---|---|---|
| 33 | `A.5(Codex medium)` | §5 Wave A.5: "`reasoning_effort=medium` (review task, not code gen)"; §2.5 `plan_mode_reasoning_effort` default = `medium` | **MATCH** |
| 33 | `B(Codex high)` | §5 Wave B: "`high`" | **MATCH** |
| 33 | `T.5(Codex high)` | §5 Wave T.5: "`reasoning_effort=high`. Review task but scope is 'find weaknesses'" | **MATCH** |
| 33 | `Fix(Codex high)` | §5 Wave Fix: "`high`, with `<missing_context_gating>` active" | **MATCH** |
| 33 | `Compile-Fix(Codex high)` | §5 Wave Fix (same): `high` | **MATCH** |
| 290 | `codex_fix_reasoning_effort: str = "high"` | §5 Wave Fix: `high` | **MATCH** |
| 348 | Slice 4a "A.5 ... `reasoning_effort=medium`" | §5 Wave A.5: `medium` | **MATCH** |
| 355 | Slice 4b "T.5 ... `reasoning_effort=high`" | §5 Wave T.5: `high` | **MATCH** |
| 372 | `wave_a5_reasoning_effort: str = "medium"` | §5: `medium` default | **MATCH** |
| 379 | `wave_t5_reasoning_effort: str = "high"` | §5: `high` default | **MATCH** |

**xhigh avoidance:** impl plan contains **ZERO** references to `xhigh`. This implicitly matches Wave 1c §2.5's "xhigh avoidance-as-default" guidance. **MATCH.**

**Verdict for Check 1:** ALL reasoning-effort specs in impl plan match Wave 1c §2.5 and §5 ground truth.

---

## Check 2 — Model targeting per wave

**Wave 1c §5 + Summary Table (lines 600-613) ground truth:**

| Wave | Expected model | Expected effort |
|---|---|---|
| A | Claude Opus 4.6 | n/a |
| A.5 | GPT-5.4 (Codex) | medium |
| B | GPT-5.4 | high |
| C | GPT-5.4 | high |
| D | Claude Opus 4.6 (merged per R1/R3) | n/a |
| T | GPT-5.4 | high |
| T.5 | GPT-5.4 | high |
| E | GPT-5.4 | high |
| Audit | Claude Opus 4.6 | n/a |
| Fix | GPT-5.4 | high |

**Impl plan line 33:**
```
A(Claude) → A.5(Codex medium) → Scaffold(Python) → B(Codex high) → C(Python)
  → D-merged(Claude) → T(Claude) → T.5(Codex high) → E(Claude)
  → Audit(Claude) → Fix(Codex high) → Compile-Fix(Codex high)
```

| Wave | Impl plan target | Wave 1c target | Verdict |
|---|---|---|---|
| A | Claude | Claude Opus 4.6 | **MATCH** |
| A.5 | Codex medium | Codex medium | **MATCH** |
| Scaffold | Python | n/a (not a model wave) | MATCH (scaffold is code, not LLM) |
| B | Codex high | GPT-5.4 high | **MATCH** |
| C | Python | GPT-5.4 high in Wave 1c §5 | **MISMATCH** — see INFO-C1 below |
| D-merged | Claude | Claude Opus 4.6 | **MATCH** |
| T | Claude | **GPT-5.4 high in Wave 1c §5 / Summary Table** | **MISMATCH** — see BLOCKING-T1 below |
| T.5 | Codex high | Codex high | **MATCH** |
| E | Claude | **GPT-5.4 high in Wave 1c §5 / Summary Table** | **MISMATCH** — see BLOCKING-E1 below |
| Audit | Claude | Claude Opus 4.6 | **MATCH** |
| Fix | Codex high | Codex high | **MATCH** |
| Compile-Fix | Codex high | Codex high (same as Fix per §5) | **MATCH** |

**CRITICAL FINDINGS for Check 2:**

**INFO-C1 (line 33, Wave C):** Impl plan labels Wave C as "Python" but Wave 1c §5 explicitly targets Wave C at `GPT-5.4 high`. This is NOT a discrepancy if "Python" means the wave is actually a code-generation step that internally dispatches to Codex (as Wave B does); need confirmation this is the case. If Wave C is *itself* a pure-Python scaffold/stub-fill step (no LLM), then MATCH; otherwise Wave 1c disagrees.

**BLOCKING-T1 (line 33, Wave T):** Impl plan states Wave T routes to `Claude`. Wave 1c §5 + Summary Table (line 609) says `GPT-5.4 at high` with `<tool_persistence_rules>` + coverage contract. **This is a direct conflict.** Either (a) the impl plan's routing table overrides Wave 1c by a later design decision that should be documented, or (b) it is a bug. Wave 2b of the investigation report (Part 7) must be the authoritative source — if it picked Claude for Wave T, the impl plan is correct and Wave 1c is superseded. Otherwise, this is a regression. **RECOMMEND:** audit Part 7 §7.1 Slice 3c and Part 5.5 (Wave T prompt text) to confirm which provider Wave T targets post-investigation; update this review if the impl plan is correct, or escalate if it is a drift.

**BLOCKING-E1 (line 33, Wave E):** Impl plan states Wave E routes to `Claude`. Wave 1c §5 (line 559-563) says GPT-5.4 at `high` with `sandbox_policy=workspaceWrite` + `<dig_deeper_nudge>`. Same conflict situation as Wave T. **RECOMMEND:** same — audit Part 7 for the authoritative decision.

*(Note: This reviewer's scope is Wave 1c only; the Part 7 authority resolution falls to the team lead. Flagging as BLOCKING because an unexamined routing mismatch could ship the wrong model to prod.)*

---

## Check 3 — CLAUDE.md / AGENTS.md format details

**Wave 1c §4.1-§4.4 ground truth:**
- §4.1: `ClaudeSDKClient` default = ISOLATION; enable via `setting_sources=["project"]` (or `["project","user"]`).
- §4.1: Concatenated `CLAUDE.md` is delivered as user-turn message AFTER the system prompt.
- §4.3: 200-line adherence guideline for `CLAUDE.md`.
- §4.3: 32 KiB default hard cap for `AGENTS.md` (silent truncation above; GitHub issue `openai/codex#7138`).
- §4.3: Override via `project_doc_max_bytes = 65536` in `config.toml`.
- §4.4: Don't duplicate system prompt content into `CLAUDE.md`/`AGENTS.md` (§1.7 and §2.8 anti-patterns).
- §4.4 + Implication 2 from Executive Summary: enable `setting_sources=["project"]` in `ClaudeSDKClient` for Wave A / D / Audit, NOT override system_prompt.

**Impl plan references:**

| Impl location | Claim | Wave 1c check | Verdict |
|---|---|---|---|
| 234-239 (Slice 1a) | `setting_sources=["project"]` when `claude_md_setting_sources_enabled=True` | §4.1 requires `setting_sources=["project"]` exactly | **MATCH on syntax** |
| 261 (Slice 1d) | `agents_md_max_bytes: int = 32768` | §4.3 says 32 KiB hard cap | **MATCH on value (32768 = 32 KiB)** |
| 264 (Slice 1d) | "AGENTS.md must stay under 32 KiB (...raised to 64 KiB via .codex/config.toml)" | §4.3: cap raise to 65536 or higher | **MATCH on direction** (note: 65536 is literally 64 KiB, consistent with line 414) |
| 272 (Slice 1e) | "Only the isolated shape (system_addendum + user body) remains" | §4.4 + §4.1 Implication 2: don't override system_prompt | **PARTIAL** — see BLOCKING-3d below |
| 414 (Slice 5e) | `.codex/config.toml` with `project_doc_max_bytes = 65536` | §4.3: that exact override | **MATCH on numerics** |
| 259 (Slice 1d) | Constitution = IMMUTABLE + WAVE_T_CORE_PRINCIPLE + _ANTI_BAND_AID_FIX_RULES verbatim + project conventions | §1.7 warns against burying critical rules in paragraph 12; §4.4 says "small + imperative beats large + exhaustive" | **MATCH on spirit** (200-line guideline not explicit — see NIT-3a) |

**BLOCKING findings for Check 3:**

**BLOCKING-3a (Slice 1d, line 261):** `agents_md_max_bytes: int = 32768` is a config field, not a runtime enforcement. **Wave 1c §4.3** is explicit: *"Content above the cap is silently truncated without a warning in the TUI — a known pain point"* — silent truncation is the foot-gun. The impl plan must require the writer to **assert length < max_bytes** before emitting, and either (a) raise a hard error, (b) auto-split into nested `AGENTS.md`, or (c) log a prominent warning. Shipping just a config field that nobody checks **recreates the exact bug Wave 1c is trying to prevent**. **REMEDIATION:** Slice 1d description should add: *"constitution_writer.py MUST assert rendered AGENTS.md size ≤ agents_md_max_bytes; on overflow, log ERROR and either truncate explicitly (with log line) or raise."*

**BLOCKING-3b (Slice 1d, line 264):** "AGENTS.md must stay under 32 KiB ... raised to 64 KiB via `.codex/config.toml` in Slice 5e." This creates a **circular dependency**: if the writer emits a 50 KiB AGENTS.md (between 32 and 64 KiB), it assumes the `.codex/config.toml` Slice 5e produces will be read at the right scope. **Wave 1c §4.3** does not specify which `[profile.*]` the override must be under; Codex's profile resolution reads from `$CODEX_HOME/config.toml` by default, not the repo-root `.codex/config.toml`. **REMEDIATION:** Slice 5e must specify (a) the config file path Codex CLI actually reads (repo `.codex/config.toml` vs. `$CODEX_HOME/config.toml` — empirically verify with context7 query), (b) the profile key (default vs. named), and (c) a sanity check step in Slice 5e's test `test_codex_config_snippet.py`.

**BLOCKING-3c (Slice 1a, line 234-239):** The impl plan says "add `setting_sources=["project"]`" — this is MATCH on syntax but does NOT state what Wave 1c §4.4 warns as the #1 rule: **do not duplicate CLAUDE.md rules into the per-wave system_prompt**. If the impl plan adds `setting_sources=["project"]` AND the D-merged prompt in Slice 3 also inlines IMMUTABLE + WAVE_T_CORE_PRINCIPLE, then the model receives those rules **twice** (once via CLAUDE.md user message, once via system prompt) — triggering §1.7 anti-pattern #6 "restating the same rule 5 times → over-rigid compliance". **REMEDIATION:** Slice 1d + Slice 3 must pick ONE source of truth per rule. Either (a) LOCKED wording lives in CLAUDE.md only, referenced by system prompt, or (b) LOCKED wording lives in system prompt only, and CLAUDE.md contains only conventions. The impl plan says BOTH inline LOCKED into CLAUDE.md (line 259) AND preserves LOCKED in prompts (line 138). This is a duplication violation per §4.4.

**BLOCKING-3d (Slice 1e, line 272 + Slice 1a):** "Only the isolated shape (system_addendum + user body) remains." Wave 1c §4.1 verbatim: *"The concatenated memory content is delivered to Claude as a user message immediately after the system prompt"*. This means for `setting_sources=["project"]` to work correctly, the system_prompt must NOT be overridden by a `preset` (which would replace the CLI's default behavior). **The impl plan's line 272 describes only the output shape**, not the required `system_prompt.preset=None` or equivalent SDK parameter that keeps default loading active. If Slice 1a passes `system_prompt="..."` as a full override, the `setting_sources` loading may or may not still fire (Wave 1c §4.1 quotes Promptfoo: *"the Claude Agent SDK provider does not look for settings files, CLAUDE.md, or slash commands"* by default — the interaction with a custom `system_prompt` is UNCLEAR and must be context7-verified before committing Slice 1a). **REMEDIATION:** Slice 1a implementer must (a) context7-query the `claude-agent-sdk-python` docs for interaction of `system_prompt` + `setting_sources` + `preset`, and (b) add a test that verifies `CLAUDE.md` is actually being loaded (e.g., by checking `.agent-team/debug/claude_turn_0.json` contains the CLAUDE.md content in turn 0 user message).

**NITs for Check 3:**

**NIT-3a:** Impl plan does not explicitly mention Wave 1c §4.3 / 4.4 **200-line adherence guideline for CLAUDE.md**. The `claude_md_autogenerate` writer should target ≤200 rendered lines. RECOMMEND: add `claude_md_max_lines: int = 200` config alongside `agents_md_max_bytes` at line 261.

**NIT-3b:** No mention of `child_agents_md` feature toggle from Wave 1c §4.2 (*"the `[features]` table in `config.toml` accepts `child_agents_md = true`"*). If the pipeline ever spawns sub-agents per wave, this toggle matters. Not required for Phase G, but future-compatibility note.

---

## Check 4 — output_schema pattern

**Wave 1c §2.4 ground truth:**
- Codex SDK supports `output_schema=` parameter constraining the final assistant message.
- Example JSON Schema pattern (lines 162-171): `{type, properties{summary, actions}, required, additionalProperties}`.
- Source: context7-verified `/openai/codex` — `sdk/python/notebooks/sdk_walkthrough.ipynb`.
- Wave 1c §5 Summary Table: A.5, B, C, T, T.5, E, Fix all emit **"JSON via `output_schema`"**.
- Wave 1c §5 Wave A.5 prompt (line 461): *"Return JSON matching output_schema: {verdict, findings[{category,severity,ref,issue,suggested_fix}]}"*.
- Wave 1c §5 Wave B prompt (line 488): *"Output: final message must be JSON matching output_schema (files_written[], files_skipped[], blockers[])"*.
- Wave 1c §5 Wave T.5 prompt (line 556): *"Return JSON matching output_schema: {gaps: [...]}"*.

**Impl plan references:**

| Impl location | Claim | Wave 1c check | Verdict |
|---|---|---|---|
| 302 (Slice 2b) | Compile-fix prompt includes "flat rules + `<missing_context_gating>` + LOCKED `_ANTI_BAND_AID_FIX_RULES` + `output_schema`" | §5 Fix wave prompt returns `{fixed:[...], still_failing:[...]}` — output_schema explicit | **MATCH** |
| 348 (Slice 4a) | "Dispatches to Codex with `reasoning_effort=medium`" — no mention of `output_schema` | §5 Wave A.5 explicitly uses `output_schema` | **PARTIAL** — see BLOCKING-4a |
| 355 (Slice 4b) | "Dispatches to Codex with `reasoning_effort=high`" — no mention of `output_schema` | §5 Wave T.5 explicitly uses `output_schema` | **PARTIAL** — see BLOCKING-4b |
| 350 (Slice 4a) | "Persists findings to `.agent-team/milestones/{id}/WAVE_A5_REVIEW.json`" | §5 A.5: JSON output via schema | **MATCH on persistence, but schema enforcement unclear** |
| 357 (Slice 4b) | "Persists gaps to `.agent-team/milestones/{id}/WAVE_T5_GAPS.json`" | §5 T.5: JSON output via schema | **MATCH on persistence, same caveat** |

**BLOCKING finding for Check 4:**

**BLOCKING-4 (Slices 4a, 4b, lines 346-359):** The impl plan's `_execute_wave_a5` and `_execute_wave_t5` function descriptions mention "Dispatches to Codex with `reasoning_effort=...`" and "Persists findings/gaps to JSON" but **DO NOT explicitly call out** the Codex SDK `output_schema=` parameter. Wave 1c §2.4 treats this as the primary mechanism for deterministic parsing. Without `output_schema` enforcement, Codex may return prose findings that don't match the expected `WAVE_A5_REVIEW.json` / `WAVE_T5_GAPS.json` shape, and the downstream GATE 8/9 + Wave E/TEST_AUDITOR consumers (Slices 4e, 5c, 5d) will break on first non-conforming output.

**REMEDIATION:** Slice 4a and 4b descriptions must explicitly reference:
> "Passes the Wave A.5 / T.5 JSON Schema (inlined in Part 5a / Part 5f of investigation report) as `output_schema=` parameter to Codex SDK `ResponseCreateParams`."

Additionally the corresponding tests (`test_wave_a5.py`, `test_wave_t5.py`) need assertions that the dispatched Codex call includes `output_schema`.

*(Note: The impl plan at line 302 Slice 2b DOES mention output_schema for compile-fix. The omission in Slice 4 is asymmetric and likely a drafting miss, not a design decision.)*

---

## Check 5 — Prompt style claims

**Wave 1c §1.1-§1.7 (Claude) + §2.1-§2.8 (Codex) ground truth:**
- §1: Claude responds to XML (`<rules>`, `<thinking>`, `<context>`, `<findings>`, 8-block order).
- §1.2: Claude follows literal instructions; restating same rule 5 times causes over-rigid compliance.
- §1.3: Claude over-engineers — explicit "minimal, no new abstractions" is load-bearing.
- §1.7 anti-pattern #6: Claude registers literal repetition as stronger signal but restating 5 times → over-rigid compliance.
- §2.1: Codex wants short rules blocks + JSON schemas, NOT XML.
- §2.1: GPT-5.4 gets MORE verbose when prompts get longer/more repetitive.
- §2.2: Codex over-constrained → "weaker instruction following" fallback → under-completion. Add persistence, don't add more constraints.
- §2.6: `<missing_context_gating>` is Codex-native analog of Claude's "give the model an out".
- §2.8 anti-pattern #5: Absolute paths in `apply_patch` silently fail.
- §2.8 anti-pattern #6: Codex generic "explore and think deeply" without verification → early stop.
- §2.8 anti-pattern #8: "Do not `git commit`" — explicitly banned in Codex's own system prompt.

**Impl plan references:**

| Impl location | Claim | Wave 1c check | Verdict |
|---|---|---|---|
| 138 | "LOCKED wording transfers VERBATIM ... Don't paraphrase." | §1.2 literal instructions; §1.7 anti-pattern #6 not violated if only ONE restatement per location | **MATCH** (as long as LOCKED wording exists once in CLAUDE.md only, or once in system prompt only — see BLOCKING-3c above) |
| 302 | Compile-fix "flat rules + `<missing_context_gating>`" | §2.1 Codex flat rules + §2.6 missing_context_gating | **MATCH** |
| 322 | "IMMUTABLE block at `agents.py:8803-8808` transfers VERBATIM" | §1.2 Claude follows literal instructions | **MATCH** |
| 325 | "REMOVE Codex autonomy directives" (from Wave D merge, which is Claude-targeted) | §1-§2 split: Codex directives belong to Codex prompts, not Claude | **MATCH** |
| 326 | "REMOVE D.5's 'don't change functionality' restriction (merged D does BOTH)" | Not directly Wave 1c scope, but aligns with R1/R3 conclusion | **MATCH on prompt-style impact** |

**NIT findings for Check 5:**

**NIT-5a:** Impl plan does not explicitly call out Wave 1c §2.8 anti-pattern #5 (**relative paths in `apply_patch`**). For Wave B / C / Fix / Compile-Fix Codex prompts (Slices 2a, 2b, and Part 5.8/5.9), the impl plan should require a `relative_paths_required` prompt block. Part 5.8 in the investigation report likely already contains this, but the impl plan doesn't verify it. RECOMMEND: Slice 2a/2b wiring-verifier checks add: *"grep the dispatched Codex prompt for the string 'relative paths' or 'never absolute'."*

**NIT-5b:** Impl plan does not reference Wave 1c §2.8 anti-pattern #8 (**"Do not `git commit`"** ban). Codex's own system prompt already bans this, but the Slice 2 and Slice 4 prompts should not accidentally ask for commits. NIT because the harm is low.

**NIT-5c:** Impl plan line 325 says "REMOVE Codex autonomy directives" from merged-D (Claude). Wave 1c §2.2 says Codex needs autonomy; §1 does not have a direct equivalent. If "Codex autonomy directives" means `<tool_persistence_rules>` or `missing_context_gating`, removing them from a Claude prompt is correct. If it means "think freely", removing them is also fine because Claude's §1.6 role-based system-prompt handles steering differently. **Low-risk MATCH**, but implementer should double-check exact wording.

**NIT-5d:** No mention of Wave 1c §1.5 **long-context ordering** (documents FIRST, instructions LAST) for Wave A / D / Audit Claude prompts. The impl plan Slice 5a/5b adds `<framework_idioms>` to Wave A/T but doesn't specify placement. RECOMMEND: Slice 5a/5b wiring-verifier adds: *"verify `<framework_idioms>` block appears BEFORE the task-description block in the rendered prompt."*

**NIT-5e:** No mention of Wave 1c §1.7 anti-pattern #5 **prefill strategy**. Wave 1c §5 Wave A and Wave D both recommend "Prefill with `<thinking>`" — the impl plan doesn't surface whether prefill is wired up via the Claude SDK `messages` param. Slice 3 touches `build_wave_d_prompt` but doesn't specify prefill. RECOMMEND: Slice 3a/5a-b wiring-verifier explicitly checks whether prefill is supported in the current pipeline.

---

## Check 6 — Context7 usage

**Wave 1c basis:** 15 context7 queries run + 5 WebSearch queries. Every "context7-verified" claim is the gold standard. Training-cutoff mitigation via context7 is Wave 1c's primary research discipline.

**Impl plan references:**

| Impl location | Claim | Wave 1c check | Verdict |
|---|---|---|---|
| 135 | "**MCPs mandatory:** context7 + sequential-thinking on every agent EXCEPT test-engineer (sequential-thinking only)." | Wave 1c implicitly endorses context7 for model-prompting; test-engineer exclusion is reasonable (writes tests from specs, not from SDK docs) | **MATCH** with caveat (see NIT-6a) |
| 565 | "**Context7 on every framework/SDK reference.** Claude Agent SDK, Codex CLI, NestJS, Prisma, Next.js." | §A-B appendices verify context7 use against `/anthropics/courses`, `/openai/codex`, `/anthropics/claude-agent-sdk-python`, `/luohaothu/everything-codex`, `/websites/code_claude` | **MATCH** |
| 62-69 (team table) | Every agent gets context7 except test-engineer | Wave 1c's primary workflow was context7-per-query | **MATCH** |

**NIT findings for Check 6:**

**NIT-6a (line 135 + line 68):** `phase-g-test-engineer` is excluded from context7 MCP. This is defensible (test-engineer writes pytest from specs, not from SDK docs), but **if any of the 18 test files need SDK-mock shapes** (e.g., asserting `output_schema=` is passed to Codex SDK correctly per BLOCKING-4), the test-engineer will need context7 to confirm the exact Codex SDK parameter name. RECOMMEND: add context7 to test-engineer for the subset of tests that assert SDK call-shapes (Slice 2a, 2b, 4a, 4b tests). Alternatively, tests can use `mock.call_args_list` checks that don't depend on SDK internal shape.

**NIT-6b:** No mention of Wave 1c's **context7 use case for future pipeline wave adjustments**. Wave 1c §2.7 warns *"legacy community docs mentioned `codex.md` / `.codex/instructions`; current Codex CLI uses `AGENTS.md`"* — this kind of training-cutoff mitigation is exactly what context7 guards against. The impl plan should instruct Slice 1d implementer to context7-verify the **current** AGENTS.md filename and 32 KiB cap value at implementation time, since both could change. RECOMMEND: Slice 1d description add one-line: *"Before implementing: context7-query `/openai/codex` for current `AGENTS.md` filename + `project_doc_max_bytes` default to verify 32 KiB cap still holds."*

**NIT-6c:** Impl plan Wave 1 ("line map verification") uses `superpowers:code-reviewer` agent type with context7. This is correct but redundant — a line-map check doesn't need context7. NIT because no harm done.

---

## Comments Index [BLOCKING/NIT/INFO] — \<line\> — \<comment\>

**BLOCKING** (must resolve before Wave 2 begins):

1. [BLOCKING] — line 261 (Slice 1d) — `agents_md_max_bytes: int = 32768` is a config field, not a runtime enforcement. Wave 1c §4.3 silent-truncation warning mandates writer-level assertion. **REMEDIATION:** require `constitution_writer.py` to assert size ≤ cap and log ERROR or raise on overflow.
2. [BLOCKING] — line 234-239 (Slice 1a) — `setting_sources=["project"]` syntax matches Wave 1c §4.1, but impl plan does not require preservation of existing system_prompt (no `preset` override). Ambiguous SDK interaction with custom system_prompt must be context7-verified before committing. **REMEDIATION:** Slice 1a context7-queries `claude-agent-sdk-python` for `system_prompt` + `setting_sources` interaction + adds integration test verifying CLAUDE.md is actually loaded in turn 0.
3. [BLOCKING] — line 259 + line 264 (Slice 1d) vs. line 138 — LOCKED wording (IMMUTABLE, WAVE_T_CORE_PRINCIPLE, _ANTI_BAND_AID_FIX_RULES) is referenced as both "inlined in CLAUDE.md" AND "verbatim in system prompts". Wave 1c §4.4 forbids duplication (triggers §1.7 anti-pattern #6 over-rigid compliance). **REMEDIATION:** pick ONE source of truth per LOCKED block — CLAUDE.md OR system prompt, not both.
4. [BLOCKING] — lines 346-359 (Slices 4a, 4b) — `_execute_wave_a5` / `_execute_wave_t5` descriptions omit Codex SDK `output_schema=` parameter. Wave 1c §2.4 + §5 Summary Table require this for deterministic parsing. **REMEDIATION:** Slice 4a/4b add "pass output_schema JSON Schema from Part 5a/5f as Codex SDK parameter"; tests assert `output_schema` in dispatch call_args.
5. [BLOCKING] — line 33 (Wave T routing) — Impl plan routes Wave T to Claude; Wave 1c §5 + Summary Table route Wave T to GPT-5.4 high. **RESOLUTION:** audit Part 7 §7.1 + Part 5.5 to confirm authoritative decision; update either impl plan or this review.
6. [BLOCKING] — line 33 (Wave E routing) — Same as above, Wave E routes to Claude in impl plan vs. GPT-5.4 high in Wave 1c §5. **RESOLUTION:** same as BLOCKING-5.
7. [BLOCKING] — line 413-414 (Slice 5e) — `.codex/config.toml` placement ambiguity: Codex reads from `$CODEX_HOME/config.toml` by default, not repo-root `.codex/config.toml`. Override scope must be verified. **REMEDIATION:** Slice 5e context7-queries `/openai/codex` `docs/config.md` for config discovery order + confirms writer emits to the path Codex actually reads.

**NIT** (quality improvements, non-blocking):

8. [NIT] — line 261 — add `claude_md_max_lines: int = 200` alongside `agents_md_max_bytes` per Wave 1c §4.3 adherence guideline.
9. [NIT] — Slice 2a/2b (lines 284-302) — no explicit **relative-paths-required** block per Wave 1c §2.8 anti-pattern #5. Part 5.8/5.9 prompts likely contain this; verifier should grep for it.
10. [NIT] — line 325 — "REMOVE Codex autonomy directives" ambiguous wording; document exact strings to remove to avoid accidentally removing `<thinking>`-style Claude-native patterns.
11. [NIT] — Slice 5a/5b (lines 398-404) — no placement requirement for `<framework_idioms>` block. Wave 1c §1.5 "documents FIRST, instructions LAST" applies to Claude prompts. Verifier should check placement.
12. [NIT] — No mention of **prefill strategy** for Wave A/D Claude prompts per Wave 1c §1.7 anti-pattern #5 + §5 recommendations. Open Question #2 in Wave 1c explicitly flags this.
13. [NIT] — line 135 / test-engineer agent — if test files assert Codex SDK call-shapes, test-engineer needs context7; currently excluded.
14. [NIT] — Slice 1d should require context7-verification of current AGENTS.md behavior (32 KiB cap may change post-Wave-1c).

**INFO** (informational, no action required):

15. [INFO] — line 33 Wave C labeled "Python" vs. Wave 1c §5 Wave C = `GPT-5.4 high`. If Wave C is now a Python-only stub-fill step (no LLM), MATCH; otherwise drift. Confirm Part 7 §7.1.
16. [INFO] — Wave 1c Open Question #4 "`reasoning_effort` per wave" is now resolved in impl plan (per-wave flags at lines 290, 372, 379).
17. [INFO] — Wave 1c Open Question #3 "`output_schema` adoption" is partially addressed by impl plan Slice 2b line 302, but fully requires BLOCKING-4 remediation.
18. [INFO] — Wave 1c Open Question #6 "`setting_sources` on `ClaudeSDKClient`" is addressed by impl plan Slice 1a, pending BLOCKING-2/3c resolution.
19. [INFO] — Wave 1c Open Question #7 "Combined AGENTS.md footprint vs. 32 KiB cap" is addressed by impl plan lines 261 + 264 + 414, pending BLOCKING-3a/3b resolution.
20. [INFO] — Wave 1c Open Question #8 "Memory-file parity" is implicitly addressed by Slice 1d's single `constitution_templates.py` generating both files from one source.

---

## Scope limit statement

This review is scoped to Wave 1c (model prompting research) only. Cross-checks against:
- Wave 1a (pipeline audit) — **OUT OF SCOPE**
- Wave 1b (prompt inventory) — **OUT OF SCOPE**
- Wave 5a (accuracy audit) + 5b (completeness audit) — **OUT OF SCOPE**
- Part 7 authoritative line-number verification — **OUT OF SCOPE**

Any Wave-T and Wave-E routing discrepancy (BLOCKING-5, BLOCKING-6) must be resolved by the team lead with Part 7 as the authoritative source, because Part 7 represents the post-investigation binding contract, while Wave 1c is one of nine inputs into that contract. If Part 7 picked Claude for Wave T/E, the impl plan is correct and Wave 1c is superseded.

---

*End of Wave 7c review deliverable.*
