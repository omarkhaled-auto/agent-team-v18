# Phase G Implementation Line-Map Verification

**Verified at HEAD:** `466c3b950ded1f57e46738f7db3bb97e6565ebc0`
**Verified on branch:** `phase-g-pipeline-restructure`
**Date:** 2026-04-17

---

## Status Summary

- **Targets verified:** 28 / 28 load-bearing file:line citations match current code.
- **Targets shifted:** 0 hard shifts. 2 cited ranges are "approximate" (pre-existing wording issues called out in Wave 1a — NOT drift since investigation).
- **LOCKED wording:** **VERBATIM** for all 3 blocks (IMMUTABLE, WAVE_T_CORE_PRINCIPLE, `_ANTI_BAND_AID_FIX_RULES`).
- **Wave 1a "9 Surprises":** 8/9 still present at HEAD; #6 (`MILESTONE_HANDOFF.md` writer/reader) is a **Wave 1a misread** — the writer HAS existed since v15 (`tracking_documents.py`). Slice 1c ARCHITECTURE.md work is still valid (different artifact, different lifecycle).
- **Post-Phase-F additions affecting insertion points:** None material. Slice 4 hook points `~3250`/`~3260` fall INSIDE the Wave T execute block — implementer must pick structural boundaries (pre-Wave-B / post-Wave-T), not literal line numbers.

**Recommendation:** implementer slices MAY use Part 7 §7.1 line numbers directly. One wording correction and one hook-point clarification are documented below for impl agents; none require plan revision.

---

## Slice 1 Line Targets

### Slice 1a — `_build_options` + `opts_kwargs`

| Target | Expected | Current HEAD | Verdict |
|--------|----------|--------------|---------|
| `cli.py:339-450` (`_build_options`) | Function signature at 339, `return ClaudeAgentOptions(**opts_kwargs)` at 450 | `def _build_options(` at **cli.py:339**; `return` at **cli.py:450** | **CONFIRMED** |
| `cli.py:427-444` (`opts_kwargs` dict) | Dict literal construction | `opts_kwargs: dict[str, Any] = {` at **cli.py:427**; dict body 427-434; conditional appends 436-449 | **CONFIRMED** (dict body is 427-434; appended keys 436-449; impl add-point "near line 430" inside the initial dict or via conditional append after 434, per Part 7 code pattern) |

### Slice 1b — Transport selector

| Target | Expected | Current HEAD | Verdict |
|--------|----------|--------------|---------|
| `cli.py:3182` | Hard-coded Codex transport import | `import agent_team_v15.codex_transport as _codex_mod` at **cli.py:3182** | **CONFIRMED** (exact line) |
| `config.py:811` (flag already exists) | `codex_transport_mode` default `"exec"` | `codex_transport_mode: str = "exec"` at **config.py:811** | **CONFIRMED** |
| Consumption check | None | `grep codex_transport_mode src/.../cli.py` → **0 matches**. Flag declared but never consumed — Surprise #1 still present. | **CONFIRMED unconsumed** |

Downstream collision site `cli.py:3184-3187` (WaveProviderMap construction) also verified — lines 3184-3187 contain the `WaveProviderMap(B=..., D=...)` block exactly as cited.

### Slice 1c — ARCHITECTURE.md writer hook points

| Target | Expected | Current HEAD | Verdict |
|--------|----------|--------------|---------|
| `wave_executor.py:~3150` (M1 dispatch) | Pre-M1 milestone dispatch point | `return await _execute_milestone_waves_with_stack_contract(...)` dispatch call at **wave_executor.py:3141-3156** | **CONFIRMED** (nearest structural boundary is before the dispatch call at 3141; "~3150" falls inside the keyword-args region 3141-3156 — impl agent should hook BEFORE line 3141) |
| `wave_executor.py:~3542-3548` (`persist_wave_findings_for_audit`) | Hook point alongside persist | `persist_wave_findings_for_audit(cwd, result.milestone_id, result.waves, wave_t_expected=..., failing_wave=result.error_wave)` at **wave_executor.py:3542-3548** | **CONFIRMED** (exact lines) |

### Slice 1d — Config flags section (for new flag additions)

