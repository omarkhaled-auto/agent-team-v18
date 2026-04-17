# Phase G — Wave 2a — Pipeline Restructure Design

> Repo: `C:\Projects\agent-team-v18-codex` branch `integration-2026-04-15-closeout` HEAD `466c3b9`
> Mode: PLAN ONLY — no source files modified. Only this deliverable was created.
> Scope: five pipeline changes — (1) merge Wave D + D.5 into a single Claude Wave D,
> (2) route fixes to Codex via the existing classifier, (3) introduce
> ARCHITECTURE.md + CLAUDE.md + AGENTS.md, (4) add Wave A.5 (Codex plan review),
> (5) add Wave T.5 (Codex edge-case test audit).
> Primary inputs: `docs/plans/2026-04-17-phase-g-pipeline-findings.md` (Wave 1a),
> `docs/plans/2026-04-17-phase-g-prompt-archaeology.md` (Wave 1b),
> `docs/plans/2026-04-17-phase-g-model-prompting-research.md` (Wave 1c).
> Inviolables: the IMMUTABLE `packages/api-client/*` rule wording is LOCKED and
> carries verbatim into the merged Wave D; the `_ANTI_BAND_AID_FIX_RULES` block
> is LOCKED and carries verbatim into every fix dispatch (Claude or Codex).

---

## Executive Summary

The current pipeline is asymmetric in three load-bearing ways that Wave 1a
surfaced: (A) `v18.codex_transport_mode` is declared but never consumed — the
Phase E app-server transport is unreachable from the production wave loop
(`cli.py:3182`); (B) `_build_options()` never sets `setting_sources=["project"]`,
so every wave-level Claude session runs in filesystem-isolation mode and silently
ignores any `CLAUDE.md` in the generated project (`cli.py:339-450`); (C) fix
dispatch is Claude-only despite `classify_fix_provider()` already being written
and exported — the classifier is imported nowhere in `cli.py`
(`provider_router.py:481-504`).

Phase G proposes a staged restructure that addresses all three in the same slice
and layers the five brief-mandated changes on top. Every new capability lands
behind a feature flag defaulting to **off** so that the production pipeline
keeps running unchanged until each slice has passed its own smoke.

The sequence change is: **A → A.5 (Codex) → Scaffold (python) → B (Codex) → C
(python) → D merged (Claude) → T (Claude) → T.5 (Codex) → E (Claude) → Audit →
Fix (Codex or Claude per classifier)**. This re-routes the one wave that wedged
on orphan-tools in build-j (Wave D body on Codex) to Claude, inserts two cheap
Codex review checkpoints (A.5 before build; T.5 before execute), and gives the
fix loop access to the Codex transport for backend-heavy fixes.

Nine surprises from Wave 1a are addressed explicitly below. The inviolable
rules — IMMUTABLE `packages/api-client/*` wording and the anti-band-aid block
— carry through unchanged.

---

## Part 1: New Wave Sequences (per template)

### 1.1 Proposed sequences

| Template | Current (wave_executor.py:307-311 + _wave_sequence at 395-403) | Proposed (Phase G) |
|---|---|---|
| `full_stack` | A → B → C → D → D5 → T → E | A → **A.5** → Scaffold → B → C → **D (merged)** → T → **T.5** → E |
| `backend_only` | A → B → C → T → E | A → **A.5** → Scaffold → B → C → T → **T.5** → E |
| `frontend_only` | A → D → D5 → T → E | A → Scaffold → **D (merged)** → T → **T.5** → E |

Notes:

- **A.5** is gated by `v18.wave_a5_enabled` (default `False`). When off, the
  sequence collapses to the legacy `A → …` order with zero behavior change.
  Skipped on `frontend_only` by design (Wave A there is scaffold-adjacent; the
  entity/endpoint plan it emits is thin and reviewing it has low ROI).
- **Scaffold** is a rename, not a new LLM wave. It is the existing
  `scaffold_verifier` step (`wave_executor.py:885` / `config.py:845`) promoted
  to always run — no new LLM cost. The dispatch loop already calls it; Phase G
  only lifts the enable default from `False` to `True` and surfaces "Scaffold"
  in the per-milestone log line.
- **D merged** (provider flip from Codex → Claude) is gated by
  `v18.wave_d_merged_enabled` (default `False`). When off, legacy D (Codex) +
  D.5 (Claude) runs unchanged.
- **T.5** is gated by `v18.wave_t5_enabled` (default `False`). When off,
  T → E runs unchanged.

### 1.2 Mapping to `WAVE_SEQUENCES`

The constant at `wave_executor.py:307-311` becomes:

```python
WAVE_SEQUENCES = {
    "full_stack":   ["A", "A5", "Scaffold", "B", "C", "D", "T", "T5", "E"],
    "backend_only": ["A", "A5", "Scaffold", "B", "C", "T", "T5", "E"],
    "frontend_only":["A", "Scaffold", "D", "T", "T5", "E"],
}
```

The post-load mutator `_wave_sequence(template, config)`
(`wave_executor.py:395-403`) is extended to remove `"A5"` / `"T5"` when their
flags are off and to remove `"D5"` (retirement path — see §8). Current D5
removal branch stays in place while `v18.wave_d_merged_enabled` is False; when
True, the merged Wave D body replaces Wave D and Wave D5 is stripped.

### 1.3 Alternatives considered

- **Preserve D/D.5 split, fix the Codex wedge instead.** Rejected: the wedge
  is transport-level (orphan-tool event pairing, fixed by the unreached
  `codex_appserver.py`), not promptable. Even after Surprise A is fixed, Codex
  at `reasoning_effort=high` over a multi-page Wave D prompt continues to
  trigger the same failure mode observed in build-j (Wave 1b §Wave D).
- **Make D.5 optional rather than merging.** Rejected: D.5's `[CODEX OUTPUT
  TOPOGRAPHY]` block (`agents.py:8929-8943`) exists exclusively to coach Claude
  around Codex's layout. If D is Claude, the whole topography section is dead
  weight. Easier to merge.
- **Add A.5 / T.5 as subagents of A / T instead of new wave letters.**
  Rejected: the wave-artifact contract (`wave_executor.py:435-442`) is
  per-wave-letter; threading a sub-result through the same artifact confuses
  audit scorers that read `wave_t_status` (D-11). Separate letter = separate
  artifact = less coupling.

---

## Part 2: Provider Routing Table

| Wave | Provider | Reasoning effort | Source of truth | Rationale (cites) |
|---|---|---|---|---|
| A | Claude | n/a (Claude SDK) | `provider_router.py:30` | Preserved. Wave 1c §5 Wave A — reasoning-heavy, XML-friendly. |
| **A.5** | **Codex** | **`medium`** | NEW `WaveProviderMap.A5 = "codex"` | Plan review → `plan_mode_reasoning_effort=medium` is the documented default (Wave 1c §2.5). Bump to `high` only if eval shows `medium` misses real gaps. |
| Scaffold | Python | n/a | existing `scaffold_verifier_enabled` promoted | No LLM; no cost. |
| B | Codex | `high` | `provider_router.py:31` + `config.py:815` | Preserved. Integration wiring is Codex's turf (Wave 1a Part 2). |
| C | Python | n/a | `provider_router.py:32` + `wave_executor.py:2646` | Preserved. OpenAPI generator; no LLM. |
| **D (merged)** | **Claude** | n/a | `provider_router.py:33` flips from `"codex"` → `"claude"` under flag; D5 alias retires | **PROVIDER FLIP.** Wave 1b §Wave D records the build-j orphan-tool wedge on Codex Wave D; Wave 1c §5 Wave D recommends Claude for the review/polish side. Merged body keeps Codex's manifest/IMMUTABLE rules in Claude-styled rules blocks. |
| T | Claude | n/a | `wave_executor.py:3243-3260` (hard-bypass) | Preserved. Intentional, documented (Surprise D). |
| **T.5** | **Codex** | **`high`** | NEW `WaveProviderMap.T5 = "codex"` | Gap-detection benefits from reasoning depth; Wave 1c §5 Wave T.5. |
| E | Claude | n/a | `provider_router.py:35` | Preserved. |
| Audit | Claude | n/a | existing `_run_milestone_audit` | Preserved. |
| **Fix** | **routed per classifier** | `high` (Codex) / n/a (Claude) | NEW: consume `classify_fix_provider()` at `cli.py:6441` (patch mode) | Wave 1a Part 3 — `classify_fix_provider` exists at `provider_router.py:481-504`, exported, never called. Wiring it at `cli.py:6441` routes backend-heavy fixes to Codex with the same transport as Wave B. |

### 2.1 Routing dataclass change

`provider_router.py:27-42` — add A5 + T5 fields:

```python
@dataclass
class WaveProviderMap:
    A: str = "claude"
    A5: str = "codex"      # NEW — Codex plan reviewer
    B: str = "codex"
    C: str = "python"
    D: str = "claude"      # FLIP when v18.wave_d_merged_enabled is True; legacy "codex" otherwise
    D5: str = "claude"     # retained for legacy path; unused when merged
    T: str = "claude"
    T5: str = "codex"      # NEW — Codex edge-case auditor
    E: str = "claude"
