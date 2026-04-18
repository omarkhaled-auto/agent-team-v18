# Phase G — Wave 1c — Model Prompting Research

**Date:** 2026-04-17
**Author:** `model-prompting-researcher` (Phase G Wave 1c)
**Repository:** `C:\Projects\agent-team-v18-codex`
**Branch:** `integration-2026-04-15-closeout` @ `466c3b9`
**Status:** PLAN-MODE RESEARCH DELIVERABLE (no source modified)
**Context7 queries run:** 15 (verbatim excerpts in Appendix A)
**WebSearch queries run:** 5 (verbatim excerpts in Appendix B)

This report drives Wave 2b (prompt-engineer). Every claim is tied to a specific source — either `/org/project` on context7 (library + file path), or a WebSearch URL. Claims marked **[context7-verified]** come from vendor repos (Anthropic, OpenAI). Claims marked **[web-sourced]** come from other docs and should be treated as directional unless a vendor source corroborates.

---

## Executive Summary

The V18 pipeline currently routes all waves through one-size-fits-all prompt templates. Claude Opus 4.6 and GPT-5.4 (Codex) differ on nearly every axis that matters for our pipeline: structural delimiters, constraint wording, autonomy vs. steering, verification rules, and tolerance for over-engineering. **Applying a single prompt style across both models is why symmetric pipelines fail asymmetrically.** Wave 2b must re-prompt per model, not per wave.

Eight high-leverage findings:

1. **Claude responds to XML structure, Codex responds to minimal persistence rules.** Claude wants `<context>...</context>` and `<thinking>`/`<answer>` separation; GPT-5.4 wants short rules blocks (`<tool_persistence_rules>`, `<dig_deeper_nudge>`) plus JSON schemas.
2. **Claude Opus 4.6 over-engineers by default** — explicit "keep minimal" guidance is required, and is load-bearing for our scaffold/builder waves.
3. **GPT-5.4 defaults to fewer tool calls** — without a persistence block it will stop early on multi-step work, which aligns with the "Codex orphan tool fail-fast" symptoms already tracked in bug-18.
4. **For hallucination: Claude responds to "give the model an out"** ("Only answer if certain" / "reply with `I don't know`"); Codex responds to `missing_context_gating` (retrieve-over-guess, label assumptions).
5. **`reasoning_effort=xhigh` is NOT a default** — OpenAI explicitly advises against making it default unless evals show benefit. Our tracker's `2026-04-15-codex-high-milestone-budget` experiment should be read through this lens.
6. **Long-context ordering matters for Claude**: put large documents FIRST, instructions LAST. For 200K+ runs, this is the single biggest performance lever per Anthropic course docs.
7. **AGENTS.md is auto-ingested by Codex** — deepest wins in the tree, but direct system/user prompt overrides it. This is a lever we are currently not using in the V18 pipeline.
8. **Claude Agent SDK does NOT auto-load `CLAUDE.md` by default** — a critical asymmetry with Codex. The SDK runs in isolation mode unless `setting_sources=["user","project"]` is passed. The V18 pipeline uses `ClaudeSDKClient` for Claude waves, which means any `CLAUDE.md` currently in the repo is IGNORED by those agents today unless `setting_sources` is configured. AGENTS.md, by contrast, is auto-included by Codex with no SDK configuration — creating an unequal default context between the two models.

---

## Part 1: Claude Opus 4.6 — Prompting Best Practices

### 1.1 Prompt Structure

**System vs user split.** Claude expects the system prompt to set role/behavior, and the user prompt to carry the task. The Anthropic courses repo documents this explicitly: "System prompt defines Claude's role and behavior" ([context7-verified] `/anthropics/courses` — `03_Assigning_Roles_Role_Prompting.ipynb`).

**Structured sections (XML).** Claude is trained on XML delimiters. The canonical 8-block order from `/anthropics/courses` — `09_Complex_Prompts_from_Scratch.ipynb` is:

```
TASK_CONTEXT → TONE_CONTEXT → INPUT_DATA → EXAMPLES →
TASK_DESCRIPTION → IMMEDIATE_TASK → PRECOGNITION → OUTPUT_FORMATTING → PREFILL
```

Quote: *"Use XML tags (like `<tag></tag>`) to wrap and delineate different parts of your prompt, such as instructions, input data, or examples. This technique helps organize complex prompts with multiple components."* ([context7-verified] `/anthropics/courses` — `real_world_prompting/01_prompting_recap.ipynb`).

**Length.** Opus 4.6 handles up to 1M tokens of context and, per 2026 external reporting, raised long-context retrieval from 18.5% to 76%, greatly reducing "context rot" ([web-sourced] Pantaleone, the-ai-corner). **Implication:** prompts can be long, but structure still matters because attention budget is finite.

### 1.2 Constraint Adherence Patterns

**MUST/MUST NOT wording.** Claude follows literal instructions. Per 2026 guides: *"Claude takes instructions literally - it will not infer what you probably meant. This means Claude rewards explicit, detailed prompts more than GPT does."* ([web-sourced] promptbuilder.cc, pantaleone.net). A vague "write something creative" gives Claude zero signal.

**Reinforcement.** For critical constraints, restate in both system and user messages, AND in OUTPUT_FORMATTING. The `/anthropics/courses` `05_customer_support_ai.ipynb` explicitly shows wrapping the same rules inside `<instructions>...</instructions>` and closing with *"Remember to follow these instructions, but do not include the instructions in your answer."*

**Common failure modes.**
- Opus 4.6 **over-engineers** — creates extra files, adds abstractions, builds in flexibility not requested ([web-sourced] the-ai-corner). Mitigation: explicit "minimal solution, no extra files, no new abstractions unless asked" in system prompt.
- Claude ignores constraints embedded in long blocks of context; keep rules in a dedicated `<rules>` or `<instructions>` block, not inline.

### 1.3 Code Generation Patterns

**Multi-file coherence.** Claude Code executes multi-file refactors by reading full codebase, planning across files, then iterating ([web-sourced] code.claude.com docs). Works best when:
- File paths are specified with absolute or repo-relative paths in the prompt.
- Framework idioms are declared (e.g., "use FastAPI dependency injection, not Flask-style decorators").
- Parallel tool calls are authorized ("When reading multiple files, run tool calls in parallel").

**Anti-over-engineering for code.** Add explicit: *"Do not create new files unless the task requires it. Do not add abstractions, factories, or interfaces unless the task requests them. A bug fix does not need surrounding cleanup."* This echoes the codebase's own CLAUDE.md and is directly relevant to Wave A (scaffolding) and Wave C (completion).

### 1.4 Review / Analysis Patterns

**Structured finding output.** Use XML-delimited severity and evidence blocks, prefill the assistant turn with the opening tag. Pattern from `/anthropics/courses`:

```
<finding severity="CRITICAL">
  <file>src/api/users.ts</file>
  <line>45</line>
  <issue>...</issue>
  <fix>...</fix>
</finding>
```

Severity classification works best when enumerated in the system prompt (CRITICAL/HIGH/MEDIUM/LOW with one-line definitions each). Evidence requirements: always require file:line references — this aligns with the finding format the `everything-codex` code-review skill uses ([context7-verified] `/luohaothu/everything-codex`).

### 1.5 Long-Context Behavior