| Target | Expected | Current HEAD | Verdict |
|--------|----------|--------------|---------|
| `config.py:791` (V18Config flags section near top) | Field block in V18Config | `wave_d5_enabled: bool = True` at **config.py:791**; V18Config section continues through 800-804 (wave_t_enabled etc.) | **CONFIRMED** as "near line 791" insertion zone. New flags (`claude_md_autogenerate`, `agents_md_autogenerate`, `agents_md_max_bytes`) can be inserted alongside. |

### Slice 1e — Recovery kill

| Target | Expected | Current HEAD | Verdict |
|--------|----------|--------------|---------|
| `cli.py:9526-9531` (legacy `[SYSTEM:]` branch) | Else branch emitting pseudo-tag | Comment block at **cli.py:9525-9528**; `legacy_situation = ...` with `[SYSTEM: ...]` pseudo-tag at **cli.py:9529-9533**; branch continues to **cli.py:9539** (`return "", legacy_prompt`) | **CONFIRMED-approx** — full legacy branch is **cli.py:9525-9539**. Plan cites 9526-9531 (covers comment header + start of legacy_situation). This is the SAME Wave 1a Check 2 item 3 "MATCH-approx" finding — not new drift. Deletion target is lines 9525-9539 (full else branch including the leading comment). |
| `config.py:863` (`recovery_prompt_isolation` field) | Field default True | `recovery_prompt_isolation: bool = True` at **config.py:863** | **CONFIRMED** |
| `config.py:2566` (coerce) | Corresponding coerce call | `recovery_prompt_isolation=_coerce_bool(...)` at **config.py:2566** | **CONFIRMED** |

Helper `_build_recovery_prompt_parts` confirmed at **cli.py:9448**; post-deletion surviving shape (`system_addendum` + `user_prompt`) is the branch at **cli.py:9504-9523**.

### Slice 1f — SCORER_AGENT_PROMPT

| Target | Expected | Current HEAD | Verdict |
|--------|----------|--------------|---------|
| `audit_prompts.py:1292` (`SCORER_AGENT_PROMPT`) | Prompt constant assignment | `SCORER_AGENT_PROMPT = """You are the SCORER AGENT...` at **audit_prompts.py:1292** | **CONFIRMED** (exact line) |

---

## Slice 2 Line Targets

### Slice 2a — Audit-fix classifier wire-in

| Target | Expected | Current HEAD | Verdict |
|--------|----------|--------------|---------|
| `cli.py:6271` (`_run_audit_fix_unified`) | Function entry | `async def _run_audit_fix_unified(` at **cli.py:6271** | **CONFIRMED** |
| `cli.py:6441` (ClaudeSDKClient patch-mode call) | SDK client async-with call | `async with ClaudeSDKClient(options=options) as client:` at **cli.py:6441** | **CONFIRMED** |
| `provider_router.py:481-504` (`classify_fix_provider`) | Function body | `def classify_fix_provider(affected_files: list[str], issue_type: str) -> str:` at **provider_router.py:481**; `return "claude"` at **provider_router.py:504** | **CONFIRMED** |
| Call-site check | Exported but never called | `grep classify_fix_provider src/` → **1 match** (the definition only). Surprise #3 still present. | **CONFIRMED unconsumed** |

### Slice 2b — Compile-fix Codex routing

| Target | Expected | Current HEAD | Verdict |
|--------|----------|--------------|---------|
| `wave_executor.py:2391` (`_build_compile_fix_prompt`) | Function entry | `def _build_compile_fix_prompt(` at **wave_executor.py:2391** | **CONFIRMED** |
| `wave_executor.py:2888` (`_run_wave_b_dto_contract_guard`) | Function entry | `async def _run_wave_b_dto_contract_guard(` at **wave_executor.py:2888** | **CONFIRMED** |

---

## Slice 3 Line Targets

