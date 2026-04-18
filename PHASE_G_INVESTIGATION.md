# PHASE G — Pipeline Restructure + Agent Prompt Engineering (INVESTIGATION)

**Repository:** `C:\Projects\agent-team-v18-codex`
**Branch base:** `integration-2026-04-15-closeout` HEAD `466c3b9` (after Phase F merge). Contains ALL Phases A-F.
**Source of truth:** `docs/plans/2026-04-16-deep-investigation-report.md` + `docs/plans/2026-04-17-phases-a-to-f-comprehensive-report.md` + all build logs.
**Test baseline:** 10,636 passed / 0 failed after Phase F.

---

## THIS IS PLAN MODE — READ ONLY. DO NOT MODIFY ANY FILES.

This is the FINAL architectural push before real production builds. It combines:

1. **Pipeline restructure** — 5 interconnected changes to the wave sequence and provider routing
2. **Agent prompt engineering** — perfect EVERY prompt for EVERY agent based on the model running it, context7-verified best practices, and observed behavior from real builds

The output is a comprehensive design document. A separate implementation session will execute the design.

---

## CONTEXT — WHY THIS MATTERS

**Competition data (3 blind comparisons + community reports):**
- Claude Opus 4.6 is "leagues ahead" for frontend/UI, architecture, creative problem-solving, coherent multi-file work
- GPT-5.4 excels at backend execution, debugging, root-cause analysis, precise pattern-following, edge-case testing, strict code review
- The proven production pattern on 100K-500K+ LOC codebases: Claude for architecture + frontend + tests, Codex for backend + debugging/fixes
- "#1 trick for large codebases": persistent architecture doc accumulating knowledge across sessions
- Cross-model plan review catches plan-level errors before expensive execution
- Handing test suites to Codex for edge-case hardening improves coverage

**Our own build data:**
- Build-l: 28 findings, Wave B failed at probe, 8 LLM-bug findings from training-data-approximate NestJS code
- Build-j: 41 findings, compile-fix exhaustion on Wave D (Codex frontend was weaker)
- TaskFlow Build A (Claude): cleaner frontend, faster
- TaskFlow Build B (Codex): slightly better structural backend, weaker frontend
- Phase E: every agent now has full MCP access + ClaudeSDKClient bidirectional + interrupt + orphan detection
- Phase F: 5 reviewers found 34 issues; 4 sweeper modules were dead code until wired; Prisma 5 shutdown hook was deprecated pattern

**Current pipeline state (post-Phase-F):**
- 10,636 tests / 0 failed / 23+ feature flags
- Every Claude agent has MCP access (context7, sequential-thinking)
- Codex app-server transport ready behind flag
- Audit-fix loop wired with observability
- Scaffold verifier + spec reconciler + ownership contract all implemented
- Framework idioms pre-fetched via N-17 before Wave B/D

---

## WHAT WE'RE DESIGNING

### Change 1: Pipeline Restructure — Merge Wave D + D.5 → Single Claude Wave D
- Claude takes FULL frontend (wiring + design tokens + polish + i18n + compile check)
- Kill Wave D.5 as a separate wave
- The independent report says Claude is "leagues ahead" for frontend
- Build B showed Codex interpreted the IMMUTABLE rule as "don't use the client at all"

### Change 2: Codex Takes the Fix/Debug Role
- Currently fix agents use Claude
- Route audit-driven fixes to Codex instead
- GPT excels at "root-cause analysis, ripple-effect scanning, precise pattern-following"
- Phase F found fixes that Claude's band-aid tendencies would have missed

### Change 3: ARCHITECTURE.md + CLAUDE.md + AGENTS.md
- **ARCHITECTURE.md** — project-level doc accumulating across milestones (entities, patterns, decisions). Dynamic — grows with each milestone.
- **CLAUDE.md** — CLI-level "constitution" auto-loaded by Claude Code. Static — defines pipeline routing, coding standards, stack conventions, TDD rules, forbidden patterns. The "#1 trick" from 400K+ LOC developers.
- **AGENTS.md** — CLI-level "constitution" for Codex CLI. Backend-focused subset adapted for Codex's prompt style.
- Three files, three purposes: CLI auto-load (CLAUDE.md/AGENTS.md) + orchestrator prompt injection (ARCHITECTURE.md).

### Change 4: Codex Plan Review (Wave A.5)
- After Wave A produces architecture, Codex reviews the plan
- Catches plan-level errors before $10+ implementation spend
- GPT's "stricter reviewer/QA" strength applied at the cheapest intervention point

### Change 5: Codex Edge-Case Audit on Wave T Output
- After Wave T writes tests, Codex reviews for missing edge cases
- GPT "generates more meaningful unit tests focusing on business logic/edge cases"
- Feeds gaps back into findings or directly writes additional tests