```

And the `provider_for` method (`provider_router.py:37-42`) keeps the D5/UI
alias-to-Claude guard; adds no new aliases. The D flip is applied in
`cli.py:3184-3187` where `WaveProviderMap` is constructed:

```python
provider_map = WaveProviderMap(
    B=getattr(v18, "provider_map_b", "codex"),
    D=("claude" if getattr(v18, "wave_d_merged_enabled", False)
       else getattr(v18, "provider_map_d", "codex")),
    A5=getattr(v18, "provider_map_a5", "codex"),
    T5=getattr(v18, "provider_map_t5", "codex"),
)
```

---

## Part 3: Wave D Merge Design (Wave D + Wave D.5 → single Claude Wave D)

### 3.1 What to keep from current Wave D (Codex body)

From `build_wave_d_prompt()` at `agents.py:8696-8858`:

- `[GENERATED API CLIENT]` manifest — mandates imports from
  `packages/api-client/index.ts` / `types.ts`. **KEEP verbatim.**
- `[CODEBASE CONTEXT]` — layout/UI/page/form/table/modal examples
  (`agents.py:8761-8773`). **KEEP.**
- `[STATE COMPLETENESS]` (`agents.py:8800-8852`). **KEEP.**
- `[I18N REQUIREMENTS]` + `[RTL REQUIREMENTS]`. **KEEP.**
- `[RULES]` — in particular the IMMUTABLE rule at `agents.py:8803`:
  > *IMMUTABLE: Zero edits to `packages/api-client/*` — that directory is the
  > Wave C deliverable and is immutable.*
  **KEEP verbatim (LOCKED per brief).**
- `[VERIFICATION CHECKLIST]` — trim to Claude-appropriate entries; drop the
  apply_patch-specific bullets that were Codex-only.
- `[FILES YOU OWN]` (N-02 ownership claim). **KEEP.**
- `[CURRENT FRAMEWORK IDIOMS]` MCP doc injection (`agents.py:8734-8741`).
  **KEEP** — Claude benefits from context7 idioms as much as Codex.

### 3.2 What to keep from current Wave D.5 (Claude body)

From `build_wave_d5_prompt()` at `agents.py:8860-9015`:

- `[APP CONTEXT]` via `_infer_app_design_context(ir)` (`agents.py:8907`).
  **KEEP.**
- `[DESIGN SYSTEM]` / `[DESIGN STANCE]` (`agents.py:8910-8916`). **KEEP.**
- `[PRESERVE FOR WAVE T AND WAVE E]` (`agents.py:8945-8956`) — do NOT
  remove/rename data-testid, aria-label, aria-labelledby, role, form
  name/id, href, type, onClick. **KEEP, renamed to
  `[TEST ANCHOR CONTRACT — preserved for Wave T / E]`.**
- `[YOU CAN DO]` list (`agents.py:8961-8969`). **KEEP.**
- `[PROCESS]` + `[VERIFICATION CHECKLIST]` (`agents.py:8987-9011`) —
  merged with D's verification list, deduplicated.
- `[CODEX OUTPUT TOPOGRAPHY]` (`agents.py:8929-8943`) — **RENAME** to
  `[EXPECTED FILE LAYOUT]` (Codex is no longer producing the files;
  the layout convention remains useful for Claude's own consistency).

### 3.3 What to DROP

- `CODEX_WAVE_D_PREAMBLE` (`codex_prompts.py:180-242`) — wholly.
  - Autonomy / persistence / "no confirmation" directives (Wave 1c §1.7:
    Claude iterates well without them; repeated rules trigger over-rigid
    compliance).
  - Codex-specific citation ban (`【F:path†Lx-Ly】`) — irrelevant to Claude.
  - `apply_patch` relative-path reminders — Claude uses Edit/Write tools.
- `CODEX_WAVE_D_SUFFIX` (`codex_prompts.py:220-242`) — fold the IMMUTABLE
  `packages/api-client` reiteration into the main rules block (it already
  appears at `agents.py:8803`; removing the duplicate saves ~400 tokens).
- Wave D.5's `[YOU MUST NOT DO]` narrow restriction (`agents.py:8971-8985`)
  — the restriction existed because D.5 was polishing Codex-owned code and
  must not break Codex's logic. In the merged wave, Claude OWNS both
  functional and visual; `[YOU MUST NOT DO]` is replaced with a shorter
  `[RULES — KEEP FUNCTIONAL CONTRACTS]` block covering only the test anchor
  contract + IMMUTABLE rule (both inherited from §3.1–3.2).

### 3.4 New compile-check strategy

Current:

- Wave D compile gate at `wave_executor.py:3295-3305` → fail the wave on
  compile-fail, no rollback.
- Wave D.5 compile gate at `wave_executor.py:3357-3375` → rollback on
  compile-fail (uses `snapshot_for_rollback` at `provider_router.py:44-57`).

Merged Wave D:

1. Run merged Wave D.
2. Run post-wave compile check (same guard as today).
3. If compile fails:
   a. Run compile-fix iteration (new `_run_wave_d_compile_fix` helper,
      modeled on `_run_wave_b_dto_contract_guard` at
      `wave_executor.py:2888`). Max attempts:
      `v18.wave_d_compile_fix_max_attempts` default **2**.
   b. If compile-fix converges: emit success + surface per-attempt costs.
   c. If compile-fix exhausts: rollback via `rollback_from_snapshot`
      (`provider_router.py:60-99`) and fail the wave.
4. Run the D5-specific guard checks (frontend-hallucination guard at
   `wave_executor.py:2997`) — these are provider-agnostic and already exist.

This is strictly stronger than either current D or current D.5:
- vs. current D: adds rollback as a last resort.
- vs. current D.5: adds a compile-fix stage before rollback, so a single typo
  doesn't blow away the whole wave.

### 3.5 Config changes

Add to `config.py` V18Config dataclass (near `wave_d5_enabled` at line 791):

```python
wave_d_merged_enabled: bool = False          # Phase G
wave_d_compile_fix_max_attempts: int = 2     # Phase G
# retained until sunset:
wave_d5_enabled: bool = True                 # ignored when wave_d_merged_enabled=True
```

When `wave_d_merged_enabled=True`, `_wave_sequence()` strips D5 regardless of
`wave_d5_enabled`.

### 3.6 Prompt builder change (agents.py)

- NEW function `build_wave_d_merged_prompt(...)` at `agents.py:~8696` (or
  extend `build_wave_d_prompt` with a `merged: bool = False` kwarg that
  selects the merged body; latter is lower-churn).
- Dispatcher in `build_wave_prompt()` at `agents.py:9018` — gate on
  `config.wave_d_merged_enabled` to select merged vs. legacy.

Estimated prompt size: ~9–14 K tokens (vs. legacy D ~10–20 K + legacy D5
~6–10 K = 16–30 K across the two-wave pair). The merged prompt is smaller
than the sum because it drops the D5 `[CODEX OUTPUT TOPOGRAPHY]` motivation
paragraph + D5 `[YOU MUST NOT DO]` narrow restriction + Codex preamble.

---

## Part 4: Codex Fix Routing Design

### 4.1 Entry points to modify

1. **Patch mode** at `cli.py:6271-6506` (`_run_audit_fix_unified` →
   `_run_patch_fixes` at `cli.py:6385-6449`).
2. **Full-build mode** at `cli.py:6451-6489` (`_run_full_build`) — spawns a
   subprocess re-running the whole builder. No change needed here: the child
   process inherits `v18.provider_routing` and will route its own waves
   accordingly. The Codex fix routing is a patch-mode feature.

### 4.2 Wiring the classifier (cli.py:6441)

Today (`cli.py:6441`):

```python
async with ClaudeSDKClient(options=options) as client:
    await client.query(fix_prompt)
    cost = await _process_response(client, config, phase_costs)
```

Phase G change: before the `async with ClaudeSDKClient` block, call
`classify_fix_provider` and branch:

```python
from .provider_router import classify_fix_provider

fix_provider = "claude"  # default preserves current behavior
if getattr(v18, "codex_fix_routing_enabled", False) and _provider_routing:
    fix_provider = classify_fix_provider(
        affected_files=target_files,
        issue_type=feature_name,
    )

if fix_provider == "codex" and _provider_routing:
    # Wrap for Codex and dispatch via _provider_routing["codex_transport"]
    codex_fix_prompt = wrap_fix_prompt_for_codex(fix_prompt)
    cost = await _dispatch_codex_fix(
        codex_fix_prompt,
        cwd=str(cwd),
        codex_config=_provider_routing["codex_config"],
        codex_home=_provider_routing["codex_home"],
        codex_transport=_provider_routing["codex_transport"],
        timeout_seconds=getattr(v18, "codex_fix_timeout_seconds", 900),
    )
else:
    async with ClaudeSDKClient(options=options) as client:
        await client.query(fix_prompt)
        cost = await _process_response(client, config, phase_costs)
```

On Codex failure or "success but no file changes", fall back to the Claude
branch (mirror of wave logic at `provider_router.py:378-393`).

### 4.3 Addressing Surprise A (transport selector)

This is the single most load-bearing code change in Phase G. Without it, even
the existing Wave B/D Codex routing runs on the legacy transport and the fix
path inherits the same problem. `cli.py:3182` today:

```python
import agent_team_v15.codex_transport as _codex_mod
```

Phase G replacement (minimal `importlib` with feature-flag default preserving
current behavior):

```python
transport_mode = getattr(v18, "codex_transport_mode", "exec")
if transport_mode == "app-server":
    import agent_team_v15.codex_appserver as _codex_mod
else:
    import agent_team_v15.codex_transport as _codex_mod
```

Both modules expose the same `execute_codex(prompt, cwd, config, codex_home,
progress_callback)` signature (`codex_appserver.py:634-693`), so
`provider_router._execute_codex_wave()` works with either. The app-server
path enables `turn/interrupt` on orphan-tool wedge per context7 verbatim:

> *"Call `turn/interrupt` to request cancellation of a running turn. The
> server will then emit a `turn/completed` event with
> `status: "interrupted"`."* (`/openai/codex` —
> `codex-rs/app-server/README.md`)

### 4.4 Fix prompt restructuring (Codex style)

The existing fix prompt at `cli.py:6417-6429` is Claude-styled (brackets,
long explanation). For Codex, Wave 1c §5 Fix recommends a short `<rules>`
block + `<missing_context_gating>` + flat errors. New helper
`wrap_fix_prompt_for_codex(fix_prompt: str) -> str`:

```
You are a compile-fix agent. Fix the findings below with the MINIMUM change per file.

<rules>
- Fix ONLY the listed findings. Do not refactor.
- Root-cause fixes only; do not wrap the error in try/except to silence it.
- Relative paths in apply_patch. No absolute paths.
- Preserve all [TEST ANCHOR CONTRACT] data-testid/aria-label/role values.
- IMMUTABLE: zero edits to packages/api-client/*.
</rules>

<missing_context_gating>
- If a fix would require guessing at intent, label the assumption and pick
  the reversible option.
- If context is retrievable, retrieve before guessing.
</missing_context_gating>

<anti_band_aid>
{_ANTI_BAND_AID_FIX_RULES}
</anti_band_aid>

<feature>
{feature_block}
</feature>

<original_prd>
{task_text}
</original_prd>

After fixing, return JSON: {fixed:[...], still_failing:[...]}.
```

The `_ANTI_BAND_AID_FIX_RULES` constant carries in verbatim (LOCKED per
brief). `task_text` (whole PRD) stays inlined — Codex 1M context supports
this per Wave 1c §1.5, and Surprise H notes the repeated inlining is cheap
under 1M.

### 4.5 Anti-band-aid block adaptation

The LOCKED block appears once per fix dispatch — no changes. Codex-specific
adaptation is wrapping it in `<anti_band_aid>...</anti_band_aid>` tags
(Codex parses these as neutral delimiters per Wave 1c §3.3).

### 4.6 Fix iteration shape

- **Patch mode (narrow scope):** **one-shot per feature.** Codex's
  `execute_codex()` runs one turn per call (`codex_transport.py:687`).
  Existing code treats each feature as an independent try; keep that shape.
  Multi-turn dialogue would require threading the Codex thread state
  through `_run_patch_fixes`, which the existing Claude branch also doesn't
  do. Not worth the complexity increase.
- **Full-build mode:** unchanged (subprocess-spawned builder, own pipeline).

### 4.7 Timeout estimate

- Wave B (full-build backend) uses 5400s (`config.py:808`).
- A patch-mode fix typically touches 1–3 files, no new entities, no full
  compile. Observed fix durations in build-j / build-h: ~2–6 minutes.
- **Recommendation:** `v18.codex_fix_timeout_seconds: int = 900` (15 min).
  This gives 2.5× headroom over observed and is 1/6 of wave timeout.
- For full mode (already a subprocess escalation), keep existing 14400s at
  `cli.py:6480` — unchanged.

### 4.8 Config changes

```python
# config.py V18Config:
codex_fix_routing_enabled: bool = False          # Phase G
codex_fix_timeout_seconds: int = 900             # Phase G
codex_fix_reasoning_effort: str = "high"         # Phase G
```

---

## Part 5a: ARCHITECTURE.md Design (project-level, dynamic)

### 5a.1 Role

A builder-written living document that accumulates architectural decisions
across milestones. Distinct from CLAUDE.md / AGENTS.md in two ways:

- **Dynamic** (grows per milestone) vs. **static** (stable across run).
- **Read by the builder itself** vs. **auto-loaded by the CLI/SDK**.

Wave 1a Part 4 documents the gap: "no project-level architecture document
that persists across milestones". `resolved_manifest.json` is per-milestone
only (`milestone_spec_reconciler.py:196-199`); `ARCHITECTURE_REPORT.md` at
repo root is hand-written (51 KB) not builder-generated.

### 5a.2 Content template

Structured markdown with one section appended per milestone:

```markdown
# Architecture — <project name>

> Auto-maintained by V18 builder. Human edits outside `## Manual notes` will
> be overwritten.

## Summary
- Stack: <fe>/<be>/<db> (from stack_contract)
- Milestones completed: <n>
- Last update: <iso-timestamp>

## Entities (cumulative)
| Name | First milestone | Current fields (count) | Relations |
|------|-----------------|------------------------|-----------|
| User | M1              | 7                      | 1:N Task  |
| Task | M1              | 12                     | N:1 User  |

## Endpoints (cumulative)
| Path                    | Method | Owner milestone | DTO |
|-------------------------|--------|-----------------|-----|
| /api/v1/users           | GET    | M1              | UserListResponse |

## Milestone M1 — <title> (2026-04-17)
### Decisions
- Adopted Prisma 5.x with `@@index` on `deletedAt` for soft-delete.
- JWT auth via Passport, sessions stored in HttpOnly cookies.
### New entities
- User, Task
### New endpoints
- GET/POST /api/v1/users; GET/POST /api/v1/tasks
### Known limitations
- Pagination not yet implemented; tracked as M3 AC.

## Milestone M2 — <title> (YYYY-MM-DD)
...

## Manual notes
<free-form human section; never overwritten>
```

### 5a.3 Who creates it

- **Created by a new Python-side helper** `architecture_writer.init_if_missing(cwd)`
  invoked from `execute_milestone_waves()` at `wave_executor.py:~3150` (before
  milestone M1 dispatch). Writes the `# Architecture …` header + empty `##
  Manual notes` block if no file exists.

### 5a.4 Who updates it

- **Updated at end of each milestone** by new Python-side helper
  `architecture_writer.append_milestone(milestone_id, wave_artifacts, cwd)`
  invoked alongside `persist_wave_findings_for_audit()` at
  `wave_executor.py:~3542-3548`. Extracts:
  - Entities from `wave_artifacts["A"]` (schema output)
  - Endpoints from `wave_artifacts["B"]` (controllers)
  - Decisions from the structured `decisions[]` array that a new
    post-Wave-E Python summarizer emits (python-only, no LLM; just pattern
    matching over the milestone's REQUIREMENTS.md + wave artifacts).

Rationale for python-over-LLM updating: Wave 1a §Part 4 notes Wave A's
prompt already has known issues (migration creation) — adding a write-to-ARCHITECTURE.md
instruction risks further dilution. Python-side extraction is deterministic,
cheap, and never drifts.

### 5a.5 How injected into wave prompts

Every wave prompt for milestone M2+ receives a new `[PROJECT ARCHITECTURE]`
block near the top of the prompt (Claude: position documents FIRST per
Wave 1c §1.5). Inject via `existing_prompt_framework` augmentation in the
prompt builders. Summarized if over `v18.architecture_md_max_lines`
(default **500**); summarization is python-side (drop earliest milestone
sections and replace with a one-paragraph rollup).

### 5a.6 Size management

- Grows ~50–100 lines per milestone.
- At 500 lines, python-side summarizer collapses the earliest N milestones
  into a rollup (`## Milestones 1–5 (rolled up)` with cumulative entities
  and endpoints preserved in full; decisions collapsed to one-line summary).
- Hard cap 2000 lines — beyond that, the file is split at
  `ARCHITECTURE_HISTORY.md` (older rollups moved over) and the live
  ARCHITECTURE.md retains the last N milestones.

### 5a.7 File path

`<generated-project-cwd>/ARCHITECTURE.md` — repo root of the generated
project, alongside `README.md`.

### 5a.8 Config

```python
architecture_md_enabled: bool = False            # Phase G
architecture_md_max_lines: int = 500             # Phase G
architecture_md_summarize_floor: int = 5         # keep last N milestones in full
```

### 5a.9 Cost

Zero LLM cost — python-only extractor + formatter. Per-milestone overhead
~50 ms.

---

## Part 5b: CLAUDE.md Design (CLI-level static constitution for Claude)

### 5b.1 Role

Auto-loaded by the Claude Agent SDK at session start — **IF** the SDK
caller opts in via `setting_sources=["project"]`. The builder today does
not opt in (Wave 1a Surprise B / §8). A CLAUDE.md without the opt-in is
inert.

### 5b.2 The required code change — addressing Surprise B

`_build_options()` at `cli.py:339-450` constructs `ClaudeAgentOptions` with
no `setting_sources` field (`cli.py:427-444`). Phase G change — add to
`opts_kwargs`:

```python
# Phase G: enable CLAUDE.md auto-load for generated-project sessions
if getattr(config.v18, "claude_md_setting_sources_enabled", False) and cwd:
    opts_kwargs["setting_sources"] = ["project"]
```

Important: **do NOT** switch `system_prompt` to
`{"type": "preset", "preset": "claude_code"}` — that would replace the
builder's hand-built orchestrator framing (`cli.py:390-408`) which carries
D-05's prompt-injection-isolation fix. Wave 1c §4.1 confirms the SDK
delivers CLAUDE.md as a user-turn message AFTER the system prompt, so the
hand-built system prompt + CLAUDE.md-as-user-turn composes cleanly. No
system-channel replacement required.

Citation (Wave 1a Appendix B, Query 2):

> ```python
> options = ClaudeAgentOptions(
>     system_prompt={"type": "preset", "preset": "claude_code"},
>     setting_sources=["project"],
>     allowed_tools=["Read", "Write", "Edit"],
> )
> ```

The context7 snippet shows both set together. Phase G sets only
`setting_sources`, which is supported — the `system_prompt` field is
orthogonal per Wave 1c §4.1 ("setting_sources controls filesystem loading;
system_prompt controls the system channel").

### 5b.3 Content template

~150 lines, well under the 200-line adherence guideline
(Wave 1c §4.3). Structure:

```markdown
# Claude Code — Project Instructions

## Project Overview
<one paragraph; source-of-truth is ARCHITECTURE.md — this block is static>

## Stack & conventions
- Backend: NestJS 11 + Prisma 5 + PostgreSQL 16
- Frontend: Next.js 15 (app router) + Tailwind 4 + shadcn/ui
- API contract: OpenAPI-generated at `packages/api-client/`
- Tests: Jest (api), Playwright (web)

## Coding standards
- TypeScript strict mode; no `any` without a comment explaining why.
- ESM imports only; relative paths avoided — use `@/` aliases.
- Functions under 80 lines; files under 500 lines.
- Error handling: throw typed errors; never swallow without logging.
- DTOs in `apps/api/src/**/dto/*.dto.ts`; always use class-validator.

## TDD rules
- Every new endpoint → one integration test under `apps/api/test/`.
- Every new page → one Playwright spec under `apps/web/e2e/`.
- No merged changes without passing tests.

## Commands
- `pnpm install`       — install deps
- `pnpm build`         — full build
- `pnpm test`          — run all tests
- `pnpm lint:fix`      — autofix ESLint
- `docker compose up`  — start local services

## Forbidden patterns
- Never edit `packages/api-client/*` — it is Wave C generated output.
- Never create `.env` files; use `.env.example` + `process.env` at runtime.
- Never add a new framework dep without updating ARCHITECTURE.md.
- Never use `console.log` in production paths; use the `logger` module.

## Naming conventions
- Entities: PascalCase singular (`User`, `Task`, not `Users`, `Tasks`).
- Services: `<Entity>Service` in `apps/api/src/<entity>/`.
- Controllers: `<Entity>Controller` in the same folder.
- React components: PascalCase; hooks `useCamelCase`.
```

### 5b.3a A note on pipeline routing rules

The brief lists "pipeline routing rules" as a CLAUDE.md content item. Phase G
recommends **keeping those OUT of CLAUDE.md**. Reasons:

- Pipeline routing is a *builder*-side concept (which wave runs which model);
  it is not relevant to the Claude session running inside a wave, which only
  sees its own task.
- Putting routing rules into CLAUDE.md causes every wave-level Claude session
  to waste context on them and potentially second-guess its own provider
  (Wave 1c §4.4: "Don't duplicate into the system prompt").
- Pipeline routing rules belong in the builder's own `CLAUDE.md` at the
  builder repo root (if anyone runs Claude Code against this repo directly,
  which is a separate dev-session use case not in Phase G scope) — or in
  `ARCHITECTURE.md` of the builder (also out of scope).

### 5b.4 File path

`<generated-project-cwd>/CLAUDE.md` — repo root of the generated project.
Relationship to ARCHITECTURE.md: both live at repo root. CLAUDE.md is
static (stack conventions, commands, forbidden patterns); ARCHITECTURE.md
is dynamic (milestone-by-milestone decisions, entities, endpoints).
CLAUDE.md has a one-line pointer: `> Project architecture details live in
./ARCHITECTURE.md.` Human devs read both; the SDK only auto-loads
CLAUDE.md.

### 5b.5 Who writes it

New python helper `constitution_writer.write_claude_md(cwd, stack)` called
once at pipeline-start (before milestone M1 dispatch). Content is rendered
from a `constitution_templates.py` module with:

```python
COMMON_STACK_RULES = [
    "Backend: NestJS 11 + Prisma 5",
    "Never edit packages/api-client/*",
    ...
]

def render_claude_md(stack: dict) -> str: ...
def render_agents_md(stack: dict) -> str: ...
```

Single source of truth (`COMMON_STACK_RULES`); two renderers for the two
different syntactic styles (XML-friendly for Claude, flat markdown for
Codex — see §5c.5).

### 5b.6 Config

```python
claude_md_setting_sources_enabled: bool = False  # Phase G; ~Surprise B fix
claude_md_autogenerate: bool = False              # Phase G; write CLAUDE.md at M1
```

### 5b.7 Size

Target <200 lines (Wave 1c §4.3 adherence guideline). Expected ~150 lines.

---

## Part 5c: AGENTS.md Design (Codex CLI constitution)

### 5c.1 Role

Codex **auto-loads** `AGENTS.md` from the generated-project cwd and all
ancestors — no SDK opt-in required (Wave 1a §8, Wave 1c §4.2). The file is
prepended to the developer message.

Citation (Wave 1a Appendix B, Query 3):

> *"The contents of the `AGENTS.md` file at the root of the repo and any
> directories from the Current Working Directory (CWD) up to the root are
> automatically included with the developer message, eliminating the need
> for re-reading."* (`/openai/codex` — `codex-rs/core/gpt_5_1_prompt.md`)

### 5c.2 Content template

Codex-friendly flat markdown (Wave 1c §2.7):

```markdown
# AGENTS.md — <project name>

## Project Overview
<one paragraph>

## Code Style
- TypeScript strict mode.
- 2-space indent, 100-column soft limit.
- No inline comments unless the PR description asks for one.
- ESM imports; no CommonJS.
- Relative paths in apply_patch only.

## Testing
- `pnpm test` runs Jest + Playwright.
- Coverage: minimum 80% on changed files.
- Every new endpoint needs an integration test.

## Database
- Prisma 5 with PostgreSQL 16.
- Migrations via `prisma migrate dev --name <slug>`.
- Never edit a committed migration; create a new one.

## Important Files
- `packages/api-client/` — Wave C generated; immutable.
- `apps/api/src/app.module.ts` — root NestJS module; add new modules here.
- `apps/web/src/app/` — Next.js app router; routes mirror URL paths.
- `ARCHITECTURE.md` — dynamic architectural record; read before adding
  new entities.

## Do Not
- Do not `git commit` or create new branches.
- Do not edit `packages/api-client/*`.
- Do not add copyright headers.
- Do not inline-comment code; put rationale in commit message.
- Do not guess at intent — retrieve first, ask second, guess last.
```

### 5c.3 File path(s)

**Recommendation:** single top-level `<generated-project-cwd>/AGENTS.md`.
Expected size ~4–6 KiB, well under the 32 KiB hard cap (Wave 1c §4.3). Do
NOT ship per-subdirectory AGENTS.md initially — nested-wins precedence is
useful but adds maintenance cost; only split if the top-level AGENTS.md
grows past 16 KiB (half-cap heuristic).

### 5c.4 Builder-side vs. generated-project-side

Decision: **generated-project-side only.**

- Builder cwd AGENTS.md would be read by Codex sessions run against the
  builder itself, which is a dev-session use case outside Phase G scope.
- Generated-project cwd is what the wave's Codex call sees (`cwd=<generated
  project>` passed into `_execute_codex_wave` at `provider_router.py:240-423`).
- Splitting into two files doubles the drift surface with no benefit.

### 5c.5 Relationship to CLAUDE.md — single source of truth

Both files encode the same stack conventions, coding standards, forbidden
patterns, and commands. They differ only in **style**: CLAUDE.md uses
prose + bullets (Claude reads prose well); AGENTS.md uses flat section
headers + bullets (Wave 1c §2.1 — Codex prefers minimal scaffolding).

Single-source strategy (preferred):

- `constitution_templates.py` defines `COMMON_STACK_RULES`,
  `COMMON_FORBIDDEN`, `COMMON_COMMANDS` as neutral data.
- `render_claude_md(stack, rules, forbidden, commands)` returns the
  Claude-styled markdown.
- `render_agents_md(stack, rules, forbidden, commands)` returns the
  Codex-styled markdown.
- Both functions emit files at M1 startup under
  `v18.claude_md_autogenerate=True` and
  `v18.agents_md_autogenerate=True`.

Sync verification: a python-side test can diff the rendered outputs against
a frozen golden; any drift surfaces in CI.

### 5c.6 Config

```python
agents_md_autogenerate: bool = False             # Phase G
agents_md_max_bytes: int = 32768                 # soft guard; warn if exceeded
```

Note: Codex's own `project_doc_max_bytes` override (Wave 1c §4.3) is a
Codex config.toml setting, not a builder setting. If V18's AGENTS.md grows
past 32 KiB (unlikely for our template), ship a `.codex/config.toml`
snippet under the generated project with `project_doc_max_bytes = 65536`.

### 5c.7 Cost

Zero LLM cost — both files are python-rendered. Per-run overhead ~20 ms.

---

## Part 6: Wave A.5 — Codex Plan Review (new)

### 6.1 Purpose

Catch entity/endpoint/state-machine gaps in Wave A's output BEFORE Wave B
writes backend code against a flawed plan. Fixing plan errors after Wave B
is 3–10× more expensive (re-run of Wave B + recompile + retest per build-j
history).

### 6.2 Input context

- Wave A output (`wave_artifacts["A"]` per `wave_executor.py:3423-3429`)
- Milestone `REQUIREMENTS.md`
- `ARCHITECTURE.md` (if present) — previous milestones' decisions for
  consistency checking
- Stack contract (`wave_executor.py:3170-3180`)

### 6.3 Prompt skeleton (Codex-style per Wave 1c §5 Wave A.5)

```
You are a strict plan reviewer. You flag gaps; you do not write new plans.

<rules>
- Emit findings ONLY for:
  (a) missing endpoints implied by ACs but not in the plan,
  (b) wrong entity relationships,
  (c) state-machine gaps (status transitions),
  (d) unrealistic scope for one milestone,
  (e) PRD/requirements contradictions.
- Every finding cites a file or plan-section reference.
- Relative paths only.
- If the plan is consistent with the PRD, return
  {"verdict":"PASS","findings":[]}.
</rules>

<missing_context_gating>
- If you would need to guess at intent, return a finding labelled UNCERTAIN
  with the assumption you would have made.
</missing_context_gating>

<architecture>
{architecture_md_content or "(none — this is milestone M1)"}
</architecture>

<plan>
{wave_a_plan_text}
</plan>

<requirements>
{milestone_requirements_md}
</requirements>

Return JSON matching output_schema:
{verdict, findings[{category, severity, ref, issue, suggested_fix}]}.
```

### 6.4 Output format

JSON via Codex `output_schema` (Wave 1c §2.4):

```json
{
  "verdict": "PASS" | "FAIL" | "UNCERTAIN",
  "findings": [
    {
      "category": "missing_endpoint" | "wrong_relationship" | "state_machine_gap" | "scope_too_large" | "prd_contradiction" | "uncertain",
      "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW",
      "ref": "<plan section or file path>",
      "issue": "<prose>",
      "suggested_fix": "<prose>"
    }
  ]
}
```

### 6.5 Integration in the orchestrator

Hybrid gating (cli.py, called from `execute_milestone_waves` at
`wave_executor.py:~3250` before Wave B dispatch):

1. If `v18.wave_a5_enabled=True` and not skipped (§6.6):
   1. Call new `_execute_wave_a5(plan, requirements, architecture, config)`
      — dispatches a Codex turn via `_provider_routing["codex_transport"]`.
   2. Persist findings to `.agent-team/milestones/{id}/WAVE_A5_REVIEW.json`.
2. If `verdict == "FAIL"` AND any `severity == "CRITICAL"`:
   - Re-run Wave A with findings attached as a `[PLAN REVIEW FEEDBACK]`
     section. Max 1 re-run (`v18.wave_a5_max_reruns = 1` default).
3. HIGH/MEDIUM/LOW findings + UNCERTAIN:
   - Proceed to Wave B with findings attached as a non-blocking `[PLAN
     REVIEW NOTES]` context block in the Wave B prompt.
4. On `verdict == "PASS"` or `verdict == "UNCERTAIN"` with no CRITICAL:
   - Proceed without re-run.

### 6.6 Skip conditions

Auto-skipped (no LLM call) when any of:

- `v18.wave_a5_enabled=False` (default).
- Template is `frontend_only` (scaffold-adjacent A has low-ROI review).
- Milestone has ≤3 entities AND ≤5 ACs (cheap simple milestones).
- Milestone is flagged `complexity: simple` in `MASTER_PLAN.json`
  (decomposer assigns; optional field).

### 6.7 Cost estimate

- Codex `reasoning_effort=medium`, ~1.5K prompt tokens, ~800 output tokens.
- Per OpenAI Codex model pricing (Wave 1c §2.5): ~$0.10–$0.30 per
  invocation.
- Per milestone: 1 invocation nominally; +1 if rerun triggered (max 2).
- Budget for a typical full_stack 8-milestone run: ~$1.50–$5.00.

### 6.8 Implementation — which function

- New function `_execute_wave_a5()` in `cli.py` (sibling of
  `_execute_single_wave_sdk` at `cli.py:3908`).
- Integration hook in `wave_executor.py:~3250` (before the existing Wave B
  dispatch block, after Wave A completes).
- Feeds into existing `_wave_sequence` logic at
  `wave_executor.py:395-403` — extend to respect `A5` in the sequence list
  and gate on `v18.wave_a5_enabled`.

### 6.9 Config

```python
wave_a5_enabled: bool = False
wave_a5_reasoning_effort: str = "medium"
wave_a5_max_reruns: int = 1
wave_a5_skip_simple_milestones: bool = True
wave_a5_simple_entity_threshold: int = 3
wave_a5_simple_ac_threshold: int = 5
```

---

## Part 7: Wave T.5 — Codex Edge-Case Test Audit (new)

### 7.1 Purpose

Catch test gaps — missing edge cases, weak assertions, untested business
rules — BEFORE Wave E runs the tests. The output is a list of GAPS, not a
list of new tests. Wave T's existing fix loop then writes tests that
address the gaps.

### 7.2 Input

- Wave T test files (`wave_artifacts["T"]` or equivalent file list)
- Source files referenced by those tests
- Milestone acceptance criteria
- `WAVE_FINDINGS.json` fragment for Wave T (from
  `wave_executor.persist_wave_findings_for_audit` at `wave_executor.py:609-681`)

### 7.3 Prompt skeleton (Codex-style per Wave 1c §5 Wave T.5)

```
You are a test-gap auditor. You find missing edge cases in existing tests.
You do NOT write new tests — you describe what is missing.

<rules>
- For each test file, identify: (a) missing edge cases, (b) weak
  assertions, (c) untested business rules from the ACs.
- Every gap cites {test_file, source_symbol, ac_id}.
- Do not propose test code. Describe the assertion in prose.
- Relative paths only.
</rules>

<tool_persistence_rules>
- Read the source file referenced by each test before concluding.
- Read the ACs before flagging "missing business rule".
- Do not stop on the first gap; scan every test.
</tool_persistence_rules>

<tests>
{test_files}
</tests>

<source>
{source_files}
</source>

<acs>
{acceptance_criteria}
</acs>

Return JSON matching output_schema:
{ gaps: [{test_file, source_symbol, ac_id, missing_case, severity,
          suggested_assertion}] }
```

### 7.4 Output format

JSON via Codex `output_schema`:

```json
{
  "gaps": [
    {
      "test_file": "apps/api/test/users.e2e-spec.ts",
      "source_symbol": "UsersService.createUser",
      "ac_id": "AC-012",
      "missing_case": "Duplicate email rejection",
      "severity": "HIGH",
      "suggested_assertion": "Expect 409 CONFLICT when POST /users fires twice with same email"
    }
  ]
}
```

### 7.5 Integration point

Inserted between Wave T completion and Wave E dispatch in the dispatch
loop at `wave_executor.py:~3260` (immediately after the `_execute_wave_t`
return):

1. If `v18.wave_t5_enabled=True` AND Wave T produced ≥1 test file:
   1. Call new `_execute_wave_t5(test_files, source_files, acs, config)`
      — dispatches a Codex turn via `_provider_routing["codex_transport"]`.
   2. Persist gaps to `.agent-team/milestones/{id}/WAVE_T5_GAPS.json`.
2. If `gaps` non-empty: feed gaps into Wave T's existing fix loop
   (`wave_t_max_fix_iterations` at `config.py:803`, default 2). The fix
   prompt is re-dispatched (Claude, because Wave T hard-bypasses provider
   routing — `wave_executor.py:3243-3260`) with a `[TEST GAP LIST]` block
   appended. The fix loop writes NEW test code to close the gaps.
3. If `gaps` empty: proceed to Wave E.

Note: T.5 does NOT write tests; only Wave T does. T.5 is purely gap
identification. This decision (Wave 1c §5 Wave T.5 critical anti-pattern)
prevents T.5 from duplicating Wave T.

### 7.6 Codex writes tests vs. identifies gaps

**Identifies gaps only.** (Decided per §7.5.)

### 7.7 Cost estimate

- Codex `reasoning_effort=high`, ~4K prompt tokens (tests + source + ACs),
  ~1.5K output tokens.
- ~$0.50–$1.50 per invocation.
- Per milestone: 1 invocation nominally. Adds 1 Wave T fix-loop iteration
  on average (already budgeted).
- Budget for a typical full_stack 8-milestone run: ~$4–$12.

### 7.8 Implementation — which function

- New function `_execute_wave_t5()` in `cli.py` or `wave_executor.py`
  (prefer `wave_executor.py` since T.5 is a wave dispatch like T).
- Integration in `execute_milestone_waves()` at `wave_executor.py:~3260`
  (after `_execute_wave_t` returns, before Wave E dispatch).

### 7.9 Config

```python
wave_t5_enabled: bool = False
wave_t5_reasoning_effort: str = "high"
wave_t5_skip_if_no_tests: bool = True
```

### 7.10 Skip conditions

- `v18.wave_t5_enabled=False` (default).
- Wave T produced zero test files.
- Wave T failed outright (T.5 input is meaningless if T didn't run).

---

## Part 8: Feature Flag Plan

### 8.1 New flags

All default to **off** so the production pipeline is behavior-identical
until each slice is opted in.

| Flag | Default | Controls |
|---|---|---|
| `v18.claude_md_setting_sources_enabled` | `False` | Adds `setting_sources=["project"]` to `_build_options` (Surprise B fix). |
| `v18.claude_md_autogenerate` | `False` | Writes `<cwd>/CLAUDE.md` at M1 startup. |
| `v18.agents_md_autogenerate` | `False` | Writes `<cwd>/AGENTS.md` at M1 startup. |
| `v18.architecture_md_enabled` | `False` | Python-side ARCHITECTURE.md init + append. |
| `v18.architecture_md_max_lines` | `500` | Auto-summarize threshold. |
| `v18.architecture_md_summarize_floor` | `5` | Keep last N milestones in full. |
| `v18.wave_a5_enabled` | `False` | Enables Wave A.5 Codex plan review. |
| `v18.wave_a5_reasoning_effort` | `"medium"` | Codex effort for A.5. |
| `v18.wave_a5_max_reruns` | `1` | Max Wave A reruns triggered by A.5 CRITICAL findings. |
| `v18.wave_a5_skip_simple_milestones` | `True` | Auto-skip small milestones. |
| `v18.wave_a5_simple_entity_threshold` | `3` | Skip if ≤ this many entities. |
| `v18.wave_a5_simple_ac_threshold` | `5` | Skip if ≤ this many ACs. |
| `v18.wave_t5_enabled` | `False` | Enables Wave T.5 Codex edge-case audit. |
| `v18.wave_t5_reasoning_effort` | `"high"` | Codex effort for T.5. |
| `v18.wave_t5_skip_if_no_tests` | `True` | Skip if Wave T produced no tests. |
| `v18.codex_fix_routing_enabled` | `False` | Enables classifier-based Codex fix path. |
| `v18.codex_fix_timeout_seconds` | `900` | Codex fix dispatch timeout. |
| `v18.codex_fix_reasoning_effort` | `"high"` | Codex effort for fix dispatches. |
| `v18.wave_d_merged_enabled` | `False` | Switches D + D.5 to merged Claude Wave D. |
| `v18.wave_d_compile_fix_max_attempts` | `2` | Merged-D compile-fix attempts before rollback. |
| `v18.provider_map_a5` | `"codex"` | Override provider for Wave A.5. |
| `v18.provider_map_t5` | `"codex"` | Override provider for Wave T.5. |

The `v18.codex_transport_mode` flag at `config.py:811` already exists with
default `"exec"`; Phase G only adds the consumer at `cli.py:3182` (no flag
default change).

### 8.2 Flags to retire

- `v18.wave_d5_enabled` (`config.py:791`, default `True`) — superseded by
  `v18.wave_d_merged_enabled`. **Phase-out plan:**
  1. Phase G-1 (this slice): keep `wave_d5_enabled` flag active;
     `wave_d_merged_enabled` defaults False; legacy path unchanged.
  2. Phase G-2 (next slice, after smoke shows merged path is stable):
     flip `wave_d_merged_enabled` default to `True`;
     `wave_d5_enabled` becomes ignored with a deprecation warning logged
     at init.
  3. Phase G-3 (later): remove `wave_d5_enabled` declaration and the
     legacy D/D.5 dispatch branch.

### 8.3 Rollback strategy

Every new capability is gated. Rollback = flip flag to `False` and re-run.
No database/state migrations required. The `.agent-team/` state
directory's schema version (`state.py:19-96`) is unchanged — new artifact
files (`WAVE_A5_REVIEW.json`, `WAVE_T5_GAPS.json`, `ARCHITECTURE.md`) are
purely additive and ignored by pre-Phase-G code.

The one exception is the transport selector at `cli.py:3182`: it is a
behavior change only when `v18.codex_transport_mode` is flipped to
`"app-server"`. Default `"exec"` preserves legacy. Rollback = flip flag
back.

---

## Part 9: Implementation Order

### 9.1 Dependency graph

```
┌──────────────────────────────┐
│ Slice 1 — Foundations        │
│  1a. setting_sources fix      │   no deps
│  1b. transport selector       │   no deps
│  1c. ARCHITECTURE.md writer   │   no deps (python-only)
│  1d. CLAUDE.md + AGENTS.md    │   depends on 1a (CLAUDE.md is inert
│      renderers + autogenerate │              without 1a)
└──────────────────────────────┘
              │
              ▼
┌──────────────────────────────┐
│ Slice 2 — Codex fix routing   │
│  2a. classifier wire-in      │   depends on 1b (app-server transport)
│  2b. wrap_fix_prompt_for_codex│   no new deps
│  2c. codex_fix timeout config │   no new deps
└──────────────────────────────┘
              │
              ▼
┌──────────────────────────────┐
│ Slice 3 — Wave D merge        │
│  3a. merged prompt builder   │   no new deps
│  3b. WAVE_SEQUENCES update    │   no new deps
│  3c. provider flip D→Claude   │   no new deps (gated)
│  3d. compile-fix-then-rollback│   no new deps
└──────────────────────────────┘
              │
              ▼
┌──────────────────────────────┐
│ Slice 4 — Wave A.5 + T.5      │
│  4a. _execute_wave_a5        │   depends on 1b (Codex transport)
│  4b. _execute_wave_t5         │   depends on 1b
│  4c. WAVE_SEQUENCES update    │   no new deps
│  4d. integration hooks        │   no new deps
└──────────────────────────────┘
```

### 9.2 Minimum first slice (shippable independently)

**Slice 1** — Foundations. All four items are:

- Behavior-neutral when flags default off.
- ≤50 LOC each.
- Independently testable via unit tests (`tests/test_claude_md_opt_in.py`,
  `tests/test_transport_selector.py`, etc.).
- No changes to wave dispatch logic.

Specifically:

- **1a (setting_sources)** — single flag + single `opts_kwargs` branch at
  `cli.py:~430`. Write test: construct `ClaudeAgentOptions` under both flag
  settings; assert `setting_sources` field presence.
- **1b (transport selector)** — single flag consumer at `cli.py:3182`.
  Write test: monkeypatch `v18.codex_transport_mode`; assert imported
  module name.
- **1c (ARCHITECTURE.md writer)** — new module `architecture_writer.py` +
  two hook sites in `wave_executor.py:~3150` and `~3542`. Write test:
  fixtures for wave artifacts → assert file content format.
- **1d (constitution renderers)** — new module `constitution_templates.py`
  + new python helper invoked at M1 init. Write test: golden-file diff
  between rendered CLAUDE.md and AGENTS.md templates.

### 9.3 Subsequent slices

- **Slice 2** requires 1b. After Slice 1 smoke, enable
  `codex_fix_routing_enabled=True` on a single smoke run. Validate via
  build telemetry (patch-mode fix costs + transport used).
- **Slice 3** is the riskiest (provider flip for a wave that's been Codex
  since Phase B). After Slice 1+2 smoke, enable `wave_d_merged_enabled`
  on a single smoke run. Measure: Wave D compile-pass rate, Wave T test
  pass-rate, overall milestone budget.
- **Slice 4** requires 1b. Can land independently after Slice 1 (even
  before Slice 2/3). Start with `wave_a5_enabled=True` on a 2-milestone
  smoke; then add `wave_t5_enabled=True`.

### 9.4 Recommended first PR

Slice 1 alone. Smallest blast radius; fixes two of the three Wave 1a
surprises (A and B) in a single atomic change; unblocks Slices 2–4.

---

## Appendix A: Config / Code Locations to Modify (file:line index)

### Files to modify

| File | Lines | Change |
|---|---|---|
| `src/agent_team_v15/config.py` | near 791 (insert) | Add all new `v18.*` flags listed in §8.1. |
| `src/agent_team_v15/config.py` | near 806 (modify) | No change — `provider_routing` default already False. |
| `src/agent_team_v15/cli.py` | 3182 | Replace hard-coded import with transport selector (§4.3). |
| `src/agent_team_v15/cli.py` | 3184-3187 | Extend `WaveProviderMap` construction with `A5`, `T5`, conditional `D` flip (§2.1). |
| `src/agent_team_v15/cli.py` | 427-444 | Add `setting_sources` to `opts_kwargs` (§5b.2). |
| `src/agent_team_v15/cli.py` | 6441 | Add classifier-based Codex fix branch (§4.2). |
| `src/agent_team_v15/provider_router.py` | 27-42 | Add `A5`, `T5` fields to `WaveProviderMap` (§2.1). |
| `src/agent_team_v15/wave_executor.py` | 307-311 | New `WAVE_SEQUENCES` entries (§1.2). |
| `src/agent_team_v15/wave_executor.py` | 395-403 | Extend `_wave_sequence` to strip `A5`/`T5`/`D5` per flags (§1.2, §3.5, §8.2). |
| `src/agent_team_v15/wave_executor.py` | ~3150 | Hook: `architecture_writer.init_if_missing(cwd)` (§5a.3). |
| `src/agent_team_v15/wave_executor.py` | ~3250 | Hook: `_execute_wave_a5()` dispatch (§6.5). |
| `src/agent_team_v15/wave_executor.py` | ~3260 | Hook: `_execute_wave_t5()` dispatch (§7.5). |
| `src/agent_team_v15/wave_executor.py` | ~3295-3305 | Merged-D compile-fix + rollback (§3.4). |
| `src/agent_team_v15/wave_executor.py` | ~3542-3548 | Hook: `architecture_writer.append_milestone(...)` (§5a.4). |
| `src/agent_team_v15/agents.py` | 8696-8858 | Extend `build_wave_d_prompt` with `merged` kwarg or new function (§3.6). |
| `src/agent_team_v15/agents.py` | 9018-9131 | Dispatcher: gate D prompt selection on `wave_d_merged_enabled` (§3.6). |

### Files to add

| File | Purpose |
|---|---|
| `src/agent_team_v15/architecture_writer.py` | ARCHITECTURE.md init/append/summarize helpers (§5a). |
| `src/agent_team_v15/constitution_templates.py` | Shared stack-rule constants + CLAUDE.md/AGENTS.md renderers (§5b.5, §5c.5). |
| `src/agent_team_v15/constitution_writer.py` | M1-init hook that renders and writes the two files (§5b.5). |
| `src/agent_team_v15/codex_fix_prompts.py` (or extend `codex_prompts.py`) | `wrap_fix_prompt_for_codex()` helper (§4.4). |

### Files to read but not modify

- `src/agent_team_v15/codex_appserver.py:634-693` — confirms
  `execute_codex()` signature matches legacy transport.
- `src/agent_team_v15/codex_transport.py:687` — legacy transport signature.
- `src/agent_team_v15/provider_router.py:481-504` — classifier to wire.

---

## Appendix B: Cost Estimates (per milestone, per flag combo)

Assumed: full_stack template, 8 milestones, typical complexity (5 entities,
10 ACs, 3–5 endpoints per milestone).

### B.1 Baseline (all Phase G flags OFF)

| Wave | Provider | Avg cost per milestone | Notes |
|---|---|---|---|
| A | Claude | $0.80 | existing |
| B | Codex `high` | $2.50 | existing |
| C | Python | $0.00 | OpenAPI gen |
| D | Codex `high` | $2.20 | existing |
| D5 | Claude | $0.60 | existing |
| T | Claude | $1.00 | existing |
| E | Claude | $0.80 | existing |
| Audit | Claude | $1.20 | existing |
| Fix (1–2 rounds) | Claude | $1.50 | existing |
| **Per-milestone total** | | **~$10.60** | |
| **8-milestone run** | | **~$85** | |

### B.2 Phase G flags ON (incremental cost)

| Added feature | Incremental cost per milestone | Notes |
|---|---|---|
| setting_sources + CLAUDE.md load | $0.00 | No new LLM call; slight token overhead (~500 tokens/prompt × 10 prompts = $0.05) |
| ARCHITECTURE.md auto-inject | $0.05 | Token overhead on every wave prompt |
| Wave A.5 (`medium`) | +$0.20 | 1 Codex turn; skipped on simple milestones (~30% skip rate) |
| Wave D merge (Codex→Claude) | -$0.40 net | Claude D (~$2.50) replaces Codex D (~$2.20) + D5 (~$0.60). Net savings $0.30. |
| Wave T.5 (`high`) | +$0.80 | 1 Codex turn + possible 1 extra Wave T fix iteration |
| Codex fix routing | -$0.20 net | Some fixes route to Codex (cheaper per-token at $0.X vs Claude $0.Y); modest net savings |
| **All Phase G incremental** | **+$0.45** | Per milestone; ~$3.60 per 8-milestone run |

Net effect per 8-milestone run: ~+4% cost (~$85 → ~$89). In exchange:
- A.5 catches plan errors before Wave B (save ~$4–$8 rework per caught gap).
- T.5 catches test gaps before Wave E (save ~$3–$5 rework per caught gap).
- D merge eliminates one wave transition + one Codex orphan-tool risk.
- Codex fix routing gives backend fixes to the right model.

### B.3 Slice-by-slice cost

| Slice | Features enabled | Incremental run cost | Payback condition |
|---|---|---|---|
| 1 (Foundations) | setting_sources + CLAUDE.md + AGENTS.md + ARCHITECTURE.md | +$0.10 / run | Zero LLM cost; payback via downstream wave quality. |
| 2 (Codex fix) | codex_fix_routing_enabled + transport_mode=app-server | -$0.20 to -$1.60 / run | Immediate — cheaper Codex fix dispatches. |
| 3 (D merge) | wave_d_merged_enabled | -$0.20 to -$3.20 / run | Immediate — fewer prompt tokens; also fixes orphan-tool wedge. |
| 4 (A.5 + T.5) | wave_a5_enabled + wave_t5_enabled | +$1.00 / run | Pays back via avoided rework (one caught gap per run breaks even). |

### B.4 Cost caveats

- Codex model pricing is volatile; numbers above assume GPT-5.4 list price
  at Wave 1c cutoff (January 2026).
- Caching (`_n17_prefetch_cache` at `cli.py:3976`) reduces repeated
  doc-fetch cost; not reflected in per-milestone numbers.
- Budget overrun flag `v18.max_budget_usd` caps runs; Phase G does not
  change that enforcement — a Phase G-enabled run is still bounded by the
  existing budget guard (`_build_options` `max_budget_usd=` at
  `cli.py:398`).

---

## Part 10: How Phase G addresses each Wave 1a Surprise

| Wave 1a Surprise | Phase G response |
|---|---|
| #1 `codex_transport_mode` never consumed | Slice 1b: transport selector at `cli.py:3182` (§4.3). |
| #2 `setting_sources` never set | Slice 1a: `setting_sources=["project"]` added to `_build_options` (§5b.2). |
| #3 `classify_fix_provider` never called | Slice 2a: wire at `cli.py:6441` (§4.2). |
| #4 Wave T hard-bypasses provider_routing | Preserved as-is; T.5 layered after, not routing T itself. |
| #5 D5 forces Claude regardless of map | Preserved (merged Wave D is always Claude; D5 alias path retires). |
| #6 No `MILESTONE_HANDOFF.md` | ARCHITECTURE.md fills the gap (§5a). |
| #7 No cumulative architecture doc | ARCHITECTURE.md (§5a). |
| #8 Fix prompt re-inlines whole PRD | Unchanged — still cheap under 1M context; reviewed, no action. |
| #9 `_n17_prefetch_cache` per-milestone | Out of Phase G scope; noted for follow-up (cache broadening is independent). |

---

## Inviolable Items Verified

- **IMMUTABLE `packages/api-client/*` wording** (`agents.py:8803`,
  `codex_prompts.py:229-231`) — carried verbatim into merged Wave D §3.1
  and into Codex fix prompt §4.4.
- **`_ANTI_BAND_AID_FIX_RULES`** — carried verbatim into Codex fix prompt
  §4.4; unchanged in Claude fix prompt at `cli.py:6422`.
- **Every design point cites file:line from Wave 1a findings** — verified;
  no design claim lacks a source.
- **Every "wave added" decision includes cost estimate + skip conditions**
  — §6.6 / §6.7 (Wave A.5) and §7.9 / §7.10 (Wave T.5).