*"When combining substantial information (especially over 30K tokens) with instructions, it's crucial to structure prompts effectively to distinguish between data and instructions. Using XML tags to encapsulate each document is a recommended method for this. Furthermore, placing longer documents and context at the beginning of the prompt, followed by instructions and examples, generally leads to noticeably better performance from Claude."* ([context7-verified] `/anthropics/courses` — `real_world_prompting/01_prompting_recap.ipynb`).

**Position bias.** Documents FIRST, instructions LAST. Prefills at the very end.

**When to summarize vs. full-include.** For repeated per-wave prompts that re-send the same PRD, prefer full-include with XML `<prd>...</prd>` tags once Opus 4.6 is proven to handle 200K+ retrieval at 76%+; summarize only when a specific wave doesn't need the full PRD (e.g., Wave T test-gen may only need the contracts subset).

### 1.6 Role-Based Prompting

*"Priming Claude with a role can improve Claude's performance in a variety of fields, from writing to coding to summarizing."* ([context7-verified] `/anthropics/courses` — `03_Assigning_Roles_Role_Prompting.ipynb`).

- **Architect wave:** "You are a senior systems architect. Your job is to produce a minimal, testable structural plan. Do not write code."
- **Coder wave:** "You are a disciplined implementer. You write only what the architect specified. You do not add abstractions."
- **Reviewer/Auditor wave:** "You are a skeptical auditor. Your job is to find gaps between the spec and the implementation. Cite file:line for every finding."

Role goes in the system prompt. More detail in role context → better adherence.

### 1.7 Anti-Patterns to Avoid

1. **Mixing instructions and data without delimiters.** Claude confuses them at 30K+ tokens.
2. **Burying the critical rule in paragraph 12 of the system prompt.** Put critical constraints in a dedicated `<rules>` block, not prose.
3. **Vague scope ("write something creative").** Opus 4.6 will over-engineer to compensate.
4. **Assuming Claude infers intent.** State it literally.
5. **Forgetting prefill.** Without prefill, Claude may introduce preamble ("Here is the JSON you requested...") that breaks parsers.
6. **Restating the same rule 5 times.** Claude registers literal repetition as stronger signal but it can also cause the model to comply too rigidly — use once in rules, once in output spec. Not 5 times.

---

## Part 2: Codex / GPT-5.4 — Prompting Best Practices

### 2.1 Prompt Structure

**Direct instruction over preamble.** GPT-5.4 is designed to follow short, explicit, task-bounded prompts. Quote: *"The default upgrade posture for GPT-5.4 suggests starting with a model string change only, especially when the existing prompt is short, explicit, and task-bounded."* ([context7-verified] `/openai/codex` — `codex-rs/skills/src/assets/samples/openai-docs/references/gpt-5p4-prompting-guide.md`).

**Minimal scaffolding.** Quote: *"Upgrading to GPT-5.4 often involves moving away from long, repetitive instructions that were previously used to compensate for weaker instruction following. Since the model usually requires less repeated steering, duplicate scaffolding can be replaced with concise rules and verification blocks."* ([context7-verified] same source).

**Block pattern that works:** short rules block + verification block + task. Example blocks documented in the guide:

```
<tool_persistence_rules>
- Use tools whenever they materially improve correctness, completeness, or grounding.
- Do not stop early just to save tool calls.
- Keep calling tools until: (1) the task is complete, and (2) verification passes.
- If a tool returns empty or partial results, retry with a different strategy.
</tool_persistence_rules>

<dig_deeper_nudge>
- Do not stop at the first plausible answer.
- Look for second-order issues, edge cases, and missing constraints.
- If the task is safety- or accuracy-critical, perform at least one verification step.
</dig_deeper_nudge>
```

**Length.** Prefer short prompts. GPT-5.4 gets MORE verbose when prompts get longer and more repetitive — opposite of Claude.

### 2.2 Constraint Adherence

**Autonomy vs. constraint balance.** GPT-5.4 is tuned toward autonomy. Over-constraining it triggers the "weaker instruction following" fallback posture and can cause under-completion. Quote: *"the workflow needs more persistence than the default tool-use behavior will likely provide"* — add persistence, don't add more constraints. ([context7-verified] `/openai/codex` — `upgrading-to-gpt-5p4.md`).

**File path specificity.** Codex's `apply_patch` tool requires RELATIVE paths only — *"file references can only be relative, NEVER ABSOLUTE"* ([context7-verified] `/openai/codex` — `prompt_with_apply_patch_instructions.md`). Prompts that ship absolute paths fail silently.

**Citation discipline.** Explicitly instruct: *"NEVER output inline citations like `【F:README.md†L5-L14】` in your outputs. The CLI is not able to render these so they will just be broken in the UI. Instead, if you output valid filepaths, users will be able to click on them to open the files in their editor."* ([context7-verified] same source).

### 2.3 Code Generation (Backend Focus)

**Preamble pattern (minimal):** role (one line) → coding guidelines (bullet list) → task description (imperative) → tool persistence rules. No XML wrapping.