### Change 6: PROMPT ENGINEERING — Perfect Every Agent Prompt
This is the BIG addition. For EVERY agent/wave in the pipeline:
- Rewrite the prompt for the MODEL that runs it (Claude prompt style ≠ Codex prompt style)
- Context7-verify prompting best practices per model
- Incorporate build log evidence (what actually works vs what doesn't)
- Account for the NEW architecture (full MCP access, bidirectional SDK, interrupt capability)
- Role-specific optimization (architect thinks differently than a code-writer)

---

## PRE-FLIGHT (MANDATORY)

1. Confirm branch state: `git log -1` → HEAD `466c3b9`
2. `pip show agent-team-v15` → editable path is current worktree
3. Run `pytest tests/ -v --tb=short` → confirm 10,636 / 0 / 35

---

## AGENT TEAM STRUCTURE

### Team Composition (7 agents)

| Agent Name | Type | MCPs | Role |
|------------|------|------|------|
| `pipeline-architecture-investigator` | `superpowers:code-reviewer` | context7, sequential-thinking | Wave 1a — reads entire wave execution system + provider routing + transport |
| `prompt-archaeology-investigator` | `superpowers:code-reviewer` | context7, sequential-thinking | Wave 1b (parallel) — reads every existing prompt + build logs + agent behavior patterns |
| `model-prompting-researcher` | `superpowers:code-reviewer` | context7, sequential-thinking | Wave 1c (parallel) — context7 deep dive on Claude + Codex prompting best practices |
| `pipeline-designer` | `general-purpose` | context7, sequential-thinking | Wave 2 — designs the new pipeline structure (Changes 1-5) based on Wave 1a findings |
| `prompt-engineer` | `general-purpose` | context7, sequential-thinking | Wave 2 (parallel) — designs every agent prompt based on Wave 1b + 1c findings |
| `integration-verifier` | `superpowers:code-reviewer` | context7, sequential-thinking | Wave 3 — verifies pipeline design + prompt designs are internally consistent |
| `report-synthesizer` | `general-purpose` | sequential-thinking | Wave 4 — consolidates all findings into the final design document |

### Coordination Flow

```
Wave 1 (parallel, 3 investigators):
    │
    1a: pipeline-architecture-investigator
    │   Reads: wave_executor.py, agents.py, cli.py, codex_transport.py, 
    │          codex_appserver.py, provider_router.py, config.py,
    │          mcp_servers.py, state.py, audit_team.py, fix_executor.py
    │   Produces: PIPELINE_FINDINGS.md
    │
    1b: prompt-archaeology-investigator
    │   Reads: EVERY prompt-building function in agents.py + codex_prompts.py +
    │          audit_prompts.py + fix_prd_agent.py + ALL build logs
    │   Produces: PROMPT_ARCHAEOLOGY.md
    │
    1c: model-prompting-researcher
    │   Context7 queries: Claude prompting docs, Codex prompting docs,
    │                     Claude Agent SDK prompt patterns, Codex CLI prompt patterns
    │   Produces: MODEL_PROMPTING_RESEARCH.md
    │
    HALT POINT: team lead reviews all 3 investigation reports
    │
Wave 2 (parallel, 2 designers):
    │
    2a: pipeline-designer → PIPELINE_RESTRUCTURE_DESIGN.md
    2b: prompt-engineer → PROMPT_ENGINEERING_DESIGN.md
    │
    HALT POINT: team lead reviews both designs for consistency
    │
Wave 3 (solo): integration-verifier
    │   Verifies: pipeline design + prompt designs don't conflict;
    │             every wave has a prompt; every prompt targets the right model;
    │             compilation of wave sequences is coherent
    │   Produces: INTEGRATION_VERIFICATION.md
    │
Wave 4 (solo): report-synthesizer
    │   Consolidates everything into:
    │   PHASE_G_INVESTIGATION_REPORT.md (the master design document)
```

---

# WAVE 1A — PIPELINE ARCHITECTURE INVESTIGATION

**Agent:** `pipeline-architecture-investigator`
**MCPs:** `context7`, `sequential-thinking`

Read the ENTIRE wave execution system. For every function, document: what it does, who calls it, what model runs it, what context it receives, what it produces.

### Files to Read (COMPLETE reads)

- `src/agent_team_v15/wave_executor.py` (FULL — this is the core; thousands of LOC)
- `src/agent_team_v15/cli.py` — all wave dispatch sections, audit loop, fix dispatch, recovery
- `src/agent_team_v15/agents.py` — all `build_wave_*_prompt()` functions (read signatures + first 20 lines of each to understand structure; full read on Wave A, B, D, D.5, T, E)
- `src/agent_team_v15/codex_prompts.py` — CODEX_WAVE_B_PREAMBLE, CODEX_WAVE_D_PREAMBLE, any other Codex-specific prompt wrappers
- `src/agent_team_v15/codex_transport.py` — legacy subprocess transport (understand what we're replacing)
- `src/agent_team_v15/codex_appserver.py` — Phase E's new JSON-RPC transport
- `src/agent_team_v15/provider_router.py` — how does provider_map decide Claude vs Codex per wave?
- `src/agent_team_v15/config.py` — all v18 flags, provider_map config, depth settings
- `src/agent_team_v15/mcp_servers.py` — MCP server configuration for both providers
- `src/agent_team_v15/state.py` — what persists across milestones
- `src/agent_team_v15/audit_team.py` — auditor definitions, dispatch
- `src/agent_team_v15/audit_prompts.py` — every auditor prompt
- `src/agent_team_v15/audit_agent.py` — Phase E's ClaudeSDKClient migration
- `src/agent_team_v15/fix_executor.py` — fix dispatch, unified fix path
- `src/agent_team_v15/fix_prd_agent.py` — fix PRD generation
- `src/agent_team_v15/milestone_spec_reconciler.py` — Phase B's reconciliation
- `src/agent_team_v15/scaffold_verifier.py` — Phase B's verification
- `src/agent_team_v15/orphan_detector.py` — Phase E's orphan detection
- `src/agent_team_v15/infra_detector.py` — Phase F's runtime infrastructure detection
- `src/agent_team_v15/confidence_banners.py` — Phase F's confidence stamping
- `.mcp.json` — MCP server configuration

### What to Document

**1. Complete Wave Sequence Map:**
```
For each template (full_stack, backend_only, frontend_only):
  Wave letter → function that builds prompt → function that dispatches → 
  model (Claude/Codex) → compile check after? → artifact produced →
  who consumes the artifact
```

**2. Provider Routing Mechanics:**
- How does `provider_map` in config determine which model runs which wave?
- What's the default routing? What's configurable?
- How does `_execute_single_wave_sdk` (Claude) vs `_execute_wave_codex` (Codex) differ?
- What wrapper/preamble does Codex get that Claude doesn't?
- How does the new `codex_appserver.py` (Phase E) change the dispatch?

**3. Fix Agent Routing:**
- Where is the fix agent dispatched? (cli.py `_run_audit_fix_unified`)
- What model currently runs fixes? (Always Claude? Configurable?)
- What context does the fix agent receive?
- How would routing to Codex change the dispatch?
- What's the fix iteration loop shape?

**4. Persistent State Across Milestones:**
- STATE.json schema (what carries over)
- MASTER_PLAN.json (milestone statuses)
- `.agent-team/` directory contents
- MILESTONE_HANDOFF.md (who writes, who reads)
- Is there ANY persistent project-level document? (Answer: probably not — ARCHITECTURE.md is new)

**5. Context Window Usage:**
- Approximate token counts per wave prompt
- What gets truncated/summarized? (`_format_all_artifacts_summary`, etc.)
- What would change with 1M context?

**6. Wave D + D.5 Mechanics (for merge design):**
- What does Wave D (Codex) prompt contain that Wave D.5 (Claude) doesn't?
- What does Wave D.5 contain that Wave D doesn't?
- What overlaps?
- Where does design tokens injection happen in each?
- Where does the IMMUTABLE rule appear?

**7. Audit Loop Mechanics:**
- `_run_audit_loop` → `_run_milestone_audit` → `_run_audit_fix_unified` → re-audit
- What terminates the loop?
- Where does WAVE_FINDINGS.json inject?
- Where would Codex edge-case audit (Change 5) insert?

**8. CLAUDE.md + AGENTS.md Auto-Loaded CLI Files:**
- Does Claude Code CLI auto-read a `CLAUDE.md` or `.claude/instructions.md` from the repo root? (Context7 verify against `/anthropics/claude-agent-sdk-python` or Claude Code docs)
- Does our builder already have a CLAUDE.md? Search: `find . -name "CLAUDE.md" -o -name ".claude" -type d`
- Does Codex CLI auto-read an `AGENTS.md` or `codex.md` from the repo root? (Context7 verify against `/openai/codex`)
- If yes to either: what format do they expect? What content gets auto-injected?
- How does auto-loading interact with our orchestrator's `ClaudeSDKClient` prompt injection? (Does CLAUDE.md supplement the system prompt? Override it? Get ignored by programmatic sessions?)
- If our builder spawns `ClaudeSDKClient` sessions, does the repo-root CLAUDE.md still load? Or only for interactive `claude` CLI usage?
- **Key distinction:** CLAUDE.md/AGENTS.md = CLI-level auto-loaded session constitution (coding standards, wave routing, git workflow, test requirements). ARCHITECTURE.md = project-level knowledge accumulating across milestones (entities, patterns, decisions). They serve DIFFERENT purposes and BOTH may be needed.
- What should CLAUDE.md contain if we create one? (The "#1 trick" from 400K+ LOC developers: pipeline routing rules, coding standards, stack conventions, TDD rules, Docker commands, forbidden patterns)
- What should AGENTS.md contain? (Codex-specific subset? Backend-only rules? Same content adapted for Codex's prompt style?)

### Deliverable

`docs/plans/2026-04-17-phase-g-pipeline-findings.md` — every finding with file:line references.

---

# WAVE 1B — PROMPT ARCHAEOLOGY INVESTIGATION

**Agent:** `prompt-archaeology-investigator`
**MCPs:** `context7`, `sequential-thinking`

Read EVERY prompt-building function in the codebase. For each prompt, document: what it instructs, what context it injects, what model receives it, what the model actually produces (from build logs), and what the model gets WRONG (from audit findings).

### Prompt Functions to Read (ALL of these, FULL read)

**Wave prompts:**
- `build_wave_a_prompt()` in agents.py — architecture/schema wave
- `build_wave_b_prompt()` in agents.py — backend (Claude variant)
- `CODEX_WAVE_B_PREAMBLE` + `CODEX_WAVE_B_SUFFIX` in codex_prompts.py — backend (Codex variant)
- `build_wave_d_prompt()` in agents.py — frontend (currently Codex-targeted)
- `CODEX_WAVE_D_PREAMBLE` in codex_prompts.py — frontend Codex wrapper
- `build_wave_d5_prompt()` in agents.py — UI polish (Claude)
- `build_wave_t_prompt()` in agents.py — test generation (Claude)
- `build_wave_e_prompt()` in agents.py — verification/Playwright (Claude)

**Fix prompts:**
- `_build_compile_fix_prompt()` in wave_executor.py — compile-fix iteration
- `_ANTI_BAND_AID_FIX_RULES` constant — the anti-band-aid block
- `generate_fix_prd()` in fix_prd_agent.py — fix PRD generation
- The unified fix prompt in `_run_audit_fix_unified` (cli.py)
- The recovery prompt in `_build_recovery_prompt_parts` (cli.py)

**Audit prompts:**
- Every auditor prompt in audit_prompts.py (requirements, technical, interface, test, MCP/library, comprehensive, scorer)
- The scorer prompt (what scoring rubric does it use?)

**Orchestrator/system prompts:**
- `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` in agents.py — the top-level orchestrator
- Enterprise-mode orchestrator prompt (post-Phase-E: Python-dispatched, not Task())
- The shared `SHARED_INVARIANTS` block
- The `WAVE_T_CORE_PRINCIPLE` constant

**Scaffold/infrastructure prompts:**
- `build_adapter_instructions()` — integration adapter scaffolding
- Any planner prompts (vertical-slice phasing)

### What to Document Per Prompt

For EACH prompt function:

```
## <function_name> (file:line)

**Target model:** Claude / Codex / Either
**Approximate token count:** ~X tokens
**Context injected:**
  - [list every piece of context: PRD excerpts, REQUIREMENTS, artifacts, etc.]
**Instructions given:**
  - [summarize what the prompt tells the model to do]
**Rules/constraints:**
  - [list every MUST/MUST NOT/NEVER/ALWAYS rule]
**Known issues from builds:**
  - [list findings from build-j, build-l, Phase F reviewers that trace to this prompt]
**Prompt style analysis:**
  - Is this written for Claude-style (collaborative, nuanced) or Codex-style (autonomous, directive)?
  - Does it match the model that actually runs it?
  - What's missing?
  - What's redundant?
  - What actively hurts the model's output?
```

### Build Logs to Read

- `v18 test runs/build-j-closeout-sonnet-20260415/BUILD_LOG.txt` — baseline build, 41 findings
- `v18 test runs/build-l-gate-a-20260416/BUILD_LOG.txt` — post-closeout, 28 findings
- `v18 test runs/build-l-gate-a-20260416/.agent-team/AUDIT_REPORT.json` — the 28 findings in detail
- Phase F reviewer reports (if accessible): `docs/plans/2026-04-17-phase-f-report.md`
- Phase C architecture report: `docs/plans/2026-04-16-phase-c-architecture-report.md` (has context7-verified idioms)

### Key Questions

1. **Which prompts are Claude-optimized but run on Codex?** (Wave D currently)
2. **Which prompts are Codex-optimized but will need to run on Claude?** (Wave D after merge)
3. **Which prompts lack the NEW capabilities?** (Full MCP access, interrupt, Phase E architecture)
4. **Which prompts have stale instructions?** (References to patterns Phase B/C/D changed)
5. **Which prompts are too long?** (Context waste → worse output)
6. **Which prompts are too vague?** (Not enough structure → model improvises badly)
7. **Which prompts contradict each other?** (Wave A says X, Wave B says Y about the same concern)

### Deliverable

`docs/plans/2026-04-17-phase-g-prompt-archaeology.md` — complete catalogue of every prompt with analysis.

---

# WAVE 1C — MODEL PROMPTING RESEARCH

**Agent:** `model-prompting-researcher`
**MCPs:** `context7`, `sequential-thinking`

**THIS IS THE CRITICAL RESEARCH TASK.** Query context7 exhaustively for prompting best practices for BOTH models. The goal: understand exactly how Claude and Codex want to be prompted, so every wave prompt is optimized for its target model.

### Context7 Queries — Claude Prompting

1. `/anthropics/claude-agent-sdk-python` — how to structure prompts for ClaudeSDKClient sessions
2. `/anthropics/prompt-engineering` or equivalent — Claude's official prompt engineering guide
3. Search for: "Claude system prompt best practices", "Claude instruction following", "Claude structured output"
4. Search for: "Claude code generation prompt patterns", "Claude multi-file generation"
5. Search for: "Claude review prompt patterns", "Claude analysis prompt patterns"
6. Search for: how Claude handles long context (200K+) — focus vs attention patterns
7. Search for: Claude's response to MUST/NEVER vs softer guidance — what prompt style gets best adherence?

**Document for Claude:**
- Preferred prompt structure (system vs user? structured sections? XML tags?)
- How to get Claude to follow constraints reliably (what wording works? what doesn't?)
- How to get Claude to produce structured output (JSON, specific file formats)
- How to get Claude to handle multi-file generation without losing coherence
- How does Claude handle role-playing (architect vs coder vs reviewer)?
- What prompt patterns reduce hallucination in code generation?
- How does Claude handle long context — does more context help or hurt?

### Context7 Queries — Codex/GPT Prompting

8. `/openai/codex` — how to structure prompts for Codex CLI / app-server
9. Search for: "Codex prompt engineering", "GPT-5.4 code generation prompts"
10. Search for: "Codex plan mode", "Codex autonomous mode", "Codex reasoning effort"
11. Search for: how Codex handles `model_reasoning_effort: high` vs `xhigh`
12. Search for: Codex preamble/suffix patterns that improve code quality
13. Search for: how GPT handles STRICT instructions vs exploratory guidance
14. Search for: GPT structured output patterns (JSON mode, function calling)

**Document for Codex:**
- Preferred prompt structure (direct instruction? step-by-step? minimal preamble?)
- How to get Codex to follow constraints (autonomy-first vs constraint-first?)
- How to get Codex to produce specific file patterns (does it need exact paths?)
- How does `reasoning_effort` affect code quality? When to use high vs xhigh?
- What preamble patterns improve Codex's backend code generation?
- How does Codex handle multi-file generation? (sandbox model vs file-by-file?)
- What makes Codex a good REVIEWER/FIXER? (Prompt patterns for review mode)

### Context7 Queries — Cross-Model Patterns

15. Search for: "hybrid Claude Codex workflow", "multi-model pipeline"
16. Search for: "Claude for planning Codex for execution" patterns
17. Search for: "handoff between Claude and Codex" — what context transfers well?

### Context7 Queries — CLAUDE.md + AGENTS.md Auto-Loading

18. `/anthropics/claude-agent-sdk-python` or Claude Code docs — does `ClaudeSDKClient` auto-read `CLAUDE.md` from the working directory? Or only the interactive `claude` CLI?
19. `/openai/codex` — does Codex CLI auto-read `AGENTS.md` or `codex.md` or `.codex/instructions`? What file name? What format?
20. Search for: "CLAUDE.md best practices", "CLAUDE.md template", "CLAUDE.md 400k loc" — how do production developers structure this file?
21. Search for: "AGENTS.md codex", "codex instructions file" — equivalent for Codex?
22. If auto-loading confirmed: what's the token budget for CLAUDE.md content? Is there a size limit? Does it count against the main context window?

### Additional Research Sources (Web Search if Context7 insufficient)

- Anthropic's official prompt engineering documentation
- OpenAI's official Codex documentation
- Reddit communities: r/ClaudeAI, r/ClaudeCode, r/codex, r/ChatGPTPro
- Any published case studies on 100K+ LOC AI-assisted codebases

### Deliverable

`docs/plans/2026-04-17-phase-g-model-prompting-research.md` containing:

```
# Model Prompting Research

## Part 1: Claude Opus 4.6 — Prompting Best Practices
  - Prompt structure
  - Constraint adherence patterns
  - Code generation patterns
  - Review/analysis patterns
  - Long-context behavior
  - Role-based prompting
  - Anti-patterns to avoid

## Part 2: Codex / GPT-5.4 — Prompting Best Practices
  - Prompt structure
  - Constraint adherence patterns
  - Code generation patterns (backend focus)
  - Review/fix patterns
  - Reasoning effort impact
  - Autonomy vs constraint balance
  - Anti-patterns to avoid

## Part 3: Cross-Model Handoff Patterns
  - What context transfers well between models?
  - How to structure handoff artifacts
  - Prompt adaptation for model switch

## Part 4: Recommendations Per Wave
  For each wave (A, B, C, D, T, E, Audit, Fix):
  - Which model runs it (current + recommended)
  - Key prompting pattern to use
  - Key anti-pattern to avoid
  - Specific context7-verified example
```

---

# WAVE 2A — PIPELINE RESTRUCTURE DESIGN

**Agent:** `pipeline-designer`
**MCPs:** `context7`, `sequential-thinking`

**Reads:** PIPELINE_FINDINGS.md (from Wave 1a)

Designs all 5 pipeline changes with exact specifications. This is the implementation blueprint.

### Design Deliverables

**1. New Wave Sequences:**
```
full_stack:    [A, A.5(Codex review), Scaffold, B, C, D(Claude full), T, T.5(Codex edge-case), E, Audit, Fix(Codex)]
backend_only:  [A, A.5, Scaffold, B, C, T, T.5, E, Audit, Fix(Codex)]
frontend_only: [A, Scaffold, D(Claude full), T, T.5, E, Audit, Fix(Codex)]
```
Or recommend alternatives with rationale.

**2. Provider Routing Table:**
| Wave | Provider | Rationale |
|------|----------|-----------|
| A | Claude | Architecture, planning |
| A.5 | Codex | Strict reviewer |
| Scaffold | Python | Deterministic |
| B | Codex | Backend execution |
| C | Python | Deterministic contracts |
| D | Claude | Frontend (merged D+D.5) |
| T | Claude | Comprehensive tests |
| T.5 | Codex | Edge-case hardening |
| E | Claude | Verification, Playwright |
| Audit | Claude | Scoring, analysis |
| Fix | Codex | Root-cause debugging |

**3. Wave D Merge Design (D + D.5 → single Claude Wave D):**
- Exact prompt sections to combine
- What to keep from Wave D (Codex): IMMUTABLE rule, client manifest, state completeness
- What to keep from Wave D.5 (Claude): design tokens, polish rules, compile verification
- What to DROP: Codex autonomy directives, D.5's "don't change functionality" restriction (merged D does both)
- New compile check strategy (one at end? intermediate?)
- Config changes: remove `wave_d5_enabled`; update WAVE_SEQUENCES

**4. Codex Fix Routing Design:**
- Exact function to modify (`_run_audit_fix_unified` or `execute_unified_fix_async`)
- How Codex receives the codebase (full workspace access via app-server?)
- Fix prompt restructuring for Codex style
- Anti-band-aid block adaptation for Codex
- Fix iteration: does Codex handle multi-turn? Or one-shot per finding?
- Timeout: fixes are smaller than Wave B — 600s? 900s?

**5. ARCHITECTURE.md Design:**
- Content template (project structure, patterns, conventions, decisions, gotchas)
- Who creates it (Wave A, milestone 1)
- Who updates it (Wave A, every milestone after first)
- How it's injected (every wave reads it; prompt section `[PROJECT ARCHITECTURE]`)
- Size management (max ~500 lines; LLM summarizes if bigger)

**5b. CLAUDE.md Design (CLI-Level Constitution):**
Based on Wave 1a findings on whether Claude Code CLI auto-reads this file:
- If auto-loaded by ClaudeSDKClient sessions: design the content (wave routing rules, coding standards, stack conventions, TDD rules, Docker commands, forbidden patterns, naming conventions)
- If NOT auto-loaded by programmatic sessions: design it anyway for developer-facing sessions (debugging, manual runs) + document the limitation
- Content structure: follow the 100-400 line format that 400K+ LOC developers use
- Relationship to ARCHITECTURE.md: CLAUDE.md is STATIC (pipeline rules); ARCHITECTURE.md is DYNAMIC (project-specific accumulating knowledge)
- Update cadence: CLAUDE.md changes only when pipeline architecture changes; ARCHITECTURE.md changes every milestone

**5c. AGENTS.md Design (Codex CLI Constitution):**
Based on Wave 1a findings on whether Codex CLI auto-reads this file:
- Content: backend patterns, DTO conventions, module registration rules, NestJS idioms
- Adapted for Codex's prompt style (directive, autonomous, pattern-following)
- Relationship to CLAUDE.md: shares some content (stack conventions, naming); differs in style + scope (backend-focused for Codex)

**6. Wave A.5 (Codex Plan Review) Design:**
- Input: Wave A's architecture output + ARCHITECTURE.md
- Prompt: "Review this architecture plan. Flag: missing endpoints, wrong entity relationships, state machine gaps, unrealistic scope, spec contradictions."
- Output: structured findings list (JSON)
- Integration: findings feed back to orchestrator; orchestrator decides re-run Wave A or proceed with notes
- Cost estimate per milestone
- Skip conditions (simple milestones? low complexity score?)

**7. Wave T.5 (Codex Edge-Case Audit) Design:**
- Input: Wave T's test files + source files + ACs
- Prompt: "Review these tests. For each: identify missing edge cases, weak assertions, untested business rules. Return a structured list of gaps."
- Output: gap list (JSON) → fed to Wave T fix loop OR written as additional test files
- Should Codex WRITE tests or just IDENTIFY gaps?
- Integration point in wave sequence
- Cost estimate per milestone

### Deliverable

`docs/plans/2026-04-17-phase-g-pipeline-design.md`

---

# WAVE 2B — PROMPT ENGINEERING DESIGN

**Agent:** `prompt-engineer`
**MCPs:** `context7`, `sequential-thinking`

**Reads:** PROMPT_ARCHAEOLOGY.md (Wave 1b) + MODEL_PROMPTING_RESEARCH.md (Wave 1c)

This is the CORE deliverable. For EVERY agent/wave prompt in the system, produce:
1. The EXACT new prompt text (or structured changes to the existing prompt)
2. Why each change was made (citing research + build evidence)
3. What model it targets and why that model

### Prompts to Design/Rewrite

**Wave A — Architecture (Claude)**
- Current: `build_wave_a_prompt()` — how should it change?
- NEW: must also write/update ARCHITECTURE.md
- Must leverage Claude's architecture strength
- Must produce output consumable by Wave A.5 (Codex review)
- Prompt style: collaborative, high-level thinking, structured output

**Wave A.5 — Plan Review (Codex) [NEW WAVE]**
- Brand new prompt
- Codex review-mode: strict, pattern-following, finding-oriented
- Input context: Wave A output + ARCHITECTURE.md + REQUIREMENTS.md
- Output: structured findings JSON
- Prompt style: directive, checklist-driven, binary judgments

**Wave B — Backend (Codex)**
- Current: `build_wave_b_prompt()` + `CODEX_WAVE_B_PREAMBLE`
- Phase C added N-09 hardeners + N-17 framework idioms injection
- Must be optimized for Codex's execution style
- Must reference ARCHITECTURE.md patterns
- Prompt style: autonomous execution, precise file paths, no planning preamble

**Wave D — Frontend (Claude) [MERGED D + D.5]**
- REWRITE: combine Wave D (Codex-targeted) + Wave D.5 (Claude-targeted) into single Claude prompt
- Must include: IMMUTABLE rule, client manifest, design tokens, polish rules, i18n/RTL, compile verification
- Must REMOVE: Codex autonomy directives, "don't change functionality" (now it DOES functionality + polish)
- Must reference ARCHITECTURE.md patterns
- Prompt style: creative + precise, Claude's frontend strength
- Must handle the full lifecycle: wiring → design tokens → polish → compile check

**Wave T — Test Generation (Claude)**
- Current: `build_wave_t_prompt()` with WAVE_T_CORE_PRINCIPLE
- Must leverage Claude's test-writing strength
- Must produce output consumable by Wave T.5 (Codex review)
- WAVE_T_CORE_PRINCIPLE is LOCKED — do not change the principle, but optimize how it's communicated
- Must emit structured wave-t-summary JSON for downstream
- Prompt style: methodical, AC-coverage-driven

**Wave T.5 — Edge-Case Audit (Codex) [NEW WAVE]**
- Brand new prompt
- Codex review-mode: "find what's missing, find what's weak"
- Input: Wave T test files + source files + ACs + wave-t-summary
- Output: structured gap list OR additional test files
- Prompt style: adversarial reviewer, edge-case hunter

**Wave E — Verification (Claude)**
- Current: `build_wave_e_prompt()`
- Must read WAVE_FINDINGS.json + wave-t-summary + ARCHITECTURE.md
- Must coordinate Playwright test generation
- Prompt style: systematic, evidence-collection-oriented

**Compile-Fix — (Claude? Codex? Design choice)**
- Current: `_build_compile_fix_prompt()` in wave_executor.py
- Phase D added structural triage + iteration context
- Which model should run compile-fix? (Claude for creative solutions? Codex for precise pattern-following?)
- Anti-band-aid block must work for whichever model

**Audit-Fix — (Codex) [NEW ROUTING]**
- Currently Claude; we're moving to Codex
- Rewrite the fix prompt for Codex's style
- Must include: finding details, file locations, codebase context
- Must include anti-band-aid block adapted for Codex
- Codex needs explicit file paths, not vague descriptions
- Prompt style: "here is the bug, here is the file, fix this exact issue"

**Recovery Agents — (model TBD)**
- Current: `_build_recovery_prompt_parts()` in cli.py
- Phase A fixed prompt role isolation (D-05)
- Which model should run recovery? (Same as fix → Codex?)
- Prompt adaptation needed?

**Audit Agents — (Claude)**
- 7 auditor prompts in audit_prompts.py
- Phase C rebalanced scoring categories
- Must reference ARCHITECTURE.md for context
- Do any auditors benefit from Codex's stricter review? (Test auditor?)
- Prompt style: systematic evaluation, structured scoring

**Orchestrator — (Claude)**
- `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` in agents.py
- Post-Phase-E: Python-dispatched, not Task()
- Must understand the NEW architecture (full MCP, interrupt, ARCHITECTURE.md)
- Must coordinate the NEW wave sequence (A, A.5, Scaffold, B, C, D, T, T.5, E, Audit, Fix)

### Per-Prompt Deliverable Format

For EACH prompt:
```
## <Wave/Agent Name> — <Model>

### Current State
- Function: <name> at <file:line>
- Model: <current model>
- Token count: ~<X>
- Known issues: <from build logs + Phase F reviewers>

### Recommended Changes
- Model change: <if any>
- Structural changes: <sections to add/remove/reorder>
- Content changes: <specific wording changes with rationale>
- Context injection changes: <what to add/remove from injected context>

### New Prompt Structure
[The actual prompt text, or a diff against current]

### Rationale
- Research citation: <from MODEL_PROMPTING_RESEARCH.md>
- Build evidence: <from build logs>
- Model-specific optimization: <why this prompt style works for this model>

### Risks
- What could go wrong with this change
- How to validate (test strategy)
```

### Deliverable

`docs/plans/2026-04-17-phase-g-prompt-engineering-design.md` — the complete prompt engineering blueprint.

---

# WAVE 3 — INTEGRATION VERIFICATION

**Agent:** `integration-verifier`
**MCPs:** `context7`, `sequential-thinking`

Reads both design documents. Verifies they're internally consistent and complete.

### Checks

1. **Every wave has a prompt design.** Map wave sequence → prompt design. No gaps.
2. **Every prompt targets the right model.** Cross-reference pipeline design's provider routing with prompt engineering's model assignments.
3. **New waves (A.5, T.5) have complete designs.** Not just "add a review step" — full prompt, input context, output format, integration point.
4. **ARCHITECTURE.md flows correctly.** Wave A writes it; every subsequent wave reads it; updates don't clobber.
5. **Codex fix routing is coherent.** Fix prompt design targets Codex; pipeline design routes fixes to Codex; transport supports it.
6. **No prompt contradictions.** Wave A instructions don't conflict with Wave B instructions. IMMUTABLE rule consistent across waves.
7. **Feature flag impact.** Which existing flags need updating? Which new flags needed?
8. **Backward compatibility.** Can we feature-flag the entire restructure? What's the rollback strategy?
9. **Cost estimate.** With A.5 + T.5 added, what's the per-milestone cost increase?
10. **Implementation order.** What depends on what? Can changes be landed incrementally?

### Deliverable

`docs/plans/2026-04-17-phase-g-integration-verification.md`

---

# WAVE 4 — REPORT SYNTHESIS

**Agent:** `report-synthesizer`
**MCPs:** `sequential-thinking`

Consolidates ALL findings into the master design document.

### Deliverable

`docs/plans/2026-04-17-phase-g-investigation-report.md` containing:

```
# Phase G — Pipeline Restructure + Prompt Engineering — Investigation Report

## Executive Summary
  - 6 changes designed (5 pipeline + prompt engineering)
  - Key findings from investigation
  - Key decisions from design
  - Implementation estimate

## Part 1: Pipeline Architecture Findings (from 1a)
  - Current wave sequences with file:line
  - Current provider routing
  - Persistent state map
  - Context window usage

## Part 2: Prompt Catalogue (from 1b)
  - Every prompt function documented
  - Build-log behavior evidence
  - Issues per prompt

## Part 3: Model Prompting Research (from 1c)
  - Claude best practices (context7-verified)
  - Codex best practices (context7-verified)
  - Cross-model handoff patterns

## Part 4: Pipeline Restructure Design (from 2a)
  - New wave sequences
  - Provider routing table
  - Wave D merge specification
  - Codex fix routing specification
  - ARCHITECTURE.md specification
  - Wave A.5 specification
  - Wave T.5 specification

## Part 5: Prompt Engineering Design (from 2b)
  - Per-prompt design (all ~15 prompts)
  - Model-specific optimizations
  - Build-evidence-driven changes

## Part 6: Integration Verification (from 3)
  - Consistency checks
  - Feature flag plan
  - Cost estimate
  - Implementation order

## Part 7: Implementation Plan
  - Exact files to modify per change
  - Estimated LOC per change
  - Dependencies and ordering
  - Test strategy
  - Rollback strategy

## Appendix A: Context7 Query Results (verbatim)
## Appendix B: Build Log Evidence Catalogue
## Appendix C: Current Prompt Inventory (complete)
```

---

## PHASE G EXIT CRITERIA

- [ ] Pipeline architecture fully documented with file:line evidence
- [ ] Every existing prompt catalogued with model-specific analysis
- [ ] Context7-verified prompting best practices for Claude AND Codex
- [ ] New wave sequences designed (full_stack, backend_only, frontend_only)
- [ ] Wave D merge fully specified (combined prompt text)
- [ ] Codex fix routing fully specified
- [ ] ARCHITECTURE.md fully specified (content template, creation, updates, injection, size management)
- [ ] CLAUDE.md fully specified (auto-loading verified, content designed, relationship to ARCHITECTURE.md clear)
- [ ] AGENTS.md fully specified (auto-loading verified, content designed, Codex-adapted)
- [ ] Wave A.5 (Codex plan review) fully specified
- [ ] Wave T.5 (Codex edge-case audit) fully specified
- [ ] EVERY prompt rewritten/designed for its target model
- [ ] Integration verification passed (no contradictions)
- [ ] Implementation plan with exact files, LOC, and ordering
- [ ] All 7 design documents produced
- [ ] Master investigation report synthesized
- [ ] ZERO design gaps — every wave, every agent, every prompt accounted for

---

## INVIOLABLE RULES

1. **PLAN MODE ONLY.** Do NOT modify any source files. Read and design only.
2. **Context7 on EVERYTHING.** Claude prompting docs, Codex prompting docs, framework docs, SDK docs. No training-data assumptions.
3. **Sequential-thinking on every design decision.** Especially: Wave D merge, fix routing, new wave designs.
4. **Evidence-driven.** Every prompt change cites either context7 research, build log evidence, or Phase F reviewer findings.
5. **The IMMUTABLE rule wording is LOCKED.** It transfers to the merged Wave D exactly as-is.
6. **The WAVE_T_CORE_PRINCIPLE is LOCKED.** The principle stays; the prompt around it can be optimized.
7. **The anti-band-aid block is LOCKED.** It must work for whichever model runs compile-fix and audit-fix.
8. **Build logs are evidence.** If build-j showed pattern X failing, the prompt must address it.
9. **Every prompt targets ONE model.** No "works for both" compromises — optimize for the specific model.
10. **The investigation report is the implementation contract.** The implementation session will follow it exactly.

---

## WHAT TO DO FIRST

1. **Read** (me, before launching): Phase F comprehensive report + deep investigation report
2. **Run pre-flight.** Confirm 10,636 / 0 / 35.
3. **Create task list** for all 7 agents.
4. **Launch Wave 1** (3 investigators in parallel). Wait for all 3 reports.
5. **HALT POINT.** Review all 3 investigation reports. Authorize Wave 2.
6. **Launch Wave 2** (pipeline designer + prompt engineer in parallel).
7. **HALT POINT.** Review both designs. Authorize Wave 3.
8. **Launch Wave 3** (integration verifier).
9. **Launch Wave 4** (report synthesizer).
10. **Deliver master investigation report → ready for implementation session.**

This is the MOST EXHAUSTIVE investigation in the entire project. 7 agents, 4 waves, 3 investigation tracks, context7 on everything, sequential-thinking on every design decision. The output is the complete blueprint for the final pipeline — every wave, every prompt, every model, every handoff. Perfected.