| Target | Expected | Current HEAD | Verdict |
|--------|----------|--------------|---------|
| `agents.py:8696-8858` (`build_wave_d_prompt`) | Full function body | `def build_wave_d_prompt(` at **agents.py:8696**; body ends with `return result` at **agents.py:8858** | **CONFIRMED** (next function `build_wave_d5_prompt` at **agents.py:8860**) |
| `agents.py:9018-9131` (`build_wave_prompt` dispatcher) | Dispatcher body | `def build_wave_prompt(` at **agents.py:9018**; dispatcher body continues through Wave C handler at 9130; `raise ValueError(...)` fall-through at **agents.py:9137** | **CONFIRMED-approx** — function body actually extends to **agents.py:9137** (6 lines longer than "9131" cited). Next function `build_orchestrator_prompt` starts at **agents.py:9139**. No semantic drift; full dispatcher is 9018-9137. |
| `provider_router.py:27-42` (`WaveProviderMap`) | Dataclass definition | `@dataclass` at **provider_router.py:27**, class body 28-35, `provider_for` method 37-42 | **CONFIRMED** (exact lines) |
| `wave_executor.py:307-311` (`WAVE_SEQUENCES`) | Dict literal (3 templates) | `WAVE_SEQUENCES = {` at **wave_executor.py:307**; 3 template entries at 308-310; close `}` at **wave_executor.py:311** | **CONFIRMED** (exact lines) |
| `wave_executor.py:395-403` (`_wave_sequence` mutator) | Function body | `def _wave_sequence(template, config)` at **wave_executor.py:395**; body 396-402; `return waves` at **wave_executor.py:403** | **CONFIRMED** (exact lines) |
| `wave_executor.py:~3295` (compile-gate) | Compile-gate start | `if wave_result.success and wave_letter in {"A", "B", "D", "D5"}:` at **wave_executor.py:3295** | **CONFIRMED** (exact line) |
| `wave_executor.py:~3357-3375` (D5 rollback) | D5-only rollback branch | `if wave_letter == "D5" and rollback_snapshot is not None:` at **wave_executor.py:3357**; `rolled_back = True` + error_message at **wave_executor.py:3371-3375** | **CONFIRMED** (exact lines) |

**Notes for impl agent:**
- Plan's Slice 3d correctly distinguishes compile-gate (~3295) from D5 rollback (~3357-3375) as two sites. This is the same distinction Wave 1a flagged in NIT-1 (earlier drafts conflated into "~3295-3305").
- `cli.py:3184-3187` WaveProviderMap construction (shared collision point with Slice 4): exact lines **cli.py:3184-3187** confirmed — `provider_map = WaveProviderMap(B=..., D=...)` + `_provider_routing = {...}` through line 3187.

---

## Slice 4 Line Targets

| Target | Expected | Current HEAD | Verdict |
|--------|----------|--------------|---------|
| `wave_executor.py:~3250` (pre-Wave-B insertion for A.5) | Insertion point before Wave B dispatch | At **wave_executor.py:3250**, content is `build_wave_prompt=build_wave_prompt,` — a kwarg INSIDE the `_execute_wave_t(...)` call (lines 3248-3260). The A.5 dispatch must be inserted at a STRUCTURAL boundary, NOT at this literal line. | **CLARIFICATION REQUIRED** — see note below |
| `wave_executor.py:~3260` (post-Wave-T insertion for T.5) | Insertion point after Wave T dispatch | At **wave_executor.py:3260**, content is `)` closing the `_execute_wave_t(...)` call. Post-Wave-T insertion point is AFTER line 3260 (before `else:` at 3261 which handles generic waves). | **CLARIFICATION REQUIRED** — see note below |
| `agents.py:1668` (`TEAM_ORCHESTRATOR_SYSTEM_PROMPT`) | Constant assignment | `TEAM_ORCHESTRATOR_SYSTEM_PROMPT = r"""` at **agents.py:1668** | **CONFIRMED** |
| `agents.py:1864` (`_DEPARTMENT_MODEL_ENTERPRISE_SECTION`) | Constant assignment | `_DEPARTMENT_MODEL_ENTERPRISE_SECTION = r"""===...` at **agents.py:1864** | **CONFIRMED** |

**Slice 4a/4b hook-point clarification for impl agent:**

The wave-execution loop in `_execute_milestone_waves_with_stack_contract` is structured as a per-wave-letter branch (wave_letter == "B" → `_execute_wave_b(...)`, "C" → `_execute_wave_c(...)`, "T" → `_execute_wave_t(...)`, else → generic `_execute_wave_sdk(...)`). The "~3250" and "~3260" citations in Part 7 fall INSIDE the Wave T execute block (lines 3248-3260).