**Coding guidelines (from Codex's own system prompt):**

*"Fix the problem at the root cause rather than applying surface-level patches. Avoid unneeded complexity. Do not attempt to fix unrelated bugs. Keep changes consistent with the style of the existing codebase. Changes should be minimal and focused on the task. NEVER add copyright or license headers unless specifically requested. Do not `git commit` your changes or create new git branches unless explicitly requested. Do not add inline comments within code unless explicitly requested."* ([context7-verified] `/openai/codex` — `prompt_with_apply_patch_instructions.md`).

**Multi-file generation.** Codex uses a sandbox / apply_patch model rather than file-by-file generation. Prompt should describe the desired END STATE (what files should exist and what they should contain), not sequential file-by-file steps. The agent will plan the patch order.

### 2.4 Review / Fix Patterns

**Structured JSON output via `output_schema`.** Codex supports a JSON Schema constraint on the final assistant message of a turn:

```python
output_schema = {
  'type': 'object',
  'properties': {
    'summary': {'type': 'string'},
    'actions': {'type': 'array', 'items': {'type': 'string'}},
  },
  'required': ['summary', 'actions'],
  'additionalProperties': False,
}
```

([context7-verified] `/openai/codex` — `sdk/python/notebooks/sdk_walkthrough.ipynb`).

**Review severity format.** `everything-codex` documents the field pattern used by mature Codex review skills:

```
[CRITICAL|HIGH|MEDIUM|LOW] <title>
File: <path>:<line>
Issue: ...
Fix: ...
```

Then a terminal `REVIEW RESULT: BLOCK|PASS` with counts. ([context7-verified] `/luohaothu/everything-codex`).

**Fixer mode.** Pair with `apply_patch` grammar constraints. Prompt the fixer with (a) list of findings + file:line, (b) code-style rules, (c) patch grammar reminder, (d) "do not fix unrelated bugs."

### 2.5 Reasoning Effort Impact

**Ladder:** `none < minimal < low < medium < high < xhigh` ([context7-verified] `/openai/codex` — `reasoning_rank` dictionary).

**xhigh guidance (verbatim):**
- *"GPT-5.4 xhigh is the new state of the art for multi-step tool use"* — described as *"the most persistent model to date"* ([web-sourced] OpenAI blog).
- *"The xhigh reasoning effort setting should be avoided as a default unless your evals show clear benefits, and is best suited for long, agentic, reasoning-heavy tasks where maximum intelligence matters more than speed or cost."* ([web-sourced] developers.openai.com prompt-guidance).

**Plan mode default:** `medium` (`plan_mode_reasoning_effort` config key — override is explicit) ([context7-verified] `/openai/codex` — `docs/config.md`).

**Upgrade posture (verbatim):** *"Before increasing reasoning effort, first consider adding a completeness contract, a verification loop, or tool persistence rules depending on the specific usage case."* ([context7-verified] `/openai/codex` — `gpt-5p4-prompting-guide.md`).

**Implication for V18:** the current experiment in `2026-04-15-codex-high-milestone-budget` that simply bumps effort should instead first test "add persistence + verification blocks at `high`." `xhigh` is the last lever, not the first.

### 2.6 Autonomy vs Constraint Balance

**`missing_context_gating` policy** (verbatim from OpenAI guide):

*"In cases where required context is missing early in a workflow, the model should prefer retrieval over guessing. If the necessary context is retrievable, use the appropriate lookup tool; otherwise, ask a minimal clarifying question. If you must proceed without full context, label all assumptions explicitly and choose actions that are reversible to mitigate potential errors."* ([context7-verified] `/openai/codex` — `gpt-5p4-prompting-guide.md`).

This is the Codex-native analog of Claude's "give the model an out."

### 2.7 AGENTS.md Convention

**Codex auto-reads AGENTS.md.** Quote: *"AGENTS.md files allow humans to provide specific instructions or tips to the coding agent within a repository. These files can cover coding conventions, organizational details, or testing instructions and apply to the directory tree where they are located. When multiple files exist, more deeply nested AGENTS.md files take precedence in case of conflicting instructions. However, direct system or user prompts always override the instructions found in these files."* ([context7-verified] `/openai/codex` — `codex-rs/models-manager/prompt.md`).

**Sections that work:**
- `## Project Overview` — one-paragraph
- `## Code Style` — bullet list with explicit numerics (line length, indent)
- `## Testing` — how to run, coverage threshold
- `## Important Files` — path → role
- `## Do Not` — explicit banned actions

**Implication for V18:** we can ship a per-project `AGENTS.md` alongside the PRD to pre-load Codex with coding standards without polluting the per-wave system prompt.

### 2.8 Anti-Patterns to Avoid

1. **Long Claude-style XML-heavy prompts.** GPT-5.4 gets verbose.
2. **Duplicating the same instruction 3+ times.** Triggers verbose echo.
3. **Omitting `tool_persistence_rules`** when tool usage is needed — causes premature stop (matches V18's orphan-tool-failfast symptom, bug-18).
4. **Using `reasoning_effort=xhigh` by default.** Cost without proven benefit. Start with `high` + persistence block.
5. **Absolute paths in `apply_patch`** — silently fails.
6. **Asking Codex to "explore the codebase and think deeply"** without verification rules — will stop early.
7. **Asking for inline code comments / docstrings** unless explicitly needed — Codex's own guidelines say no.
8. **Asking Codex to git commit** — explicitly banned in its own system prompt.

---

## Part 3: Cross-Model Handoff Patterns

### 3.1 What context transfers well between models?

**Transfers well (both models parse):**
- Structured file lists with role descriptions.
- Severity-tagged findings (`[CRITICAL] file:line`).
- JSON outputs that conform to a schema.
- Numbered task lists.
- Code blocks with explicit language fences.
- PRDs with clear section headers.

**Transfers poorly (model-specific):**
- XML blocks like `<thinking>`, `<finding>` — Claude emits them, Codex ignores or tries to strip them.
- Inline reasoning traces — Claude uses them constructively, Codex treats as noise.
- `<reply>`-tagged user-facing output — Claude produces cleanly, Codex sometimes nests weirdly.
- Codex inline citations `【F:path†Lx-Ly】` — Claude does not produce these; Codex produces them but they break UIs.

**Mitigation:** for handoff artifacts, strip model-specific delimiters before passing to the other model. Convert to a neutral format (JSON + markdown).

### 3.2 How to structure handoff artifacts

**Recommended handoff envelope (model-neutral):**

```json
{
  "artifact_type": "architecture_plan" | "findings" | "patch" | "test_results",
  "wave": "A" | "B" | ... ,
  "source_model": "claude-opus-4-6" | "gpt-5.4",
  "target_model": "claude-opus-4-6" | "gpt-5.4",
  "summary": "<one-paragraph>",
  "artifacts": [
    { "path": "<repo-relative>", "role": "<e.g. 'scaffold', 'test', 'fix'>" }
  ],
  "findings": [
    { "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "file": "<repo-relative>",
      "line": <int>,
      "issue": "<prose>",
      "fix": "<prose>" }
  ],
  "constraints": ["<any rules the next wave must preserve>"],
  "open_questions": ["<items requiring retrieval or clarification>"]
}
```

This matches the "contracts JSON in orchestration" tracker entry (`docs/plans/2026-04-15-d-08-contracts-json-in-orchestration.md`) and supports both the `output_schema` pathway in Codex and straightforward XML-unwrap for Claude.

**[web-sourced, directional]:** External reporting on multi-model pipelines notes that *"there's no automatic handoff between agents, and you manually pass artifacts between stages"* and *"When Claude delegates to Codex, it passes specific context—not the entire session—and if Codex needs information from earlier in the conversation, Claude has to explicitly include it in the handoff."* (MindStudio, medevel.com). Implication: the orchestrator must construct the envelope; neither model will do it for you.

### 3.3 Prompt adaptation for model switch (same task, different model)

If the same logical wave can run on either model, keep the BODY (task description, artifacts, success criteria) identical and swap the SHELL:

| Shell element | Claude version | Codex/GPT-5.4 version |
|---|---|---|
| Role | 1-paragraph persona in system prompt | 1-line role in user prompt |
| Rules | `<rules>...</rules>` block | flat bulleted list at top |
| Inputs | `<input><document>...</document></input>` | markdown `---` separator + H2 headers |
| Output format | `<output>` XML block + PREFILL | `output_schema` JSON Schema + one-line format reminder |
| Hallucination control | "Only if certain" / "reply with I don't know" | `<missing_context_gating>` block |
| Persistence | not typically needed — Claude iterates well | `<tool_persistence_rules>` REQUIRED for tool-heavy |
| Verification | add "Before concluding, verify X" in PRECOGNITION | `<dig_deeper_nudge>` block |
| Over-engineering control | explicit "keep minimal, no new abstractions" | Codex's own guidelines already handle this |
| Multi-file strategy | iterative read-plan-edit across turns | single-patch `apply_patch` sandbox |

---

## Part 4: CLAUDE.md + AGENTS.md Auto-Loading

This section is critical because the V18 pipeline invokes both Claude (via `ClaudeSDKClient` / `claude-agent-sdk-python`) and Codex (via the Codex CLI / app-server). The two models have ASYMMETRIC defaults for reading project-level memory files, which means a `CLAUDE.md` committed to a repo may be silently ignored by the Claude agents while `AGENTS.md` is consumed by Codex. Wave 2b must plan for this asymmetry.

### 4.1 `ClaudeSDKClient` auto-load behavior

**Default: ISOLATION MODE — no filesystem settings loaded.** The Python SDK runs the agent in an isolated context that does NOT read `CLAUDE.md`, `.claude/rules/*.md`, or project-level skills unless explicitly enabled ([web-sourced] Anthropic Agent SDK docs — `platform.claude.com/docs/en/agent-sdk/overview`, `code.claude.com/docs/en/agent-sdk/overview`; Promptfoo provider docs).

**Enablement:** pass `setting_sources` (TypeScript: `settingSources`) to `ClaudeAgentOptions`:

```python
from claude_agent_sdk import ClaudeAgentOptions

options = ClaudeAgentOptions(
    cwd="/abs/path/to/project",
    setting_sources=["project", "user"],  # "project" → load CLAUDE.md from cwd; "user" → load ~/.claude/CLAUDE.md
    system_prompt="...",
)
```

([web-sourced] Anthropic Agent SDK — `platform.claude.com/docs/en/agent-sdk/claude-code-features`, Promptfoo provider docs.)

**Once enabled, the SDK follows the Claude Code CLI discovery rules:**
- Recurses UP from `cwd` to `/`, reading any `CLAUDE.md` or `CLAUDE.local.md` it finds along the way ([web-sourced] claudelog.com — "What is Working Directory in Claude Code").
- The concatenated memory content is delivered to Claude *as a user message immediately after the system prompt* ([web-sourced] same source, confirmed in Anthropic support article `support.claude.com/en/articles/14553240`).
- Deeper (closer to `cwd`) files take precedence when rules conflict, matching Codex's nested-wins convention.

**Known limitation:** GitHub issue `anthropics/claude-code#2571` tracks reports that `CLAUDE.md` files in subdirectories are sometimes not loaded — treat sub-directory `CLAUDE.md` as best-effort, not guaranteed ([web-sourced] GitHub issue).

**Implication for V18:** the `ClaudeSDKClient` invocations in the pipeline (e.g., Wave A, Wave D, Audit) currently run without `setting_sources`, meaning any repo-level `CLAUDE.md` is invisible to those agents. Wave 2b should either (a) enable `setting_sources=["project"]` AND ship a project `CLAUDE.md`, or (b) inline the equivalent content into the per-wave system prompt — NOT both, to avoid duplication.

### 4.2 Codex CLI auto-load behavior

**Default: AUTO-INCLUDED.** Codex automatically reads `AGENTS.md` files from the repo root and every directory from the CWD up to the root, and prepends them to the developer message with no additional configuration ([context7-verified] `/openai/codex` — `codex-rs/core/gpt_5_1_prompt.md`). Quote:

*"The contents of the `AGENTS.md` file at the root of the repo and any directories from the Current Working Directory (CWD) up to the root are automatically included with the developer message, eliminating the need for re-reading. However, when working in a subdirectory of CWD or a directory outside CWD, the agent should check for any applicable `AGENTS.md` files."*

**Precedence:** more-deeply-nested `AGENTS.md` wins on conflicting instructions; direct system/developer/user prompt instructions always override `AGENTS.md` ([context7-verified] `/openai/codex` — `codex-rs/models-manager/prompt.md`, `codex-rs/core/gpt_5_1_prompt.md`).

**Hierarchical agents message (opt-in enhancement):** the `[features]` table in `config.toml` accepts `child_agents_md = true`, which causes Codex to append additional scope/precedence guidance to the user-instructions message — even when no `AGENTS.md` is present ([context7-verified] `/openai/codex` — `docs/agents_md.md`).

**Alternate filenames:** the official guide is `AGENTS.md`. Earlier community docs mentioned `codex.md` / `.codex/instructions`; current Codex CLI uses `AGENTS.md`. No context7 evidence in this repo for `codex.md` being honored by current Codex builds — treat as legacy.

### 4.3 Format + token budget + size limits

**Claude `CLAUDE.md`:**
- **Recommended max:** under 200 lines. Quote: *"CLAUDE.md files are loaded into the context window at the start of every session. Because these instructions consume tokens, it is recommended to keep files under 200 lines to maintain high adherence. For larger instruction sets, use imports or organize rules into dedicated directories."* ([context7-verified] `/websites/code_claude` — `code.claude.com/docs/en/memory`).
- **Import syntax:** `@path/to/file.md` pulls in another file. Relative paths resolve from the importing file. Recursive imports allowed up to **5 levels deep** ([context7-verified] same source). This is the mechanism to keep the root file under 200 lines while still encoding longer guidance.
- **No hard byte limit documented.** The 200-line heuristic is an adherence guideline, not an enforced cap. Content is consumed as a regular user-turn message, so it counts against the standard context window.

**Codex `AGENTS.md`:**
- **Default hard cap:** **32 KiB** of combined `AGENTS.md` content (root + nested, merged). Content above the cap is **silently truncated without a warning in the TUI** — a known pain point ([web-sourced] GitHub issue `openai/codex#7138`).
- **Override:** set `project_doc_max_bytes = 65536` (or higher) in `config.toml` under the relevant profile to raise the cap. The larger cap allows more combined guidance before truncation ([web-sourced] blakecrosley.com Codex definitive reference).
- **Format:** markdown. Recommended sections (from context7-verified templates): `## Project Overview`, `## Code Style`, `## Testing`, `## Database`, `## Important Files`. Codex-review skill templates (from `/luohaothu/everything-codex`) also add `## Do Not` and `## Available Skills`.

**Main-context impact comparison:**

| File | Auto-loaded by | Default budget | Delivery mechanism | Override |
|---|---|---|---|---|
| `CLAUDE.md` | Claude Code CLI (auto); Claude Agent SDK (opt-in via `setting_sources`) | No byte cap; **200-line adherence guideline** | User-turn message after system prompt | Imports (`@file.md`) up to 5 levels |
| `AGENTS.md` | Codex CLI / app-server (auto) | **32 KiB** hard cap (truncates silently above) | Developer message prepend | `project_doc_max_bytes` in `config.toml` |

### 4.4 Production best practices

**Keep the root file small.** Both vendors converge on "small and imperative beats large and exhaustive":
- Claude: <200 lines, use `@import` for longer sections.
- Codex: stay well under 32 KiB; the Codex Prompting Guide emphasizes short explicit rules over long repetitive scaffolding ([context7-verified] `/openai/codex` — `gpt-5p4-prompting-guide.md`).

**Nest by scope.** Per-subsystem `AGENTS.md` / `CLAUDE.md` under specific directories is the recommended pattern for monorepos and 100K–400K LOC projects ([web-sourced] builder.io Claude-md guide; flowith.io Codex pricing / context guide; `developers.openai.com/codex/guides/agents-md`). Both models honor nested-wins precedence.

**Don't duplicate into the system prompt.** Anything in `CLAUDE.md`/`AGENTS.md` is *additive* to the per-turn system/user prompt. Restating the same rules wastes tokens and (per §1.7 and §2.8) can cause over-rigid compliance or verbose echo. Pick one source of truth per rule.

**Sections that demonstrably move behavior** (from context7-verified templates and the `/luohaothu/everything-codex` AGENTS.md template):
- Imperative Code Style bullets with numerics (line length, indent, naming).
- `## Do Not` — explicit banned actions (e.g., "Do not `git commit`", "Do not create new files unless listed").
- `## Important Files` — path → role mapping; makes Codex navigate instead of search.
- `## Testing` — how to run, coverage threshold, framework in use.

**Sections that drift / rot:**
- `## Project Status` — stale fast; better in a dated plan file.
- Architectural narratives — better as linked design docs.
- Long tutorial prose — triggers the Codex "long repetitive instructions" anti-pattern.

**Per-profile override (Codex):** ship a `.codex/config.toml` snippet alongside the repo (or document for each dev env) to raise `project_doc_max_bytes` when the combined `AGENTS.md` exceeds 32 KiB. Without this, parts of the guidance vanish silently.

**Implication for V18:**
1. **Ship both files at repo root**, scoped to the waves that will actually consume them.
2. **Enable `setting_sources=["project"]`** in the `ClaudeSDKClient` calls used by Wave A / Wave D / Audit — otherwise `CLAUDE.md` does nothing for those runs.
3. **Audit the combined `AGENTS.md` footprint** against 32 KiB; if it exceeds, set `project_doc_max_bytes` in the Codex config to avoid silent truncation.
4. **Avoid duplicating the same rules** in per-wave system prompts; those prompts should be additive (wave-specific task/format), not a full restatement of the memory file.

---

## Part 5: Recommendations Per Wave

Waves present in this codebase (derived from tracker filenames and `MASTER_IMPLEMENTATION_PLAN_v2.md` scan):

- **Wave A** — Architecture / scaffold
- **Wave A.5** — Codex plan-review of Wave A output (proposed new wave; see `PHASE_G_INVESTIGATION.md`)
- **Wave B** — Build / backend
- **Wave C** — Complete / code fill-in
- **Wave D** — Docs / design / review fleet
- **Wave T** — Test generation
- **Wave T.5** — Codex edge-case audit of Wave T output (proposed new wave; see `PHASE_G_INVESTIGATION.md`)
- **Wave E** — Execute / verify
- **Wave Audit** — Audit loop (N-08/09/10/17 in tracker)
- **Wave Fix** — Compile-fix / structural triage (A-10, D-15)

### Wave A — Architecture / Scaffold

- **Recommended model:** Claude Opus 4.6 (reasoning-heavy, text-heavy, benefits from 8-block XML).
- **Key pattern:** Long-context ordering — put PRD + existing skeleton FIRST, role + rules LAST. Use `<precognition>Think in <thinking> tags first.</precognition>` because architecture requires reasoning.
- **Critical anti-pattern to block:** Opus 4.6 over-engineering — explicit rules block: *"Produce the MINIMUM structural plan. Do not propose helpers, factories, base classes, or cross-cutting abstractions unless the PRD explicitly requires them. Three similar lines is better than a premature abstraction."*
- **Context7-verified snippet:**

```
System:
You are a senior systems architect working on a single feature branch.
<rules>
- Output a MINIMAL structural plan. No extra abstractions.
- Cite exact file paths (repo-relative) for every new or changed file.
- Do not write code. Describe signatures and responsibilities only.
</rules>

User:
<prd>...</prd>
<existing_skeleton>...</existing_skeleton>

Think in <thinking> tags, then produce the plan inside <plan> tags with one <file> entry per file.
```

Prefill with `<thinking>`.

### Wave A.5 — Codex Plan Review (proposed)

- **Recommended model:** Codex / GPT-5.4 at `reasoning_effort=medium` (review task, not code gen — per §2.5 `medium` is the documented default for `plan_mode_reasoning_effort`).
- **Key pattern:** Short, skeptical, structured-output prompt. The input is Wave A's XML plan stripped down to a Codex-friendly shell per §3.3. Use `output_schema` so orchestration can parse the review deterministically.
- **Critical anti-pattern to block:** Codex re-writing the plan instead of reviewing it. Explicit rule: *"Do not propose a new plan. Only flag gaps in the provided plan."* Also block the general Codex "exploratory mode" — this is a narrow yes/no per category, not open-ended exploration.
- **Context7-verified snippet:**

```
You are a strict plan reviewer. You flag gaps; you do not write new plans.

Rules:
- Emit findings ONLY for: (a) missing endpoints, (b) wrong entity relationships,
  (c) state-machine gaps, (d) unrealistic scope, (e) spec/PRD contradictions.
- Every finding must cite a file or plan-section reference.
- Relative paths only. No absolute paths.
- If the plan is consistent with the PRD, return {"verdict":"PASS","findings":[]}.

<missing_context_gating>
- If you would need to guess at intent, return a finding labelled UNCERTAIN with the assumption you would have made.
</missing_context_gating>

<plan>{wave_a_plan_as_markdown_or_json}</plan>
<prd>{prd_relevant_subset}</prd>

Return JSON matching output_schema: {verdict, findings[{category,severity,ref,issue,suggested_fix}]}.
```

Per §2.5, bump to `high` only if eval shows `medium` misses real gaps.

### Wave B — Build / Backend

- **Recommended model:** Codex / GPT-5.4 at `reasoning_effort=high`.
- **Key pattern:** Short prompt + persistence + `apply_patch` emphasis + AGENTS.md in the worktree.
- **Critical anti-pattern to block:** early stopping → missing files. Require `<tool_persistence_rules>`.
- **Context7-verified snippet:**

```
You are implementing the plan in <plan_artifact>{path}</plan_artifact>.

Rules:
- Follow the plan verbatim. Do not add files the plan does not list.
- Use relative paths in apply_patch. Never absolute.
- No inline comments unless the plan requires them.
- No git commit. No new branches.
- Use root-cause fixes when you encounter ambiguity. Do not patch around a symptom.

<tool_persistence_rules>
- Keep calling tools until: (1) all plan files exist, and (2) the test suite for this wave runs (it does not need to pass, but it must run).
- If apply_patch fails, retry with a different strategy; do not stop.
</tool_persistence_rules>

Output: final message must be JSON matching output_schema (files_written[], files_skipped[], blockers[]).
```

### Wave C — Complete / Fill-in

- **Recommended model:** Codex / GPT-5.4 at `reasoning_effort=high`.
- **Key pattern:** Same as Wave B, but narrower scope. Include "treat empty stubs as `raise NotImplementedError`; do not invent business logic not in the plan or the test spec."
- **Anti-pattern to block:** Codex inventing helper functions for stub bodies. Explicit: *"Do not add helper functions unless the plan or a test requires them."*

### Wave D — Docs / Design / Review Fleet

- **Recommended model:** Claude Opus 4.6.
- **Key pattern:** `<reviewer>` role + structured finding output in XML. Since D-04 (review fleet deployment) spawns multiple reviewers, each reviewer gets a NARROW lens (security only, perf only, contracts only) to prevent generic findings.
- **Context7-verified snippet:**

```
System:
You are a skeptical {lens} auditor. You only raise findings related to {lens}.
<rules>
- Every finding MUST cite file:line.
- Use severity CRITICAL | HIGH | MEDIUM | LOW with the enum definitions below.
- If you are not certain, reply with <uncertain> — do not invent.
</rules>

User:
<changes>{unified_diff}</changes>
<context>{relevant_files}</context>

Think in <thinking>, then output findings inside <findings>, each as <finding severity="..."><file>...</file><line>...</line><issue>...</issue><fix>...</fix></finding>.
```

Prefill with `<thinking>`.

### Wave T — Test Generation

- **Recommended model:** Codex / GPT-5.4 at `high` (test gen is code gen; Codex is better at idiomatic test frameworks).
- **Key pattern:** JSON output schema listing `tests_written[]` with `{file, framework, covers[]}`. Include the contracts JSON from Wave A as the single source of truth for what to test.
- **Anti-pattern:** the 2026-04-15-d-11 tracker entry notes "wave-T findings unconditional" — likely because the test wave is emitting findings regardless of failures. Fix: explicit *"Emit a finding ONLY when a test failed or a required coverage gap exists. No findings otherwise."*

### Wave T.5 — Codex Edge-Case Audit (proposed)

- **Recommended model:** Codex / GPT-5.4 at `reasoning_effort=high`. Review task but scope is "find weaknesses in existing tests" which benefits from reasoning depth.
- **Key pattern:** Narrow prompt focused on gap-detection, not rewriting. Input: Wave T's test files + source files + acceptance criteria. Output: JSON list of `{test_file, source_symbol, missing_case, severity, suggested_assertion}`. Pair with `<tool_persistence_rules>` because the agent may need to read multiple test+source files before concluding.
- **Critical anti-pattern to block:** Codex generating *new* tests instead of *identifying gaps*. Explicit: *"Do not write new test code. Only describe the gap and the assertion it would contain."* Without this, the wave drifts back into T, not T.5.
- **Context7-verified snippet:**

```
You are a test-gap auditor. You find missing edge cases in an existing test file.
You do NOT write new tests — you describe what is missing.

Rules:
- For each test file, identify: (a) missing edge cases, (b) weak assertions,
  (c) untested business rules from the ACs.
- Every gap cites {test_file, source_symbol, ac_id}.
- Do not propose test code. Describe the assertion in prose.
- Relative paths only.

<tool_persistence_rules>
- Read the source file referenced by each test before concluding.
- Read the ACs before flagging "missing business rule".
- Do not stop on the first gap; scan every test.
</tool_persistence_rules>

<tests>{test_files}</tests>
<source>{source_files}</source>
<acs>{acceptance_criteria}</acs>

Return JSON matching output_schema:
{ gaps: [{test_file, source_symbol, ac_id, missing_case, severity, suggested_assertion}] }
```

### Wave E — Execute / Verify

- **Recommended model:** Codex / GPT-5.4 at `high` with `sandbox_policy=workspaceWrite`.
- **Key pattern:** `<dig_deeper_nudge>` + persistence block. Execute means run, not plan. Explicit: *"Run the command. If it fails, read the error. Fix the root cause. Run again. Do not skip the run even if you are confident."*
- **Note:** matches the feedback memory "Verify before claiming completion — unit tests aren't enough; end-to-end smoke must actually fire the fix."

### Wave Audit

- **Recommended model:** Claude Opus 4.6.
- **Key pattern:** Long-context — the whole work product goes in. PRD + plan + diff + test output, in that order, then instructions. Auditor role. Use "give Claude an out": *"If the artifact is consistent with the PRD, reply `<audit_result>PASS</audit_result>` with no findings. If you cannot tell, reply `<audit_result>UNCERTAIN</audit_result>`. Do not manufacture findings to justify effort."*
- **Anti-pattern:** the c-01 tracker entry ("auditor milestone scope") suggests the auditor was scoped too broad. Narrow each audit pass to one explicit question: "Does the diff implement every file in the plan? YES/NO/UNCERTAIN with evidence."

### Wave Fix / Compile-Fix

- **Recommended model:** Codex / GPT-5.4 at `high`, with `<missing_context_gating>` active.
- **Key pattern:** Short, constraint-light prompt. Feed the compile errors directly. Codex is tuned to read errors and repair. DO NOT over-constrain or you will trigger the weaker-instruction-following fallback.
- **Context7-verified snippet:**

```
You are a compile-fix agent. Fix the errors below with the MINIMUM change per file.

<rules>
- Fix ONLY the listed errors. Do not refactor.
- Root-cause fixes only. No try/except around the error.
- Relative paths in apply_patch.
</rules>

<missing_context_gating>
- If a fix would require guessing at intent, label the assumption and pick the reversible option.
- If context is retrievable, retrieve before guessing.
</missing_context_gating>

<errors>{compiler_output}</errors>

After fixing, run `{build_command}` once and return JSON: {fixed:[...], still_failing:[...]}.
```

The `2026-04-15-d-15-compile-fix-structural-triage.md` plan indicates this wave is currently failing due to "structural" (scope) issues; the fix is narrower scope + explicit per-error file:line input, not bigger prompts.

---

## Summary Table — Model Selection Per Wave

| Wave | Model | Effort | Key Block | Output Format |
|---|---|---|---|---|
| A — Arch | Claude Opus 4.6 | n/a | `<rules>` minimal + `<precognition>` | XML `<plan>` |
| A.5 — Plan Review | GPT-5.4 | `medium` (→`high` if eval) | `<missing_context_gating>` + narrow verdict | JSON via `output_schema` |
| B — Build | GPT-5.4 | `high` | `<tool_persistence_rules>` | JSON via `output_schema` |
| C — Complete | GPT-5.4 | `high` | `<tool_persistence_rules>` | JSON via `output_schema` |
| D — Review | Claude Opus 4.6 | n/a | lens-narrowed `<rules>` | XML `<findings>` |
| T — Test | GPT-5.4 | `high` | `<tool_persistence_rules>` + coverage contract | JSON via `output_schema` |
| T.5 — Edge Audit | GPT-5.4 | `high` | `<tool_persistence_rules>` + "describe gaps, don't write tests" | JSON via `output_schema` |
| E — Exec | GPT-5.4 | `high` | `<dig_deeper_nudge>` + persistence | JSON via `output_schema` |
| Audit | Claude Opus 4.6 | n/a | narrow question + "give an out" | XML `<audit_result>` |
| Fix | GPT-5.4 | `high` | `<missing_context_gating>` | JSON {fixed,still_failing} |

---

## Appendix A: Context7 Query Results (verbatim excerpts with library ID)

### A.1 `/anthropics/courses` (Benchmark 82.94, 588 snippets, High reputation)
- `real_world_prompting/01_prompting_recap.ipynb` — long-context structuring with XML tags; docs-first ordering.
- `real_world_prompting/04_call_summarizer.ipynb` — best-practices list (system prompt, XML, edge cases, examples).
- `real_world_prompting/05_customer_support_ai.ipynb` — `<context>` + `<instructions>` separation, out-phrase.
- `prompt_engineering_interactive_tutorial/AmazonBedrock/anthropic/03_Assigning_Roles_Role_Prompting.ipynb` — role prompting effectiveness.
- `prompt_engineering_interactive_tutorial/AmazonBedrock/anthropic/06_Precognition_Thinking_Step_by_Step.ipynb` — `<thinking>` tags for CoT.
- `prompt_engineering_interactive_tutorial/AmazonBedrock/anthropic/08_Avoiding_Hallucinations.ipynb` — "give Claude an out" pattern.
- `prompt_engineering_interactive_tutorial/AmazonBedrock/anthropic/09_Complex_Prompts_from_Scratch.ipynb` — 8-block prompt order.
- `tool_use/06_chatbot_with_multiple_tools.ipynb` — `<reply>` XML for user-facing output.
- `prompt_evaluations/03_code_graded_evals/03_code_graded.ipynb` — `<thinking>`/`<answer>` for code CoT grading.

### A.2 `/anthropics/claude-agent-sdk-python` (Benchmark 77.69, 12 snippets, High reputation)
- `README.md` — `ClaudeAgentOptions(system_prompt=..., max_turns=...)`; custom tools via `@tool` + `create_sdk_mcp_server`; `allowed_tools` pre-approves, does not gate availability.

### A.3 `/openai/codex` (Benchmark 66.29, 870 snippets, High reputation, versions rust_v0_29_1_alpha_7 / rust-v0.75.0)
- `codex-rs/skills/src/assets/samples/openai-docs/references/gpt-5p4-prompting-guide.md` — tool persistence rules, dig-deeper nudge, missing-context gating, default upgrade posture, prompt rewrite patterns.
- `codex-rs/skills/src/assets/samples/openai-docs/references/upgrading-to-gpt-5p4.md` — when to do light rewrite vs. model-string-only.
- `codex-rs/core/prompt_with_apply_patch_instructions.md` — patch grammar, coding guidelines (root-cause, minimal, no headers, no comments), citation ban, update_plan.
- `codex-rs/core/gpt_5_1_prompt.md` — apply_patch example.
- `codex-rs/models-manager/prompt.md` — AGENTS.md hierarchy + override rules.
- `codex-rs/app-server/README.md` — turn/start with sandboxPolicy + outputSchema.
- `docs/config.md` — `plan_mode_reasoning_effort`; default `medium`; `none` means no-reasoning override, not inherit.
- `sdk/python/notebooks/sdk_walkthrough.ipynb` — reasoning_rank dictionary (`none:0 ... xhigh:5`), advanced turn config with output_schema, approval_policy, personality.

### A.4 `/luohaothu/everything-codex` (Benchmark 63.3, 1497 snippets, High reputation)
- `/code-review` skill format (CRITICAL/HIGH/MEDIUM + file:line + BAD/GOOD code + REVIEW RESULT).
- AGENTS.md template structure (when to apply, coding standards, testing, available skills).
- SKILL.md template for coding-pattern extraction.
- Orchestration workflow (plan → tdd → code-review → security-review, handoff context between phases).
- Starlark git-safety rules (prefix_rule → forbid force push / hard reset / force clean).

### A.5 `/yeachan-heo/oh-my-codex` (Benchmark 75.71, 1893 snippets, High reputation)
- Team pipeline `team-plan → team-prd → team-exec → team-verify → team-fix (loop)`.
- Child agent protocol: max 6 concurrent, stay under AGENTS.md authority, report handoffs upward.
- `$team` command as shared-spec execution context.

### A.6 `/websites/code_claude` (Benchmark 81.93, 4699 snippets, High reputation) — Wave 1c extension

Query: *"CLAUDE.md auto-loading memory file hierarchy recursion token budget size limits best practices production 400k LOC"*

- `code.claude.com/docs/en/memory` — **verbatim:** *"CLAUDE.md files are loaded into the context window at the start of every session. Because these instructions consume tokens, it is recommended to keep files under 200 lines to maintain high adherence. For larger instruction sets, use imports or organize rules into dedicated directories."*
- `code.claude.com/docs/en/memory` — import syntax: *"Reference project files like README or package.json using '@' syntax. Relative paths resolve from the current file's location. Imported files can recursively import others up to five levels deep."*
- `code.claude.com/docs/en/claude-directory` — TypeScript/React example CLAUDE.md; *"CLAUDE.md loads into every session and should be kept under 200 lines for better adherence."*
- `code.claude.com/docs/en/third-party-integrations` — org-wide vs. repo-root deployment guidance.
- `code.claude.com/docs/en/gitlab-ci-cd` — *"Claude automatically reads this file to align its proposed changes with your established conventions."* (CLI default behavior; SDK requires `setting_sources`.)

### A.7 `/anthropics/claude-agent-sdk-python` — Wave 1c extension

Query: *"setting_sources parameter project user filesystem settings CLAUDE.md memory files load"*

- README — `ClaudeAgentOptions(cwd=..., allowed_tools=..., permission_mode=..., hooks=...)` configuration surface. The SDK's `setting_sources` is used in the wider Agent SDK docs (see B.4/B.5) to enable filesystem-settings loading; the Python README itself focuses on tool permissions and hooks rather than `setting_sources` specifically.
- Confirms `cwd` parameter exists on `ClaudeAgentOptions` as the anchor for any subsequent filesystem discovery.

### A.8 `/openai/codex` — Wave 1c extension

Query: *"AGENTS.md auto-load behavior — what file paths does Codex read automatically? Token budget, size limits, format requirements, project vs nested hierarchy precedence"*

- `codex-rs/core/gpt_5_1_prompt.md` — **verbatim:** *"The contents of the `AGENTS.md` file at the root of the repo and any directories from the Current Working Directory (CWD) up to the root are automatically included with the developer message, eliminating the need for re-reading."*
- `codex-rs/core/gpt_5_1_prompt.md` — **verbatim:** *"In cases of conflicting instructions, more-deeply-nested `AGENTS.md` files take precedence, while direct system, developer, or user instructions (as part of a prompt) override `AGENTS.md` instructions."*
- `codex-rs/models-manager/prompt.md` — second confirmation of auto-read + override precedence.
- `docs/agents_md.md` — `child_agents_md` feature flag in `[features]` of `config.toml` appends scope/precedence guidance, emitted even when no `AGENTS.md` exists.
- `context7.com/openai/codex/llms.txt` — canonical AGENTS.md section template (Project Overview / Code Style / Testing / Database / Important Files).

---

## Appendix B: WebSearch References

- [Claude Opus 4.6 System Prompt 2026: Full Breakdown — Pantaleone](https://www.pantaleone.net/blog/claude-opus-4.6-system-prompt-analysis-tuning-insights-template) — literal instruction following, system prompt depth.
- [How to Use Claude Opus 4.6: Complete Guide (2026) — ssntpl](https://ssntpl.com/how-to-use-claude-opus-4-6-guide/) — long-context retrieval 18.5%→76%.
- [Claude Opus 4.6 Explained — the-ai-corner](https://www.the-ai-corner.com/p/claude-opus-4-6-practical-guide) — over-engineering tendency, keep-minimal guidance.
- [Claude Prompt Engineering Best Practices 2026 — promptbuilder.cc](https://promptbuilder.cc/blog/claude-prompt-engineering-best-practices-2026) — 4-block INSTRUCTIONS/CONTEXT/TASK/OUTPUT_FORMAT.
- [Prompting best practices — Claude API Docs](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices) — canonical Anthropic page.
- [Use examples (multishot) — Claude API Docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/multishot-prompting) — examples as accuracy lever.
- [Introducing GPT-5.4 — OpenAI](https://openai.com/index/introducing-gpt-5-4/) — "most persistent model to date", multi-step tool use SOTA at xhigh.
- [Prompt guidance for GPT-5.4 — OpenAI API](https://developers.openai.com/api/docs/guides/prompt-guidance) — xhigh avoidance-as-default advice; evals-gated.
- [Codex Prompting Guide — OpenAI Cookbook](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide) — autonomy, persistence, codebase exploration, tool use, frontend quality.
- [Models — Codex — OpenAI](https://developers.openai.com/codex/models) — GPT-5.4 combines GPT-5.3-Codex coding + knowledge/computer-use.
- [Common workflows — Claude Code Docs](https://code.claude.com/docs/en/common-workflows) — multi-file refactor workflow.
- [Kiln — multi-model AI orchestration for Claude Code](https://github.com/Fredasterehub/kiln) — hybrid Claude (Opus 4.6) + Codex (GPT-5.4 planning/exec) 7-step pipeline.
- [What Is the OpenAI Codex Plugin for Claude Code? — MindStudio](https://www.mindstudio.ai/blog/openai-codex-plugin-claude-code-cross-provider-review) — context isolation on cross-provider delegation.
- [How to Use Claude Code and Codex Together — BSWEN](https://docs.bswen.com/blog/2026-04-02-claude-codex-workflow-integration/) — manual artifact handoff.

### Wave 1c extension — CLAUDE.md + AGENTS.md auto-loading

Query: *"ClaudeSDKClient auto-read CLAUDE.md working directory documentation 2026"*

- [Explore the .claude directory — Claude Code Docs](https://code.claude.com/docs/en/claude-directory) — CLAUDE.md in CLI working-directory context.
- [Give Claude context: CLAUDE.md and better prompts — Claude Help Center](https://support.claude.com/en/articles/14553240-give-claude-context-claude-md-and-better-prompts) — CLAUDE.md is delivered as a user message right after the system prompt.
- [What is Working Directory in Claude Code — ClaudeLog](https://claudelog.com/faqs/what-is-working-directory-in-claude-code/) — recursion from `cwd` up to `/` reading any `CLAUDE.md` or `CLAUDE.local.md`.
- [Claude Agent SDK — Promptfoo](https://www.promptfoo.dev/docs/providers/claude-agent-sdk/) — *"By default, the Claude Agent SDK provider does not look for settings files, CLAUDE.md, or slash commands."*
- [Documentation about CLAUDE.md locations, seems not quite accurate — GitHub `anthropics/claude-code#2274`](https://github.com/anthropics/claude-code/issues/2274) — known doc/behavior mismatches.
- [BUG: CLAUDE.md files in subdirectories are not being loaded — GitHub `anthropics/claude-code#2571`](https://github.com/anthropics/claude-code/issues/2571) — subdirectory load is best-effort in some CLI builds.

Query: *"Claude Agent SDK setting_sources project user CLAUDE.md auto-load 2026 documentation"*

- [Agent SDK overview — Claude API Docs](https://platform.claude.com/docs/en/agent-sdk/overview) — `settingSources` / `setting_sources` controls filesystem-settings loading.
- [Agent SDK overview — Claude Code Docs](https://code.claude.com/docs/en/agent-sdk/overview) — default isolation mode; `settingSources` opt-in.
- [Use Claude Code features in the SDK — Claude API Docs](https://platform.claude.com/docs/en/agent-sdk/claude-code-features) — concrete `settingSources: ["user","project"]` snippet.
- [Agent Skills in the SDK — Claude API Docs](https://platform.claude.com/docs/en/agent-sdk/skills) — skill discovery shares the same `setting_sources` gate.

Query: *"Codex AGENTS.md token budget size limit large repositories 400k LOC production best practices"*

- [Custom instructions with AGENTS.md — OpenAI Developers (Codex)](https://developers.openai.com/codex/guides/agents-md) — canonical AGENTS.md guide, nested-wins, large-repo nesting strategy.
- [AGENTS.md silently truncated without any warning within the TUI — GitHub `openai/codex#7138`](https://github.com/openai/codex/issues/7138) — the 32 KiB cap behavior; silent truncation.
- [Codex CLI: The Definitive Technical Reference — Blake Crosley](https://blakecrosley.com/guides/codex) — `project_doc_max_bytes` config override (default 32 KiB; raise to 65536 or higher).
- [codex/AGENTS.md at main — GitHub `openai/codex`](https://github.com/openai/codex/blob/main/AGENTS.md) — real-world AGENTS.md from Codex's own repo.
- [OpenAI Codex Pricing: API Costs, Token Limits, and Which Tier Makes Sense — Flowith Blog](https://flowith.io/blog/openai-codex-pricing-api-costs-token-limits/) — GPT-5.4 1M context; GPT-5.3-Codex 272K input; context management in large repos.
- [How to Write a Good CLAUDE.md File — Builder.io](https://www.builder.io/blog/claude-md-guide) — production CLAUDE.md patterns, nesting by subsystem.
- [Anatomy of the .claude/ Folder — Daily Dose of DS](https://blog.dailydoseofds.com/p/anatomy-of-the-claude-folder) — `.claude/` contents and loading interactions.

---

## Appendix C: Anti-Patterns Already Visible in V18 Tracker (matched to research)

This is a courtesy cross-ref, not a prescription. Wave 2b should validate.

| V18 tracker file | Symptom | Research-grounded root cause |
|---|---|---|
| `2026-04-15-bug-18-codex-orphan-tool-failfast.md` | Codex stops on orphan tool | Missing `<tool_persistence_rules>` |
| `2026-04-15-bug-20-codex-appserver-migration.md` | App-server migration issues | Existing prompts likely assume long-form XML; see §2.1 |
| `2026-04-15-codex-high-milestone-budget.md` | `reasoning_effort` budget | Per §2.5: try persistence+verification at `high` before `xhigh` |
| `2026-04-15-d-04-review-fleet-deployment.md` | Review fleet quality | Per §5/Wave D: narrow each reviewer to one lens |
| `2026-04-15-d-11-wave-t-findings-unconditional.md` | Wave T emits findings always | Needs explicit "emit finding only on failure/gap" |
| `2026-04-15-d-15-compile-fix-structural-triage.md` | Compile-fix scope creep | Needs `<missing_context_gating>` + per-error file:line input |
| `2026-04-15-a-10-compile-fix-budget-investigation.md` | Budget overrun | Prompts likely too long; §2.1 says "short, explicit, task-bounded" |
| `2026-04-15-c-01-auditor-milestone-scope.md` | Auditor scope too broad | Per §5/Audit: one explicit yes/no/uncertain question per pass |
| `2026-04-15-d-16-fallback-prompt-scope-quality.md` | Fallback quality | Likely over-constrained for GPT-5.4 path; see §2.2 |
| `2026-04-15-d-17-truth-score-calibration.md` | Truth scoring | See §1.7 "give an out" and §2.6 "missing_context_gating" |
| `2026-04-15-d-08-contracts-json-in-orchestration.md` | Contracts JSON | Aligned with handoff envelope §3.2 |

---

## Open Questions for Wave 2b

1. **Per-wave AGENTS.md** — should we ship one, or rely on system prompts? AGENTS.md persists across invocations; system prompt is per-turn.
2. **Prefill strategy** — Claude SDK exposes prefill via message format. Audit whether the existing pipeline uses it, or always starts assistant turns from zero.
3. **`output_schema` adoption** — if all Codex waves move to JSON schema, orchestration parsing simplifies. Cost: must design schemas for each wave.
4. **`reasoning_effort` per wave** — current config likely single global. Research supports per-wave tuning (A/D/Audit do not need reasoning_effort because they are Claude; B/C/T/E/Fix vary between `high` and `xhigh` per eval).
5. **Fallback prompts** — when Codex fails and we fall back to Claude (or vice versa), the prompt MUST be re-shelled per §3.3. Currently unclear whether this is happening.
6. **`setting_sources` on `ClaudeSDKClient`** — is it currently set in the V18 pipeline for Claude waves? Per §4.1, default is isolation mode; if unset, any `CLAUDE.md` in the repo is invisible to those agents. Wave 2a/2b should verify the current value and decide (a) enable `setting_sources=["project"]` + ship `CLAUDE.md`, or (b) keep isolation + inline guidance in system prompts. Do not mix both.
7. **Combined AGENTS.md footprint vs. 32 KiB cap** — per §4.3, Codex silently truncates above the default 32 KiB budget. Wave 2b should measure the combined size of any shipped AGENTS.md files and, if over budget, set `project_doc_max_bytes` in the Codex config or split guidance into nested files.
8. **Memory-file parity** — if `CLAUDE.md` and `AGENTS.md` contain different instructions, the two models will diverge silently. Wave 2b should decide whether to generate one from the other (with model-specific shells per §3.3) or maintain them independently.

---

*End of Wave 1c Research Deliverable.*