The correct insertion points are:
- **A.5 dispatch:** NEW `elif wave_letter == "A5":` branch inserted at the per-wave dispatcher (the elif chain starting near **wave_executor.py:3200s-3261**; exact location depends on where the Slice 4 author chooses to add the A5 literal to `WAVE_SEQUENCES` — see Slice 3b). Orchestrator ordering (A → A5 → Scaffold → B) is driven by `_wave_sequence()` returning the A5 literal; the dispatch code just needs a new `elif` branch for `"A5"`.
- **T.5 dispatch:** Same pattern — NEW `elif wave_letter == "T5":` branch in the same elif chain, inserted after the Wave T branch (after line **3260**) so the sequence goes T → T5 → E.

No line-number drift here — the "~" in Part 7 explicitly acknowledges these are approximate. Impl agent should use structural boundary (elif chain in the dispatcher) rather than literal line.

---

## Slice 5 Line Targets

| Target | Expected | Current HEAD | Verdict |
|--------|----------|--------------|---------|
| `agents.py:7750` (`build_wave_a_prompt`) | Function entry | `def build_wave_a_prompt(` at **agents.py:7750** | **CONFIRMED** |
| `agents.py:8391` (`build_wave_t_prompt`) | Function entry | `def build_wave_t_prompt(` at **agents.py:8391** | **CONFIRMED** |
| `agents.py:8147` (`build_wave_e_prompt`) | Function entry | `def build_wave_e_prompt(` at **agents.py:8147** | **CONFIRMED** |
| `audit_prompts.py:651` (`TEST_AUDITOR_PROMPT`) | Prompt constant | `TEST_AUDITOR_PROMPT = """You are a TEST AUDITOR...` at **audit_prompts.py:651** | **CONFIRMED** |
| `cli.py:3976` (`_n17_prefetch_cache`) | Cache dict declaration | `_n17_prefetch_cache: dict[str, str] = {}` at **cli.py:3976** | **CONFIRMED** |

**Surprise #9 verification:** cache-key gate is `if w in ("B", "D")` at **cli.py:3980**. Slice 5a/5b will need to broaden this to A+T. Plan line 535 + 541 are aware (cite cli.py:3976 for Wave A/T keyword sets).

---

## LOCKED Wording Verification

### 1. IMMUTABLE packages/api-client block — `agents.py:8803-8808`

**Status:** VERBATIM. Impl plan copy-paste will preserve exact bytes.

Exact contents read from HEAD `466c3b9`:

```
8803    "For every backend interaction in this wave, you MUST import from `packages/api-client/` and call the generated functions. Do NOT re-implement HTTP calls with `fetch`/`axios`. Do NOT edit, refactor, or add files under `packages/api-client/*` - that directory is the frozen Wave C deliverable. If you believe the client is broken (missing export, genuinely unusable type), report the gap in your final summary with the exact symbol and the line that would have called it, then pick the nearest usable endpoint. Do NOT build a UI that only renders an error. Do NOT stub it out with a helper that throws. Do NOT skip the endpoint.",
8804    "",
8805    "[INTERPRETATION]",
8806    "Using the generated client is mandatory, and completing the feature is also mandatory.",
8807    "If one export is awkward or partially broken, use the nearest usable generated export and still ship the page.",
8808    "Do not replace the feature with a client-gap notice, dead-end error shell, or placeholder route.",
```

**Note:** Line 8803 is the IMMUTABLE rule itself (one long string item in a list); lines 8805-8808 are the `[INTERPRETATION]` supporting block. Wave 1a NIT-4 flagged this same "IMMUTABLE proper is only line 8803; 8804-8808 is adjacent [INTERPRETATION]" nuance. Plan citation "8803-8808" treats this as a bundle — acceptable because impl agent will copy the entire 8803-8808 block VERBATIM when composing the merged Wave D prompt (Slice 3a). No drift vs investigation.

### 2. WAVE_T_CORE_PRINCIPLE — `agents.py:8374-8388`

**Status:** VERBATIM. Exact contents read from HEAD `466c3b9`:

```python
WAVE_T_CORE_PRINCIPLE = (
    "You are writing tests to prove the code is correct. "
    "If a test fails, THE CODE IS WRONG — not the test.\n"
    "\n"
    "NEVER weaken an assertion to make a test pass.\n"
    "NEVER mock away real behavior to avoid a failure.\n"
    "NEVER skip a test because the code doesn't support it yet.\n"
    "NEVER change an expected value to match buggy output.\n"
    "NEVER write a test that asserts the current behavior if the current "
    "behavior violates the spec.\n"
    "\n"
    "If the code doesn't do what the PRD says, the test should FAIL and "
    "you should FIX THE CODE.\n"
    "The test is the specification. The code must conform to it."
)
```

Opening `(` at **line 8374**, closing `)` at **line 8388**. Exact match.

### 3. `_ANTI_BAND_AID_FIX_RULES` — `cli.py:6168-6193`

**Status:** VERBATIM. Exact contents read from HEAD `466c3b9`:

```python
_ANTI_BAND_AID_FIX_RULES = """[FIX MODE - ROOT CAUSE ONLY]
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
STRUCTURAL note in your summary instead of half-fixing it."""
```

Opening at **line 6168**, closing `"""` at **line 6193**. Exact match.

**All three LOCKED blocks verified VERBATIM. Impl agents must copy-paste these ranges (not paraphrase) per Phase G rule #3 + Part 6.3.**

---

## "9 Surprises" from Wave 1a — Presence Check

| # | Surprise (Wave 1a) | HEAD verification | Status |
|---|--------------------|-------------------|--------|
| 1 | `codex_transport_mode` declared but never consumed (`cli.py:3182` hard-coded) | `config.py:811` declares `codex_transport_mode: str = "exec"`; `grep codex_transport_mode src/.../cli.py` → 0 matches; `cli.py:3182` has `import agent_team_v15.codex_transport as _codex_mod` unconditionally. | **STILL PRESENT** (Slice 1b target) |
| 2 | `setting_sources=["project"]` never set; builder ignores generated-project `CLAUDE.md` | `grep -r setting_sources src/agent_team_v15/` → 0 matches. | **STILL PRESENT** (Slice 1a target) |
| 3 | `classify_fix_provider` (provider_router.py:481) exported, never called | `grep classify_fix_provider src/` → 1 match (definition only, provider_router.py:481). | **STILL PRESENT** (Slice 2a target) |
| 4 | Wave T hard-bypasses `provider_routing` at `wave_executor.py:3243-3260` | `wave_executor.py:3243` — `elif wave_letter == "T":` branch calls `_execute_wave_t(...)` without passing `provider_routing`. Comment at 3244-3247 explicitly notes "V18.2: Wave T ALWAYS routes to Claude — bypass provider_routing entirely". | **STILL PRESENT** (Slice 3b respects this; Slice 4b T.5 adds NEW dispatch, doesn't modify T bypass) |
| 5 | D5 forces Claude regardless of caller's map (`provider_router.py:39-41`) | `provider_router.py:37-42` — `provider_for` returns `"claude"` when `wave_key in {"D5", "UI"}`. Short-circuit before `getattr(self, wave_key, "claude")`. | **STILL PRESENT** (Slice 3c mirrors this pattern for merged-D flip) |
| 6 | No `MILESTONE_HANDOFF.md` writer/reader found | **CORRECTION:** MILESTONE_HANDOFF writer HAS existed since v15 — `tracking_documents.py:766` defines `generate_milestone_handoff_section`; `tracking_documents.py:868` / `:972` / `:1050` / `:1097` / `:1165` define parsers. Call sites at `cli.py:3727`, `:4369`, `:4873-4952`, `:5041`, `:14144`. Prompts reference it at `cli.py:8078`, `agents.py:2923`, `:3027`, `:6470-6495`, `:6699-6702`. Config flag `milestone_handoff: bool = True` at `config.py:459`. | **WAVE 1a MISREAD** — writer/reader PRESENT at HEAD. Slice 1c ARCHITECTURE.md is still justified (different artifact: cumulative cross-milestone vs per-milestone handoff). Impl agent should NOT conflate the two. |
| 7 | No project-level cumulative architecture document exists | `ls C:/Projects/agent-team-v18-codex/{CLAUDE,AGENTS,ARCHITECTURE}.md` → **no such file or directory** for all three. No `ARCHITECTURE.md` builder in source. | **STILL PRESENT** (Slice 1c target) |
| 8 | Fix prompt inlines entire `task_text` at `cli.py:6428` | `cli.py:6425-6428`: `"[ORIGINAL USER REQUEST]\n"` then `f"{task_text}"`. Impl plan Slice 2a inherits this (informational-only gap per Wave 1a). | **STILL PRESENT** (informational — noted for Codex context-window sizing) |
| 9 | `_n17_prefetch_cache` (cli.py:3976) is per-milestone, per-wave (B+D only) | `cli.py:3976`: `_n17_prefetch_cache: dict[str, str] = {}`. `cli.py:3980`: `if w in ("B", "D") and w not in _n17_prefetch_cache:`. | **STILL PRESENT** (Slice 5a/5b needs to broaden to A+T) |

**Summary of Surprises:** 8/9 present unchanged since Wave 1a. #6 was a Wave 1a misread — MILESTONE_HANDOFF infrastructure exists; Slice 1c is still valid because ARCHITECTURE.md is a different artifact (cumulative cross-milestone doc, not the per-milestone handoff).

---

## Post-Phase-F Additions Affecting Insertion Points

**Branch base:** `466c3b9` (Phase F merge, 2026-04-15 closeout). Investigation HEAD was the same SHA, so by definition there are NO commits between investigation and line-map verification.

Spot-check confirms all line-number citations in Part 7 reflect the code at `466c3b9`:
- `_build_options` at cli.py:339 — unchanged.
- `opts_kwargs` dict at cli.py:427-434 — unchanged.
- `codex_transport` import at cli.py:3182 — unchanged.
- `_run_audit_fix_unified` at cli.py:6271 — unchanged.
- All `build_wave_*_prompt` functions at cited lines — unchanged.
- `WAVE_SEQUENCES` at wave_executor.py:307-311 — unchanged.
- `_wave_sequence` mutator at wave_executor.py:395-403 — unchanged.
- Compile-gate at wave_executor.py:3295 + D5 rollback at wave_executor.py:3357-3375 — unchanged.
- All LOCKED blocks at cited line ranges — VERBATIM.

**No post-Phase-F additions affect Phase G insertion points.**

---

## Recommendations for Implementer Slices

**Primary verdict: GREEN — impl agents may use Part 7 line numbers directly.** No blocking discrepancies.

Two minor clarifications (both pre-existing from Wave 1a, NOT drift):

1. **Slice 1e recovery kill (cli.py:9526-9531 → actually 9525-9539).** The full legacy `[SYSTEM:]` else branch begins at line 9525 (leading comment `# Legacy shape — preserved byte-identically...`) and ends at line 9539 (`return "", legacy_prompt`). Impl agent deletes the ENTIRE block 9525-9539 — the plan's 9526-9531 citation covers the comment header + first half of the `legacy_situation` assignment. Deletion is structural (whole else branch), not line-sliced. No behavior change vs plan; this is a clearer citation.

2. **Slice 4a/4b hook points (~3250 / ~3260).** Part 7 uses `~` to indicate approximate lines because the insertion is structural (new `elif wave_letter == "A5":` / `"T5":` branches in the dispatcher elif chain), not line-literal. At HEAD, lines 3250 and 3260 fall INSIDE the existing Wave T execute block (3248-3260). The correct insertion pattern:
   - A.5: new elif branch co-located with other wave-letter dispatches (around lines 3220s-3261, before the `else:` fallback at 3261). Sequence ordering is driven by `_wave_sequence()` output (Slice 3b).
   - T.5: new elif branch, same dispatcher, logically inserted after the Wave T branch (after line 3260).
   Plan's "~3250"/"~3260" are acknowledgments of this — not literal targets. Impl agent uses structural boundary, not literal line.

3. **Slice 3 dispatcher end-line (agents.py:9018-9131 → actually 9018-9137).** `build_wave_prompt` body extends 6 lines past the cited "9131" (Wave C handler at 9130-9136 + `raise ValueError(...)` at 9137). Next function `build_orchestrator_prompt` starts at 9139. No semantic drift; slight end-line extension. Impl agent's merged-D dispatcher patch will insert an early branch for `wave_letter == "D"` + `config.wave_d_merged_enabled` flag — location within body unchanged.

**LOCKED wording status: confirmed VERBATIM for all 3 blocks.** Copy-paste by impl agents (Slice 3a merged-D, Slice 2b compile-fix Codex, Slice 2a audit-fix Codex) will preserve exact bytes.

**Wave 1a Surprises status: 8/9 actionable today (Surprise #6 was a Wave 1a misread but does not affect Slice 1c viability).**

**HALT POINT OUTCOME: no shifts. Wave 2 may proceed using Part 7 §7.1 line numbers directly.**
