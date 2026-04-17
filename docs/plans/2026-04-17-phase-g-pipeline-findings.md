# Phase G — Wave 1a — Pipeline Architecture Findings

> Repo: `C:\Projects\agent-team-v18-codex`  branch `integration-2026-04-15-closeout` HEAD `466c3b9`
> Mode: PLAN ONLY — no source files modified. Only this deliverable was created.
> Scope: wave execution system end-to-end, provider routing, audit loop, fix loop,
> state persistence, auto-loaded CLI configuration files.

All findings below cite `path:line` pairs. Where the claim is a design-relevant
behavior (e.g. "Wave T bypasses provider routing"), the exact function body is
cited. Two Context7 queries were used to verify upstream SDK / CLI behavior;
their verbatim outputs are in Appendix B.

---

## Executive Summary

The V18 hardened builder runs one **Claude-orchestrator session** (`ClaudeSDKClient`
with a heavyweight system prompt + agent definitions) that iterates milestones and,
for each milestone, drives a **wave pipeline** (A → B → C → D → D5 → T → E) where
individual wave letters are optionally routed to **OpenAI Codex** via a second
transport. Wave C is pure Python (OpenAPI generation); Wave T is Claude-only by
design (wave_executor.py:3243-3260); Waves B and D default to Codex when
`v18.provider_routing` is ON (config.py:806, 815-816).

Two Codex transports exist: the **legacy subprocess transport**
(`codex_transport.py` — `codex exec --json`) and the **Phase E JSON-RPC
transport** (`codex_appserver.py` — `codex_app_server.AppServerClient`). The
second exists solely to support `turn/interrupt` and `item/started` /
`item/completed` event pairing for orphan-tool detection (codex_appserver.py:1-17).
**Surprise (#1):** `v18.codex_transport_mode` is declared (config.py:811) but
**nothing in cli.py consumes it** — the dispatcher unconditionally imports
`agent_team_v15.codex_transport` at cli.py:3182, so the app-server path is only
reachable via direct callers (tests, provider_router imports the exception type
at provider_router.py:263), never via the production wave pipeline.

Fix agent dispatch is **Claude-only** regardless of the originating wave —
`_run_audit_fix_unified` (cli.py:6271) spawns fresh `ClaudeSDKClient` instances
for both the "patch" path (cli.py:6441) and the "full-build" escalation path
(cli.py:6472, spawns a subprocess re-running the whole builder). There is no
Codex-routed fix path.

Per-milestone persistent state lives in `.agent-team/`: `STATE.json`
(state.py:326, full schema below), `MASTER_PLAN.json`
(wave_executor.py:477), per-milestone `REQUIREMENTS.md` / `TASKS.md` /
`WAVE_FINDINGS.json` / `AUDIT_REPORT.json`, per-wave artifact JSONs under
`.agent-team/artifacts/{milestone}-wave-{letter}.json` (wave_executor.py:435-442),
and per-wave telemetry under `.agent-team/telemetry/`. There is **no
project-level architecture document that persists across milestones** — the
"architecture" is implicit in the artifacts + prompts.

For auto-loaded CLI files: **Codex auto-loads `AGENTS.md`** from the CWD and all
ancestor directories when running `codex exec` (verbatim from context7 on
`/openai/codex`). **Claude Code CLI auto-loads `CLAUDE.md`** (verbatim from
context7 on `/websites/code_claude`), **but only if callers opt in via
`setting_sources=["project"]` + `system_prompt.preset="claude_code"`**.
**Surprise (#2):** The builder's `_build_options()` (cli.py:339) does NOT set
`setting_sources` — so any `CLAUDE.md` at the repo root of the generated project
would NOT be auto-injected into wave / audit / fix sessions. And the builder
repo itself has **no `CLAUDE.md` and no `AGENTS.md`** at any of these roots
(verified 2026-04-17 via `find … -maxdepth 3`).

---

## Part 1: Complete Wave Sequence Map (per template)

### Wave sequence source of truth

`wave_executor.py:307-311`:

```
WAVE_SEQUENCES = {
    "full_stack":   ["A", "B", "C", "D", "D5", "E"],
    "backend_only": ["A", "B", "C", "E"],
    "frontend_only":["A", "D", "D5", "E"],
}
```

`_wave_sequence(template, config)` at `wave_executor.py:395-403` mutates this:

- Removes `"D5"` when `_wave_d5_enabled(config)` is False (config.py:791 default True).
- Inserts `"T"` immediately before `"E"` when `_wave_t_enabled(config)` is True
  (default True, config.py:802).

Net effect with current defaults:

- **full_stack**:   A → B → C → D → D5 → **T** → E
- **backend_only**: A → B → C → **T** → E
- **frontend_only**:A → D → D5 → **T** → E

### Dispatch table per wave

The authoritative dispatch loop is `execute_milestone_waves()` at
`wave_executor.py:3120-3550`. Per-wave behavior:

| Wave | Prompt builder (agents.py) | Dispatcher (wave_executor.py) | Default provider | Post-wave compile? | Primary artifact consumed by |
|------|----------------------------|-------------------------------|------------------|---------------------|------------------------------|
| A    | `build_wave_a_prompt()` at agents.py:7750 | `_execute_wave_sdk()` at wave_executor.py:2502 → `provider_router.execute_wave_with_provider()` | `claude` (provider_router.py:30, `WaveProviderMap.A = "claude"`) | YES (wave_executor.py:3295-3305) — compile gate runs for A/B/D/D5 | Wave B (entity files) via `wave_artifacts["A"]` (wave_executor.py:3429) |
| B    | `build_wave_b_prompt()` at agents.py:7909 | `_execute_wave_sdk()` — same | `codex` (provider_router.py:31; config.py:815 `provider_map_b="codex"`) — wrapped with `CODEX_WAVE_B_PREAMBLE` (codex_prompts.py:10-158) | YES, plus DTO-contract guard (wave_executor.py:3308-3324) + duplicate-prisma cleanup + Wave-B output sanitization (Phase F N-19) | Wave C (OpenAPI generator reads controllers) + Wave D via artifact |
| C    | Python-only (wave_executor.py:3233-3242 → `_execute_wave_c()` at wave_executor.py:2646-2689) | No LLM dispatch — calls `generate_contracts` callback (cli.py injects `generate_openapi_contracts`) | `python` (provider_router.py:32) — cost 0 | SKIPPED (compile_skipped=True at wave_executor.py:2658) | Wave D consumes `packages/api-client/*` |
| D    | `build_wave_d_prompt()` at agents.py:8696 | `_execute_wave_sdk()` — same | `codex` (provider_router.py:33; config.py:816 `provider_map_d="codex"`) — wrapped with `CODEX_WAVE_D_PREAMBLE` (codex_prompts.py:180-242) | YES + frontend-hallucination guard (wave_executor.py:3332-3345) | Wave D5 polish + Wave E tests |
| D5   | `build_wave_d5_prompt()` at agents.py:8860 | `_execute_wave_sdk()` — same | `claude` forced (provider_router.py:34, 39-41 — any alias `D5`/`UI` returns `"claude"`) | YES, with **rollback on failure** (wave_executor.py:3357-3375, uses `snapshot_for_rollback` at provider_router.py:44-57) | Wave T, Wave E |
| T    | `build_wave_t_prompt()` at agents.py:8391 | **`_execute_wave_t()` at wave_executor.py:2111** — bypasses `_execute_wave_sdk()` entirely | **Claude-only** — wave_executor.py:3243-3260 comment: "V18.2: Wave T ALWAYS routes to Claude — bypass provider_routing entirely regardless of the user's provider_map" | Implicit (Wave T runs tests internally with fix loop up to `v18.wave_t_max_fix_iterations` default 2, config.py:803) | Wave E reads Wave T handoff JSON |
| E    | `build_wave_e_prompt()` at agents.py:8147 | `_execute_wave_sdk()` — same | `claude` (provider_router.py:35 `WaveProviderMap.E = "claude"`) | NO, but triggers post-Wave-E scans (wave_executor.py:3466-3508): `_run_post_wave_e_scans()`, `_run_node_tests`, `_run_playwright_tests` | Audit loop (via `WAVE_FINDINGS.json`) |

Code-path callouts for every row:

- **Every non-C/non-T wave** flows through
  `_execute_wave_sdk()` (wave_executor.py:2502-2643). The function calls
  `_invoke_provider_wave_with_watchdog()` (wave_executor.py:1509-1590) when
  `provider_routing` is passed; that function calls
  `provider_router.execute_wave_with_provider()` (provider_router.py:149-210),
  which dispatches to either `_execute_claude_wave()` (provider_router.py:212-238)
  or `_execute_codex_wave()` (provider_router.py:240-423).
- **Wave T dispatch** sits entirely inside `_execute_wave_t()` at
  wave_executor.py:2111-2389. It takes `execute_sdk_call` (the Claude callback)
  directly — no `provider_routing` parameter — and runs a Claude fix-loop bounded
  by `wave_t_max_fix_iterations`.
- **Post-wave compile gate** runs for `A/B/D/D5` via `_run_wave_compile()` at
  wave_executor.py:2768-2887; Wave A/B guard extensions (DTO contract guard,
  duplicate-prisma cleanup, Wave-B output sanitization, frontend-hallucination
  guard) are all invoked from the same block at wave_executor.py:3295-3395.
- **Wave E post-dispatch scans** (wave_executor.py:3466-3508) are python-side
  and LLM-free: `_run_post_wave_e_scans(cwd)` at wave_executor.py:1860-1912
  (forbidden-content, wiring, i18n scanners), `_run_node_tests` at
  wave_executor.py:1775-1817, `_run_playwright_tests` at wave_executor.py:1819-1858.

### Artifact flow graph

`_load_dependency_artifacts()` (wave_executor.py:445-459) loads wave A/B/C
artifacts from each milestone the current one declares as a dependency — this
is the only cross-milestone artifact handoff. Per-wave artifacts are saved at
`.agent-team/artifacts/{milestone_id}-wave-{LETTER}.json` by
`_save_wave_artifact()` (wave_executor.py:435-442). Each wave's artifact is
stored in `wave_artifacts[wave_letter]` (wave_executor.py:3423-3429) and passed
into the next wave's prompt builder (e.g. Wave B reads `wave_artifacts["A"]`
via `wave_a_artifact=` in `build_wave_b_prompt()`, agents.py:9081-9089).

---

## Part 2: Provider Routing Mechanics

### `WaveProviderMap` and routing entry point

`provider_router.py:27-42`:

```python
@dataclass
class WaveProviderMap:
    A: str = "claude"
    B: str = "codex"    # Codex strongest at integration wiring
    C: str = "python"   # Contract generation — no provider needed
    D: str = "codex"    # Codex owns frontend + generated-client wiring
    D5: str = "claude"  # UI polish is always Claude-owned
    E: str = "claude"

    def provider_for(self, wave_letter: str) -> str:
        wave_key = str(wave_letter or "").strip().upper()
        if wave_key in {"D5", "UI"}:
            return "claude"
        provider = getattr(self, wave_key, "claude")
        return str(provider or "claude").strip().lower()
```

D5 is hard-pinned to Claude at line 39-41 even if a caller sets it on the dataclass.

### Configurability

Only `provider_map_b` and `provider_map_d` are loadable from config
(config.py:815-816, loaded at config.py:2513-2514). `WaveProviderMap` is
constructed at cli.py:3184-3187:

```python
provider_map = WaveProviderMap(
    B=getattr(v18, "provider_map_b", "codex"),
    D=getattr(v18, "provider_map_d", "codex"),
)
```

`A`, `E`, `D5`, and `C` are **not user-configurable from the v18 config** —
they are always `claude` / `claude` / `claude` / `python` respectively. Opting
out of Codex entirely requires setting `v18.provider_routing = False`
(config.py:806); that leaves `_provider_routing = None` at cli.py:3203 and the
fallback "existing Claude-only path" at wave_executor.py:2598-2642 runs
instead.

### `_execute_single_wave_sdk` (Claude) vs `_execute_wave_codex` (Codex)

The two paths are orchestrated by `provider_router.execute_wave_with_provider()`
(provider_router.py:149-210):

- **Claude branch** (provider_router.py:206-210) calls
  `_execute_claude_wave()` (provider_router.py:212-238), which invokes the
  caller-supplied `claude_callback` — in the pipeline this is
  `_execute_single_wave_sdk` at cli.py:3908-3939 (inside the milestone
  context) and the re-declared version at cli.py:4547 (non-isolation path).
  Both definitions do the same thing: build per-wave options via
  `_prepare_wave_sdk_options`, open a fresh `ClaudeSDKClient(options=…)`,
  call `client.query(prompt)`, drain response through `_process_response`.
- **Codex branch** (provider_router.py:194-204) calls
  `_execute_codex_wave()` (provider_router.py:240-423):
  1. Checks `codex_transport_module.is_codex_available()` (provider_router.py:278-288)
  2. Creates a pre-wave file checkpoint + snapshot (provider_router.py:291-292)
  3. Wraps the Claude-shaped prompt with
     `codex_prompts.wrap_prompt_for_codex(wave_letter, prompt)`
     (provider_router.py:295-299) — prepends `CODEX_WAVE_B_PREAMBLE` or
     `CODEX_WAVE_D_PREAMBLE` and appends matching suffix (codex_prompts.py:245-284).
  4. Calls `codex_transport_module.execute_codex(prompt, cwd, config,
     codex_home, progress_callback)` (provider_router.py:315-323)
  5. On timeout / orphan-tool / generic exception: rolls back the checkpoint
     (provider_router.py:324-368) and falls back to Claude via the same
     callback (`_claude_fallback` at provider_router.py:425-455).
  6. On "success but no file changes": also falls back to Claude
     (provider_router.py:378-393) — this is a behavior-level safeguard against
     Codex reporting OK without writing anything.
  7. Runs Prettier / ESLint --fix on changed style-eligible files
     (provider_router.py:393, `_normalize_code_style` at provider_router.py:101-147).

### Wrapper / preamble Codex gets that Claude doesn't

`codex_prompts.wrap_prompt_for_codex()` (codex_prompts.py:251-284) wraps only
wave letters in `_WAVE_WRAPPERS` (codex_prompts.py:245-248) — **only "B" and
"D"**. Wave-B wrapper contents (codex_prompts.py:10-177):
- Autonomy / persistence / convention-matching / active-backend / barrels /
  no-markdown / no-confirmation execution directives.
- **8 canonical NestJS 11 / Prisma 5 patterns** (AUD-009 / 010 / 012 / 013 /
  016 / 018 / 020 / 023) with **verbatim quoted idioms from upstream docs**
  plus positive / anti-pattern examples.
- Verification checklist suffix (codex_prompts.py:159-177).

Wave-D wrapper contents (codex_prompts.py:180-242): autonomy directives,
generated-client-wins rule, state-completeness requirements, packages/api-client
immutability checklist (codex_prompts.py:229-231).

Claude does NOT receive these preambles — the unwrapped prompt is what
`build_wave_b_prompt` / `build_wave_d_prompt` produce.

### How `codex_appserver.py` (Phase E) changes dispatch — AND WHY IT CURRENTLY DOESN'T

Phase E introduced `codex_appserver.py` (692 lines) as a drop-in replacement
for `codex_transport.py` exposing the same `execute_codex()` signature
(codex_appserver.py:634-693). The config flag
`v18.codex_transport_mode: str = "exec"` (config.py:811) is supposed to
select between "exec" (legacy) and "app-server" (Phase E).

**Surprise #1 (important for Phase G design):** `codex_transport_mode` is
**never consumed at dispatch time**. The only production code path that wires
the transport into `_provider_routing` is cli.py:3182:

```python
import agent_team_v15.codex_transport as _codex_mod
```

— hard-coded to the legacy subprocess transport. A repo-wide grep for
`codex_transport_mode` returns only config.py:811 (the field definition) and
its coerce at config.py (not shown — only the default declaration exists,
the field is read nowhere else). `codex_appserver.py` is referenced only by
`provider_router.py:263` (importing the `CodexOrphanToolError` exception type
defensively) and by its own tests. **The Phase E transport is not wired in.**

Design-relevant consequence for Phase G pipeline-restructure: any plan that
relies on the app-server transport (e.g. for clean `turn/interrupt` on
orphan-tool wedge) must either (a) add a transport selector in cli.py around
line 3182, or (b) swap the hard-coded import.

### Fallback chain

On Codex failure (any branch), `_claude_fallback()` (provider_router.py:425-455)
re-runs the same wave through `_execute_claude_wave()` and marks
`result["fallback_used"] = True`. The retry budget itself is controlled at
`wave_executor.py:2523-2596` — `_execute_wave_sdk()` loops up to
`_wave_watchdog_max_retries(config) + 1` times (config.py:795 default 1, so 2
attempts). On `WaveWatchdogTimeoutError` (wave_executor.py:2559-2583) the
second attempt passes `force_claude_fallback_reason` to short-circuit the
Codex path entirely (provider_router.py:178-192).

---

## Part 3: Fix Agent Routing

### Entry point and model

`_run_audit_fix_unified()` at cli.py:6271-6506 is the production fix dispatcher.
Its internals:

1. Converts `AuditReport.findings` → `audit_agent.Finding` dataclasses
   (cli.py:6345-6383).
2. Calls `execute_unified_fix_async()` (cli.py:6491-6501 → fix_executor.py:312-441).
3. `execute_unified_fix_async()` first runs `generate_fix_prd()`
   (fix_prd_agent.py:361, Python text-generation — no LLM), then classifies
   each "feature" as `mode=patch` or `mode=full` via
   `classify_fix_feature_mode()` (fix_prd_agent.py:180).
4. **Patch mode** → `run_patch_fixes` callback (fix_executor.py:356-375),
   which in cli.py is `_run_patch_fixes()` at cli.py:6385-6449. That function
   opens a fresh `ClaudeSDKClient(options=options)` per feature at cli.py:6441
   and calls `client.query(fix_prompt)`. **Fix prompt is Claude-only.**
5. **Full-build mode** → `run_full_build` callback (fix_executor.py:377-389),
   which is `_run_full_build()` at cli.py:6451-6489. That function **spawns a
   subprocess re-running the whole builder** (`python -m agent_team_v15 --prd
   <fix_prd> …` at cli.py:6459-6468); the spawned builder's wave pipeline then
   follows whatever `provider_routing` was configured in the child process.
6. Modified files returned to `_run_audit_loop` (cli.py:6640-6671) for
   selective re-audit scope computation.

### Context the fix agent receives

The patch-mode fix prompt is built at cli.py:6417-6429:

```
[PHASE: AUDIT FIX - ROUND {r}, FEATURE {i}/{N}]
[EXECUTION MODE: {PATCH|FULL}]
[TARGET FILES: {...}]
[FEATURE: {name}]

{_ANTI_BAND_AID_FIX_RULES}           # constant string — not found in this read pass

Apply this bounded repair plan. Read each target file before editing. Do not
introduce unrelated changes.

[FIX FEATURE]
{feature_block}                      # feature markdown block from generate_fix_prd

[ORIGINAL USER REQUEST]
{task_text}                          # entire PRD text
```

The fix agent runs with full orchestrator options (via `_build_options` at
cli.py:6431-6437) — same `system_prompt`, same MCP servers, same agent
definitions as the top-level orchestrator. That means the fix agent has the
same tool belt (Read/Write/Edit/Bash/Glob/Grep + Context7 + Sequential-Thinking
+ per-config extras) as the orchestrator.

### Classification logic (fix provider)

`provider_router.classify_fix_provider()` (provider_router.py:481-504) exists
and uses issue-type + file-path heuristics (keyword sets at
provider_router.py:457-478) to return `"codex"` or `"claude"`. **But nothing
in cli.py calls it.** A grep for `classify_fix_provider` shows only the
definition and its export. So:

- **Fix routing today: Claude for every fix, always.**
- The infrastructure for Codex-routed fixes exists (classifier + provider_router
  handles "codex"), but the wiring at cli.py:6441 bypasses it.

### Fix iteration loop shape

The outer loop is `_run_audit_loop()` (cli.py:6509-6797):

```
for cycle in 1..max_reaudit_cycles:
    if cycle > 1:
        snapshot files touched by previous findings (cli.py:6630-6637)
        modified_files, fix_cost = await _run_audit_fix_unified(...)  # cli.py:6640-6643
        selective_auditors = compute_reaudit_scope(modified_files, findings)
    report, audit_cost = await _run_milestone_audit(...)               # cli.py:6676-6686
    detect regression → rollback + break (cli.py:6697-6704)
    detect plateau (3 rounds < 3% Δ) → break                           # cli.py:6711-6721
    should_terminate_reaudit(...) → break                               # cli.py:6724-6737
```

`max_reaudit_cycles` is read at cli.py:6532; `audit_team.max_findings_per_fix_task`
(used in `_run_audit_fix` legacy path) at cli.py:6216.

---

## Part 4: Persistent State Across Milestones

### `.agent-team/` directory contents

Canonical paths read/written by the builder:

| Path | Writer | Reader | Purpose |
|------|--------|--------|---------|
| `.agent-team/STATE.json` | `state.save_state()` at state.py:521-620 | `state.load_state()` at state.py:628-717 + `wave_executor._load_state_dict()` at wave_executor.py:374-381 | Run-level resume state (milestone progress, costs, wave progress, audit score) |
| `.agent-team/MASTER_PLAN.json` | decomposition phase in cli.py (not in this scope — referenced at wave_executor.py:477) | `wave_executor._load_milestone_scope()` at wave_executor.py:462-506 | Milestone list + metadata |
| `.agent-team/milestones/{id}/REQUIREMENTS.md` | decomposition | wave prompt builders (agents.py:7750…), audit prompts, `milestone_spec_reconciler._safe_read` at milestone_spec_reconciler.py:94 | Per-milestone requirements + ACs |
| `.agent-team/milestones/{id}/TASKS.md` | decomposition + Wave E (agents.py:8207-8209) | wave prompt builders, health checks | Per-milestone task tracking |
| `.agent-team/milestones/{id}/WAVE_FINDINGS.json` | `wave_executor.persist_wave_findings_for_audit()` at wave_executor.py:609-681 | audit loop (cli.py:6640+, agents.py:8194-8200) | Probes + scans + Wave T test-fail bridge to auditors |
| `.agent-team/milestones/{id}/AUDIT_REPORT.json` | audit scorer via `audit_team.AuditReport.to_json()` + `_run_audit_loop` at cli.py:6744 | resume guard at cli.py:6535-6548 | Audit result per milestone |
| `.agent-team/milestones/{id}/GATE_*_REPORT.md` | gate functions (not in scope) | `confidence_banners.stamp_all_reports` at confidence_banners.py:257-309 | Post-milestone gate outcomes |
| `.agent-team/artifacts/{milestone}-wave-{LETTER}.json` | `wave_executor._save_wave_artifact()` at wave_executor.py:435-442 | `wave_executor.load_wave_artifact()` at wave_executor.py:423-432 | Per-wave structured handoff — includes `scaffolded_files`, endpoint summaries, client exports |
| `.agent-team/telemetry/{milestone}-wave-{LETTER}.json` | `wave_executor.save_wave_telemetry()` at wave_executor.py:509-575 | diagnostic tooling — no in-pipeline reader | Per-wave duration / cost / tokens / watchdog / tests-run telemetry |
| `.agent-team/MCP_PREFLIGHT.json` | `mcp_servers.run_mcp_preflight()` at mcp_servers.py:429-491 | operator-visible only | D-09 MCP tool deployability snapshot |
| `.agent-team/scaffold_verifier_report.json` | `scaffold_verifier` (file referenced at config.py:870-871; writer not in this read pass) | `_maybe_run_scaffold_verifier()` at wave_executor.py:885 | N-13 scaffold verification outcome |
| `.agent-team/evidence/{ac_id}.json` | Wave E agent (instructions at agents.py:8303-8329) | audit scorer | Per-AC evidence records (PASS / PARTIAL / FAIL) |

### `STATE.json` schema (state.py:20-214)

`RunState` top-level fields (state.py:19-96):

- `run_id`, `task`, `depth`, `current_phase`, `completed_phases`,
  `total_cost`, `artifacts` (name→path), `interrupted`, `timestamp`,
  `convergence_cycles`, `requirements_checked/total`, `error_context`
- `milestone_progress: dict[str, dict]`, `v18_config: dict`,
  `wave_progress: dict[str, dict]`
- Schema version 3 fields: `current_milestone`, `completed_milestones`,
  `failed_milestones`, `milestone_order`, `completion_ratio`,
  `completed_browser_workflows`
- Enterprise/department mode: `enterprise_mode_active`,
  `ownership_map_validated`, `waves_completed`, `domain_agents_deployed`,
  `department_mode_active`, `departments_created`, `manager_count`
- Audit/truth: `audit_score`, `audit_health`, `audit_fix_rounds`,
  `truth_scores`, `previous_passing_acs`, `regression_count`
- Gate/pattern/recipe/convergence: `gate_results`, `gates_passed/failed`,
  `patterns_captured/retrieved`, `recipes_captured/applied`,
  `debug_fleet_deployed`, `escalation_triggered`
- Routing: `routing_decisions`, `routing_tier_counts`, `stack_contract`
- `summary`: D-13 reconciled block (populated by `finalize()` at state.py:97-207),
  invariant-checked at write time (state.py:591-601 — `StateInvariantError`
  raised when `summary.success` diverges from `(not interrupted) and
  len(failed_milestones) == 0`).

### `MASTER_PLAN.json` structure

Consumed by `build_scope_for_milestone` (referenced at wave_executor.py:496).
Schema not directly visible in this read pass; the loader expects
`{"milestones": [...]}` (wave_executor.py:484 default shape). Each
milestone dict provides `id`, `template`, `dependencies`, `stack_target`,
`feature_refs`, and `title` — inferred from usages at wave_executor.py:472,
wave_executor.py:809-810, and agents.py:8168.

### `MILESTONE_HANDOFF.md`

No reader / writer for a literal file named `MILESTONE_HANDOFF.md` was found
in the reviewed files. Cross-milestone context is carried via:
- `_load_dependency_artifacts()` → reads Wave A/B/C artifact JSONs
  (wave_executor.py:445-459).
- `MilestoneContext` objects built elsewhere (referenced by
  `build_wave_*_prompt()` signatures at agents.py:8705, agents.py:7919).

### Persistent project-level architecture document?

**None.** There is no file written at project root or in `.agent-team/` that
cumulatively describes the emerging architecture across milestones. The
closest approximations:
- `resolved_manifest.json` — per-milestone only (milestone_spec_reconciler.py:196-199)
- Stack contract loaded at wave_executor.py:3170-3180 — versioned config, not
  an accumulation of decisions
- `ARCHITECTURE_REPORT.md` at repo root (51 KB) — a hand-written historical
  doc, not builder-generated

The "ARCHITECTURE.md is new" note in the brief is consistent with this gap —
the Phase G design can introduce such a document without colliding with an
existing one.

---

## Part 5: Context Window Usage

### Approximate token counts per wave prompt

Each `build_wave_*_prompt()` function ends by calling `check_context_budget`
(agents.py:7876, 8857, 9014, 8354). I could not read the implementation of
`check_context_budget` in the scope allowed, but the function name implies
an explicit budget enforcement. Prompt shape by wave (read directly):

- **Wave A prompt** (agents.py:7776-7873) — existing framework + entity list
  + dependency summary + milestone-AC block + backend-codebase-context +
  rules. Conservative estimate: 3–8 K tokens (varies with dependency count).
- **Wave B prompt** (agents.py:7909+, full body not quoted here) — ownership
  claim section + Wave A artifact + `mcp_doc_context` (N-17 framework idioms
  prefetched from Context7 at cli.py:3981-3991) + scaffolded files + rules.
  Conservative estimate: 8–15 K tokens; Codex path adds 3 KB of preamble
  (codex_prompts.py:10-158).
- **Wave D prompt** (agents.py:8696-8858) — existing framework + MCP doc
  context + frontend codebase context + Wave C artifact + UI standards
  (`include_ui_standards=True` at agents.py:9045, 9062) + acceptance criteria
  + design tokens + i18n config + rules + verification checklist.
  Conservative estimate: 10–20 K tokens; Codex adds ~2 KB preamble
  (codex_prompts.py:180-242).
- **Wave D5 prompt** (agents.py:8860-9015) — app context + design tokens +
  stance + Wave D changed-files list + codex-output-topography guidance +
  acceptance criteria + YOU-CAN / YOU-MUST-NOT blocks + process + verification.
  Conservative estimate: 6–10 K tokens.
- **Wave E prompt** (agents.py:8147-8355) — references to read
  `WAVE_FINDINGS.json` (agents.py:8194-8200) + finalization instructions +
  wiring / i18n / Playwright / evidence blocks + completed-waves-summary
  (via `_format_all_artifacts_summary(wave_artifacts)` at agents.py:8340) +
  acceptance criteria + handoff / phase-boundary rules. Conservative
  estimate: 12–25 K tokens — grows linearly with number of completed waves.
- **Wave T prompt** (agents.py:8391+) — core principle (WAVE_T_CORE_PRINCIPLE
  at agents.py:8374-8388) + per-wave artifact references. Estimate: 8–15 K
  tokens.

Orchestrator system prompt (cli.py:390) is built by
`get_orchestrator_system_prompt(config)` — not read in this pass; the
template is parameterized with escalation thresholds, convergence config,
master plan file, max budget.

### What gets truncated / summarized

- `_format_all_artifacts_summary(wave_artifacts)` at agents.py:8340 — called
  in Wave E. Not read directly but the name implies summarization for budget.
- `_format_dependency_artifacts()` used at agents.py:7814 — same pattern.
- Integration gate injection has explicit caps:
  `contract_injection_max_chars = 15000` and `report_injection_max_chars =
  10000` (config.py:991, 993).
- The scaffold verifier writes `SPEC.md` / `resolved_manifest.json` as
  external files (milestone_spec_reconciler.py:196-199) rather than inlining
  — this is a context-offloading pattern the wave prompts already rely on.

### What would change with 1M context?

Direct observations from the code:
1. Wave E could stop truncating `wave_artifacts` (agents.py:8340) and instead
   inline the full per-wave handoff JSON.
2. Audit-fix prompts (cli.py:6417-6429) already inline the entire `task_text`
   (original PRD) plus the feature block plus `_ANTI_BAND_AID_FIX_RULES`;
   1M allows keeping more findings per fix task (config.py audit_team field
   `max_findings_per_fix_task`).
3. The N-17 MCP-informed dispatches cache at
   `.agent-team/framework_idioms_cache.json` (config.py:907-909) currently
   per-milestone — 1M allows merging per-project cache with richer doc
   excerpts.
4. The orchestrator prompt currently ships with `max_thinking_tokens`
   configurable (cli.py:436-437). Extending that budget interacts with 1M.

None of the wave prompts currently hit a hard truncation ceiling from the
cited read; the visible caps are `contract_injection_max_chars` / etc. —
explicit bytes, not token-budget driven.

---

## Part 6: Wave D + D.5 Mechanics (merge-readiness)

### Wave D prompt contents (Codex)

`build_wave_d_prompt()` at agents.py:8696-8858 emits in order:

1. `existing_prompt_framework` (orchestrator base framing)
2. `[WAVE D - FRONTEND SPECIALIST]` header + `[EXECUTION DIRECTIVES]`
   (agents.py:8725-8731) — read api-client first, complete full scope,
   no planning-only output
3. `[CURRENT FRAMEWORK IDIOMS]` (N-17, agents.py:8734-8741) when
   `mcp_doc_context` non-empty
4. `[YOUR TASK]` — manifest of pages/sections/components
5. `[GENERATED API CLIENT]` — mandates imports from
   `packages/api-client/index.ts` / `types.ts`
6. `[ACCEPTANCE CRITERIA]`
7. `[CODEBASE CONTEXT]` — layout/UI/page/form/table/modal examples
   (agents.py:8761-8773)
8. `[MILESTONE REQUIREMENTS]` + `[MILESTONE TASKS]` excerpts
9. `[DESIGN SYSTEM]` if `_load_design_tokens_block` returns content
   (agents.py:8783-8789)
10. `[I18N CONFIG]` (agents.py:8793-8798)
11. `[RULES]` / `[INTERPRETATION]` / `[IMPLEMENTATION PATTERNS]` /
    `[FILE ORGANIZATION]` / `[I18N REQUIREMENTS]` / `[RTL REQUIREMENTS]` /
    `[STATE COMPLETENESS]` / `[VERIFICATION CHECKLIST]` (agents.py:8800-8852)
12. `[FILES YOU OWN]` (N-02 ownership claim, agents.py:8854)

The IMMUTABLE rule for `packages/api-client/*` appears at agents.py:8803
(long sentence) and is re-echoed in the Codex wrapper suffix at
codex_prompts.py:231 ("Zero edits to `packages/api-client/*` — that directory
is the Wave C deliverable and is immutable").

Design tokens injection: `_load_design_tokens_block(config, cwd)` at
agents.py:8783; block header is `[DESIGN SYSTEM]` at agents.py:8787.

### Wave D5 prompt contents (Claude)

`build_wave_d5_prompt()` at agents.py:8860-9015 emits:

1. `existing_prompt_framework`
2. `[WAVE D.5 - UI POLISH SPECIALIST]` + `[YOUR ROLE]`
3. `[APP CONTEXT]` via `_infer_app_design_context(ir)` (agents.py:8907)
4. `[DESIGN SYSTEM]` (agents.py:8910-8916) — OR `[DESIGN STANCE]` when
   tokens absent
5. `[WAVE D FILES - POLISH THESE FIRST]` (agents.py:8925-8927) — per-file
   list from Wave D artifact
6. **`[CODEX OUTPUT TOPOGRAPHY]`** (agents.py:8929-8943) — this is the
   D-owned-by-Codex consequence: D5 is told explicitly where Codex typically
   places files ("Pages: apps/web/src/app/{route}/page.tsx …") so it doesn't
   fight Codex's layout. Also: `data-testid="{feature}-{element}"` convention
   is declared here and referenced by Wave T / Wave E as test anchors.
7. `[PRESERVE FOR WAVE T AND WAVE E]` (agents.py:8945-8956) — do NOT
   remove/rename data-testid, aria-label, aria-labelledby, role, form name/id,
   href, type, onClick — these are the test-anchor contract.
8. `[MILESTONE ACCEPTANCE CRITERIA]`
9. `[YOU CAN DO]` (agents.py:8961-8969) — Tailwind classes, CSS, responsive,
   hover/focus/transitions, accessibility, loading/empty/error states,
   tokens application
10. `[YOU MUST NOT DO]` (agents.py:8971-8985) — zero-trust guard for data
    fetching / API / hooks / state / routing / TypeScript types / props /
    testids / semantic elements / form field order
11. `[PROCESS]` + `[VERIFICATION CHECKLIST]` (agents.py:8987-9011) — run
    typecheck / dev build; revert on new errors

### Overlap analysis

Functional overlap is deliberately **zero-sum**:
- Wave D = functional frontend (Codex's turf)
- Wave D5 = visual polish (Claude's turf)

Structural overlap that matters for merging them:
- Both receive `existing_prompt_framework` + milestone ACs + design tokens.
- Both read the same codebase context (layout/UI example paths at
  agents.py:8761-8773 vs. agents.py:8925-8956's "polish these files").
- Both write RTL-safe / i18n-safe code (Wave D agents.py:8830-8833 vs.
  Wave D5 agents.py:8981-8985).
- D5 invokes a checkpoint-backed **rollback-on-compile-fail** (wave_executor.py:3357-3375)
  — D does not; if Wave D's compile fix fails it fails the wave.

**Merge-readiness:** a merged Wave-D prompt would need to (a) toggle
provider by section (Codex for functional, Claude for polish — currently
impossible because one wave = one provider call), or (b) collapse into a
single Claude prompt that loses Codex's integration-wiring edge. The clean
cut as-shipped is the right seam.

### IMMUTABLE rule location

The `packages/api-client/*` immutability rule appears in THREE places:
1. Wave D prompt `[RULES]` at agents.py:8803 (single long sentence).
2. Codex Wave-D suffix at codex_prompts.py:229-231 (reiterated for Codex).
3. Codex Wave-D preamble note at codex_prompts.py:213-214 ("applies to every
   provider, not just Codex").

---

## Part 7: Audit Loop Mechanics

### Loop topology

`_run_audit_loop()` (cli.py:6509-6797) → `_run_milestone_audit()` (cli.py:5885 —
referenced but body not in this read) → `_run_audit_fix_unified()`
(cli.py:6271-6506) → re-audit.

Termination criteria are layered (evaluated in this order):

1. **Resume guard** (cli.py:6534-6571) — if existing `AUDIT_REPORT.json` has
   `cycle >= max_cycles` or is already healthy, short-circuit and return.
   F-EDGE-003 (cli.py:6553-6562) tolerates schema drift by restarting.
2. **Regression rollback** (cli.py:6697-6704) — if current score drops by
   > 1 point vs `best_score`, restore snapshot via `_restore_snapshot` and break.
3. **Plateau detection** (cli.py:6711-6721) — three consecutive rounds with
   < 3 point delta → break.
4. **`should_terminate_reaudit`** (audit_team.py:93-133) — five conditions:
   healthy threshold reached, max cycles, regression > 10 points,
   no-improvement, new CRITICAL findings.
5. **Audit budget** — cli.py:6592-6594 comment explicitly notes the budget
   cap was removed in Phase F; loop terminates only on convergence / plateau /
   max_cycles.

### WAVE_FINDINGS.json injection point

The file is written at `persist_wave_findings_for_audit()`
(wave_executor.py:609-681), called unconditionally at
wave_executor.py:3542-3548 AFTER the milestone's wave loop completes
(including on early-break when a wave fails). The file is then read by:
- **Audit loop** — indirectly, via the auditor prompts instructing agents to
  read `.agent-team/milestones/{milestone_id}/WAVE_FINDINGS.json`
  (agents.py:8195 references it in Wave E prompt; auditor prompts likely do
  the same — audit_prompts.py not exhaustively read).
- **Gate scorers** — `persist_wave_findings_for_audit()` records `wave_t_status`
  (D-11) which gate enforcers read.

### Audit fix unified path

Internals already covered in Part 3. Key call sites:
- `compute_reaudit_scope(modified_files, findings)` at cli.py:6669 —
  computes which auditors need re-running based on modified files.
- `_run_milestone_audit(auditors_override=selective_auditors)` at
  cli.py:6685 — passes the selective list so not all 7 auditors run every cycle.

### Where a hypothetical "Codex edge-case audit" (Change 5) would insert

The natural seam is `_run_audit_loop` around cli.py:6676-6686, just before
the selective-auditor re-audit. Options:

- (a) Add a new auditor in `audit_team.DEPTH_AUDITOR_MAP` (audit_team.py:46-52)
  and a matching prompt in `audit_prompts.AUDIT_PROMPTS` (audit_prompts.py:1361-1370).
- (b) Hook a post-fix python-side scanner between cli.py:6644 and cli.py:6676
  that appends findings to the next cycle's report.
- (c) Thread the Codex transport into `_run_audit_fix_unified`'s
  `_run_patch_fixes` (cli.py:6441) with a codex branch selected via
  `provider_router.classify_fix_provider` (provider_router.py:481) — the
  classifier is already written, only the wiring is missing.

---

## Part 8: CLAUDE.md / AGENTS.md Auto-Loading Behavior

### Repo scan (2026-04-17)

```
find . -maxdepth 3 -name "CLAUDE.md" -o -name ".claude" -type d
  → C:/Projects/agent-team-v18-codex/.claude          # dir
  → C:/Projects/agent-team-v18-codex/test_run/output2/.claude  # dir (test artifact)

find . -maxdepth 3 -name "AGENTS.md" -o -name "codex.md"
  → (no matches)
```

`.claude/` at repo root holds only `scheduled_tasks.lock` and
`settings.local.json` (a permissions-allowlist file, not instructions).

**The builder repository does not ship a `CLAUDE.md` and does not ship an
`AGENTS.md`**. If either were to be introduced, Phase G must specify where
(repo root auto-loads for Claude Code CLI; repo root or any ancestor dir from
CWD auto-loads for Codex per the verbatim spec below).

### Claude Code CLI — `CLAUDE.md` auto-load (verbatim from Context7)

Source: `/websites/code_claude` — `code.claude.com/docs/en/claude-directory`:

> *CLAUDE.md is a project-specific instruction file that is loaded into the
> context at the start of every session. It allows developers to define
> conventions, common commands, and architectural context to ensure consistent
> behavior. It is recommended to keep this file under 200 lines to maintain
> high adherence, and it can be placed in the project root or within the
> .claude directory.*

Source: `/websites/code_claude` — `code.claude.com/docs/en/agent-sdk/claude-code-features`:

> *CLAUDE.md files are loaded from various locations including the project
> root, parent directories, subdirectories, and user-specific paths. These
> levels are additive, meaning the agent can access multiple files
> simultaneously. Because there is no hard precedence rule, it is recommended
> to write non-conflicting instructions or explicitly state precedence within
> the files themselves.*

Source: `/websites/code_claude` — `code.claude.com/docs/en/agent-sdk/python`
(AgentSDK opt-in):

> ```python
> options = ClaudeAgentOptions(
>     system_prompt={
>         "type": "preset",
>         "preset": "claude_code",      # Use Claude Code's system prompt
>     },
>     setting_sources=["project"],      # Required to load CLAUDE.md from project
>     allowed_tools=["Read", "Write", "Edit"],
> )
> ```

### Codex CLI — `AGENTS.md` auto-load (verbatim from Context7)

Source: `/openai/codex` — `codex-rs/core/gpt_5_1_prompt.md`:

> *Repositories often contain `AGENTS.md` files, which can be located
> anywhere within the repository. These files serve as a mechanism for humans
> to provide instructions or tips to the agent for working within the
> container, such as coding conventions, information about code organization,
> or instructions on how to run or test code. The scope of an `AGENTS.md`
> file encompasses the entire directory tree rooted at the folder containing
> it. For every file modified in the final patch, the agent must adhere to
> instructions in any `AGENTS.md` file whose scope includes that file.
> Instructions regarding code style, structure, or naming apply only within
> the `AGENTS.md` file's scope, unless explicitly stated otherwise. In cases
> of conflicting instructions, more-deeply-nested `AGENTS.md` files take
> precedence, while direct system, developer, or user instructions (as part
> of a prompt) override `AGENTS.md` instructions. The contents of the
> `AGENTS.md` file at the root of the repo and any directories from the
> Current Working Directory (CWD) up to the root are automatically included
> with the developer message, eliminating the need for re-reading. However,
> when working in a subdirectory of CWD or a directory outside CWD, the
> agent should check for any applicable `AGENTS.md` files.*

### Does the builder opt in?

`_build_options()` (cli.py:339-450) constructs `ClaudeAgentOptions(**opts_kwargs)`
where `opts_kwargs` is built at cli.py:427-444:

```python
opts_kwargs: dict[str, Any] = {
    "model": config.orchestrator.model,
    "system_prompt": system_prompt,            # hand-built at cli.py:390-408
    "permission_mode": config.orchestrator.permission_mode,
    "max_turns": config.orchestrator.max_turns,
    "agents": agent_defs,
    "allowed_tools": allowed_tools,
}
```

**Neither `setting_sources` nor `system_prompt={"type":"preset",...}` is set.**
A repo-wide grep for `setting_sources` / `settingSources` in cli.py returned
no matches. Consequence: when the generated project (at `cwd`) ends up
containing a `CLAUDE.md`, the V18 builder's Claude sessions will NOT pick it
up — the builder overrides `system_prompt` with its own hand-built value.

Codex's story is different. `codex_transport.create_codex_home()`
(codex_transport.py:124-182) copies `~/.codex/auth.json` / `installation_id` /
`config.toml` into a temp `CODEX_HOME` but **does NOT copy or synthesize an
`AGENTS.md` into the generated project's cwd**. `codex exec --cd <cwd>` is
invoked at codex_transport.py:565-575 — Codex will auto-load any
`AGENTS.md` that already exists under `cwd` or ancestor dirs, but the
builder does not write one. The generated project's Codex sessions
therefore also miss any builder-authored per-project instructions unless
something in the pipeline writes `<cwd>/AGENTS.md` before the first Codex
dispatch.

### Interaction with orchestrator's prompt injection

The builder's orchestrator `system_prompt` (cli.py:390-408) is a hand-built
string that already carries the heavyweight framing (convergence thresholds,
master plan file name, etc.). D-05 (config.py:857-863) fixed a prompt-injection
misfire where trusted framing was embedded in user-role messages as
`[SYSTEM: …]`; the fix moved the framing to the real system channel.
Consequence for Phase G:

- A `CLAUDE.md` at generated-project root would sit adjacent to — but not
  replace — the builder's hand-built orchestrator system prompt, **provided**
  Phase G flips `_build_options()` to use `system_prompt={"type":"preset",
  "preset":"claude_code"}` + `setting_sources=["project"]`. That switch would
  replace the hand-built prompt with Claude Code's own preset plus the
  project's `CLAUDE.md`, which would be a semantic shift, not a pure
  addition.
- An alternative is to read `CLAUDE.md` from disk and concatenate to
  `system_prompt_addendum` (cli.py:407-408) — that preserves the hand-built
  core and is the safer migration.

### Key distinction: CLI-level session constitution vs project-level ARCHITECTURE.md

These serve different purposes and should not be conflated:

- **`CLAUDE.md` / `AGENTS.md`** — **CLI-level session constitution**. Auto-loaded
  by the CLI / SDK at session start. Scope: coding conventions, safe /
  forbidden commands, where files live, how to run tests. Lifetime:
  stable across the entire run. Every LLM call in the session sees it.
- **`ARCHITECTURE.md`** (hypothetical new, project-level) — **per-project
  evolving document**. Would be written by the builder itself as milestones
  complete (like `STATE.json` / `MASTER_PLAN.json`), and would capture design
  decisions that accumulate. Lifetime: grows across milestones. Must be
  explicitly passed into wave prompts or auditor prompts (because auto-load
  only happens at CLI session start — and `ARCHITECTURE.md` would mutate
  mid-session).

What each should contain:

- `CLAUDE.md` (builder repo or generated-project): stable rules — where
  code lives, testids, i18n helpers, never-edit paths
  (`packages/api-client/*`), compile command, test command, lint command.
- `AGENTS.md` (at generated-project root or `apps/api`, `apps/web`): same
  content, Codex-flavored — these are what Codex auto-reads per the verbatim
  spec above, and Codex has strong adherence to AGENTS.md because it is
  trained to do so.
- `ARCHITECTURE.md` (builder-written, per-project): milestone-accreting
  record — entities created, endpoints exposed, design decisions, known
  limitations. Read by later milestones' wave prompts (like how
  `_load_dependency_artifacts()` currently loads Wave A/B/C JSON artifacts).

---

## Appendix A: Function → File:Line Reference Index

### wave_executor.py (4117 LOC)

| Symbol | Line |
|--------|------|
| `WaveFinding` dataclass | 49 |
| `WaveResult` dataclass (51 fields) | 65 |
| `WaveCheckpoint` | 127 |
| `CheckpointDiff` | 136 |
| `CompileCheckResult` | 145 |
| `_DeterministicGuardResult` | 156 |
| `_WaveWatchdogState` | 170 |
| `WaveWatchdogTimeoutError` | 256 |
| `MilestoneWaveResult` | 296 |
| `WAVE_SEQUENCES` constant | 307 |
| `_wave_sequence(template, config)` | 395 |
| `_get_resume_wave()` | 406 |
| `load_wave_artifact()` | 423 |
| `_save_wave_artifact()` | 435 |
| `_load_dependency_artifacts()` | 445 |
| `_load_milestone_scope()` | 462 |
| `save_wave_telemetry()` | 509 |
| `_derive_wave_t_status()` | 578 |
| `persist_wave_findings_for_audit()` | 609 |
| `_wave_t_max_fix_iterations()` | 1180 |
| `_wave_idle_timeout_seconds()` | 1188 |
| `_orphan_tool_idle_timeout_seconds()` | 1196 |
| `_wave_watchdog_poll_seconds()` | 1204 |
| `_wave_watchdog_max_retries()` | 1212 |
| `_sub_agent_idle_timeout_seconds()` | 1220 |
| `_invoke_wave_sdk_with_watchdog()` | 1427 |
| `_invoke_provider_wave_with_watchdog()` | 1509 |
| `_invoke_sdk_sub_agent_with_watchdog()` | 1592 |
| `_run_post_wave_e_scans()` | 1860 |
| `_run_wave_b_probing()` | 1965 |
| `_execute_wave_t()` | 2111 |
| `_execute_wave_sdk()` | 2502 |
| `_execute_wave_c()` | 2646 |
| `_detect_structural_issues()` | 2692 |
| `_run_wave_compile()` | 2768 |
| `_run_wave_b_dto_contract_guard()` | 2888 |
| `_run_wave_d_frontend_hallucination_guard()` | 2997 |
| `execute_milestone_waves()` (public entry) | 3120 |
| `_execute_milestone_waves_with_stack_contract()` | 3553 |
| Wave T dispatch (special case) | 3243-3260 |
| Per-wave compile gate + guards | 3295-3395 |
| Post-wave-E scans + test runners | 3466-3508 |

### cli.py (14305 LOC) — key sites

| Symbol | Line |
|--------|------|
| `_build_options()` (ClaudeAgentOptions builder) | 339 |
| Provider-routing init (Codex home + transport) | 3133-3203 |
| `import agent_team_v15.codex_transport as _codex_mod` | 3182 |
| `_execute_single_wave_sdk` (isolated path) | 3908 |
| `_execute_single_wave_sdk` (legacy path) | 4547 |
| `execute_milestone_waves(...)` invocation | 3995-4012 |
| `_run_milestone_audit()` | 5885 |
| `_run_audit_fix()` (legacy) | 6196 |
| `_run_audit_fix_unified()` | 6271 |
| `_run_patch_fixes()` (nested) | 6385 |
| Patch-mode `ClaudeSDKClient` spawn | 6441 |
| `_run_full_build()` (nested, subprocess escalation) | 6451 |
| Builder subprocess command | 6459-6481 |
| `_run_audit_loop()` | 6509 |
| AUDIT_REPORT.json resume guard | 6534-6571 |
| Audit fix invocation | 6640-6643 |
| Plateau detection | 6711-6721 |
| Final report write | 6744 |
| Confidence banner stamp | 6755-6795 |

### agents.py (9344 LOC)

| Symbol | Line |
|--------|------|
| `build_wave_a_prompt()` | 7750 |
| `build_wave_b_prompt()` | 7909 |
| `build_wave_e_prompt()` | 8147 |
| `WAVE_T_CORE_PRINCIPLE` | 8374 |
| `build_wave_t_prompt()` | 8391 |
| `build_wave_t_fix_prompt()` | 8596 |
| `build_wave_d_prompt()` | 8696 |
| `build_wave_d5_prompt()` | 8860 |
| `build_wave_prompt()` (dispatcher) | 9018 |
| Wave A dispatch | 9066 |
| Wave B dispatch | 9078 |
| Wave D dispatch | 9091 |
| Wave D5 dispatch | 9103 |
| Wave E dispatch | 9112 |
| Wave T dispatch | 9121 |
| Wave C short-circuit | 9131 |

### provider_router.py (504 LOC)

| Symbol | Line |
|--------|------|
| `WaveProviderMap` | 27 |
| `snapshot_for_rollback()` | 44 |
| `rollback_from_snapshot()` | 60 |
| `_normalize_code_style()` | 101 |
| `execute_wave_with_provider()` (public) | 149 |
| `_execute_claude_wave()` | 212 |
| `_execute_codex_wave()` | 240 |
| `_claude_fallback()` | 425 |
| `classify_fix_provider()` | 481 |

### codex_prompts.py (284 LOC)

| Symbol | Line |
|--------|------|
| `CODEX_WAVE_B_PREAMBLE` | 10 |
| `CODEX_WAVE_B_SUFFIX` | 159 |
| `CODEX_WAVE_D_PREAMBLE` | 180 |
| `CODEX_WAVE_D_SUFFIX` | 220 |
| `_WAVE_WRAPPERS` dict | 245 |
| `wrap_prompt_for_codex()` | 251 |

### codex_transport.py (760 LOC)

| Symbol | Line |
|--------|------|
| `CodexConfig` | 37 |
| `CodexResult` | 63 |
| `is_codex_available()` | 89 |
| `check_prerequisites()` | 94 |
| `create_codex_home()` | 124 |
| `cleanup_codex_home()` | 185 |
| `_parse_jsonl()` | 203 |
| `_compute_cost()` | 232 |
| `_execute_once()` | 549 |
| `execute_codex()` (public) | 687 |

### codex_appserver.py (692 LOC)

| Symbol | Line |
|--------|------|
| `CodexOrphanToolError` | 41 |
| `is_codex_available()` | 68 |
| `_OrphanWatchdog` | 117 |
| `_TokenAccumulator` | 183 |
| `_send_turn_interrupt()` | 226 |
| `_monitor_orphans()` | 263 |
| `_execute_turn()` | 311 |
| `_process_streaming_event()` | 525 |
| `execute_codex()` (public, same signature as legacy) | 634 |

### config.py — V18Config fields referenced

| Field | Line | Default |
|-------|------|---------|
| `scaffold_enabled` | 789 | False |
| `wave_d5_enabled` | 791 | True |
| `wave_idle_timeout_seconds` | 792 | 1800 |
| `orphan_tool_idle_timeout_seconds` | 793 | 600 |
| `wave_watchdog_poll_seconds` | 794 | 30 |
| `wave_watchdog_max_retries` | 795 | 1 |
| `sub_agent_idle_timeout_seconds` | 796 | 600 |
| `wave_t_enabled` | 802 | True |
| `wave_t_max_fix_iterations` | 803 | 2 |
| `provider_routing` | 806 | False |
| `codex_model` | 807 | "gpt-5.4" |
| `codex_timeout_seconds` | 808 | 5400 |
| `codex_max_retries` | 809 | 1 |
| `codex_reasoning_effort` | 810 | "high" |
| `codex_transport_mode` | 811 | "exec" |
| `codex_orphan_tool_timeout_seconds` | 812 | 300 |
| `codex_context7_enabled` | 814 | True |
| `provider_map_b` | 815 | "codex" |
| `provider_map_d` | 816 | "codex" |
| `milestone_scope_enforcement` | 823 | True |
| `audit_milestone_scoping` | 825 | True |
| `ownership_contract_enabled` | 833 | False |
| `spec_reconciliation_enabled` | 840 | False |
| `scaffold_verifier_enabled` | 845 | False |
| `m1_startup_probe` | 849 | True |
| `review_fleet_enforcement` | 856 | True |
| `recovery_prompt_isolation` | 863 | True |
| `cascade_consolidation_enabled` | 872 | False |
| `duplicate_prisma_cleanup_enabled` | 879 | False |
| `template_version_stamping_enabled` | 885 | False |
| `content_scope_scanner_enabled` | 894 | False |
| `audit_fix_iteration_enabled` | 902 | False |
| `mcp_informed_dispatches_enabled` | 910 | True |
| `runtime_infra_detection_enabled` | 920 | True |
| `confidence_banners_enabled` | 929 | True |
| `audit_scope_completeness_enabled` | 936 | True |
| `wave_b_output_sanitization_enabled` | 943 | True |

### state.py (751 LOC)

| Symbol | Line |
|--------|------|
| `RunState` (38 fields) | 20 |
| `RunState.finalize()` | 97 |
| `RunSummary` | 220 |
| `ConvergenceReport` | 236 |
| `StateInvariantError` | 335 |
| `count_test_files()` | 348 |
| `_reconcile_milestone_lists()` | 375 |
| `update_milestone_progress()` | 392 |
| `save_state()` | 521 |
| `load_state()` | 628 |
| `clear_state()` | 720 |

### audit_team.py (452 LOC)

| Symbol | Line |
|--------|------|
| `DEPTH_AUDITOR_MAP` | 46 |
| `get_auditors_for_depth()` | 55 |
| `_SCAN_AUDITOR_OVERLAP` | 66 |
| `should_skip_scan()` | 77 |
| `should_terminate_reaudit()` | 93 |
| `detect_convergence_plateau()` | 140 |
| `detect_regressions()` | 196 |
| `compute_escalation_recommendation()` | 228 |
| `_build_optional_suppression_block()` | 286 |
| `build_auditor_agent_definitions()` | 322 |

### audit_prompts.py (1526 LOC)

| Symbol | Line |
|--------|------|
| `AUDIT_PROMPTS` dict | 1361 |
| `_TECH_STACK_ADDITIONS` dict | 1377 |
| `get_auditor_prompt()` | 1457 |
| `get_scoped_auditor_prompt()` | 1500 |

### mcp_servers.py (561 LOC)

| Symbol | Line |
|--------|------|
| `_firecrawl_server()` | 24 |
| `_context7_server()` | 38 |
| `_sequential_thinking_server()` | 54 |
| `get_mcp_servers()` | 63 |
| `get_research_tools()` | 93 |
| `_BASE_TOOLS` | 114 |
| `recompute_allowed_tools()` | 149 |
| `contract_engine_is_deployable()` | 380 |
| `run_mcp_preflight()` | 429 |
| `ensure_contract_e2e_fidelity_header()` | 494 |

### fix_executor.py + fix_prd_agent.py

| Symbol | File | Line |
|--------|------|------|
| `_prepare_fix_plan()` | fix_executor.py | 28 |
| `execute_unified_fix()` (sync) | fix_executor.py | 187 |
| `execute_unified_fix_async()` | fix_executor.py | 312 |
| `_classify_fix_features()` | fix_executor.py | 444 |
| `classify_fix_feature_mode()` | fix_prd_agent.py | 180 |
| `generate_fix_prd()` | fix_prd_agent.py | 361 |

### Phase B / E / F auxiliaries

| Module | Key symbols |
|--------|-------------|
| `milestone_spec_reconciler.py:72` | `reconcile_milestone_spec()` |
| `scaffold_verifier.py:63` | `run_scaffold_verifier()` |
| `orphan_detector.py:32` | `OrphanToolDetector` (Claude-path mirror of Codex orphan detection) |
| `infra_detector.py:167` | `detect_runtime_infra()` |
| `infra_detector.py:241` | `build_probe_url()` |
| `confidence_banners.py:61` | `derive_confidence()` |
| `confidence_banners.py:257` | `stamp_all_reports()` |

### .mcp.json

`C:/Projects/agent-team-v18-codex/.mcp.json` (full body, 15 lines):

```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp@latest"],
      "env": { "CONTEXT7_API_KEY": "ctx7sk-..." }
    },
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    }
  }
}
```

---

## Appendix B: Context7 Query Results (verbatim)

### Query 1 — Claude Agent SDK (Python): CLAUDE.md auto-load behavior

Library ID: `/anthropics/claude-agent-sdk-python`
Query (verbatim): *"Does ClaudeSDKClient or ClaudeAgentOptions auto-load
CLAUDE.md from the repository root? How is CLAUDE.md or
.claude/instructions.md integrated into the system prompt?"*

Returned snippets (key excerpts):

> **Migration > From Claude Code SDK** —
> Source: https://github.com/anthropics/claude-agent-sdk-python/blob/main/README.md
>
> *When upgrading from the Claude Code SDK (versions < 0.1.0) to the Claude
> Agent SDK, several breaking changes and new features have been introduced.
> The primary configuration class has been renamed from `ClaudeCodeOptions`
> to `ClaudeAgentOptions`. System prompt configuration has been merged into
> the main options structure. The SDK now provides settings isolation with
> explicit control over agent behavior.*

(Context7's top results from `/anthropics/claude-agent-sdk-python` did NOT
mention `setting_sources` / `CLAUDE.md` auto-load directly — that detail was
only found under `/websites/code_claude`, quoted in §8 above.)

### Query 2 — Claude Code: CLAUDE.md memory auto-load

Library ID: `/websites/code_claude`
Query (verbatim): *"CLAUDE.md memory auto-load on startup from repo root,
project memory, ~/.claude/CLAUDE.md, precedence order for memory files and
instruction files"*

Returned snippets (verbatim, quoted in §8):

> **Load CLAUDE.md project instructions** —
> Source: https://code.claude.com/docs/en/agent-sdk/python
> ```python
> async for message in query(
>     prompt="Add a new feature following project conventions",
>     options=ClaudeAgentOptions(
>         system_prompt={"type": "preset", "preset": "claude_code"},
>         setting_sources=["project"],
>         allowed_tools=["Read", "Write", "Edit"],
>     ),
> ):
>     print(message)
> ```

> **Explore the .claude directory > CLAUDE.md** —
> Source: https://code.claude.com/docs/en/claude-directory
>
> *CLAUDE.md is a project-specific instruction file that is loaded into the
> context at the start of every session. It allows developers to define
> conventions, common commands, and architectural context to ensure
> consistent behavior. It is recommended to keep this file under 200 lines
> to maintain high adherence, and it can be placed in the project root or
> within the .claude directory.*

> **CLAUDE.md load locations** —
> Source: https://code.claude.com/docs/en/agent-sdk/claude-code-features
>
> *CLAUDE.md files are loaded from various locations including the project
> root, parent directories, subdirectories, and user-specific paths. These
> levels are additive, meaning the agent can access multiple files
> simultaneously. Because there is no hard precedence rule, it is
> recommended to write non-conflicting instructions or explicitly state
> precedence within the files themselves.*

> **CLAUDE.md with Import Syntax** —
> Source: https://code.claude.com/docs/en/best-practices
> ```markdown
> See @README.md for project overview and @package.json for available npm commands.
>
> # Additional Instructions
> - Git workflow: @docs/git-instructions.md
> - Personal overrides: @~/.claude/my-project-instructions.md
> ```

### Query 3 — Codex CLI: AGENTS.md auto-load behavior

Library ID: `/openai/codex`
Query (verbatim): *"Does codex CLI automatically read AGENTS.md or codex.md
from the working directory when running codex exec? What files are
auto-loaded as context or instructions? Where do AGENTS.md/codex.md files go?"*

Returned snippets (verbatim):

> **AGENTS.md spec** —
> Source: https://github.com/openai/codex/blob/main/codex-rs/core/gpt_5_1_prompt.md
>
> *Repositories often contain `AGENTS.md` files, which can be located
> anywhere within the repository. These files serve as a mechanism for
> humans to provide instructions or tips to the agent for working within
> the container, such as coding conventions, information about code
> organization, or instructions on how to run or test code. The scope of
> an `AGENTS.md` file encompasses the entire directory tree rooted at the
> folder containing it. For every file modified in the final patch, the
> agent must adhere to instructions in any `AGENTS.md` file whose scope
> includes that file. Instructions regarding code style, structure, or
> naming apply only within the `AGENTS.md` file's scope, unless explicitly
> stated otherwise. In cases of conflicting instructions, more-deeply-nested
> `AGENTS.md` files take precedence, while direct system, developer, or
> user instructions (as part of a prompt) override `AGENTS.md`
> instructions. The contents of the `AGENTS.md` file at the root of the
> repo and any directories from the Current Working Directory (CWD) up to
> the root are automatically included with the developer message,
> eliminating the need for re-reading. However, when working in a
> subdirectory of CWD or a directory outside CWD, the agent should check
> for any applicable `AGENTS.md` files.*

> **Codex CLI > AGENTS.md spec** —
> Source: https://github.com/openai/codex/blob/main/codex-rs/models-manager/prompt.md
>
> *AGENTS.md files allow humans to provide specific instructions or tips
> to the coding agent within a repository. These files can cover coding
> conventions, organizational details, or testing instructions and apply
> to the directory tree where they are located. When multiple files exist,
> more deeply nested AGENTS.md files take precedence in case of conflicting
> instructions. However, direct system or user prompts always override the
> instructions found in these files.*

---

## Surprises (flagged for Phase G design)

1. **`v18.codex_transport_mode` is declared but never consumed.** Production
   code path at cli.py:3182 hard-codes `agent_team_v15.codex_transport` (the
   legacy subprocess). The Phase E `codex_appserver.py` (JSON-RPC + `turn/
   interrupt` + richer event pairing) is reachable only via direct callers
   (tests + `provider_router.py:263` importing the exception type). If Phase G
   assumes the app-server path is active by default, add the transport
   selector at cli.py:3182.

2. **`setting_sources=["project"]` is never set in `_build_options()`.** The
   builder's Claude sessions will NOT auto-load any `CLAUDE.md` placed in
   the generated project. The repo itself has no `CLAUDE.md` at root either.

3. **`classify_fix_provider()` (provider_router.py:481) is exported but
   never called.** The infrastructure to route fixes to Codex is written;
   only the call site is missing. This is a one-line change at cli.py:6441
   (plus wiring the Codex transport into the fix options).

4. **Wave T hard-bypasses `provider_routing`** (wave_executor.py:3244-3260).
   This is intentional per the comment, but worth calling out: any Phase G
   design that assumes "one provider dispatch per wave letter" must special-
   case T.

5. **D5 forces Claude regardless of caller's map** (provider_router.py:39-41).
   Same category as #4 — intentional, documented, but load-bearing for
   merge-design.

6. **No `MILESTONE_HANDOFF.md` writer/reader was found.** The brief asked for
   this specifically; cross-milestone data flows exclusively through wave
   artifact JSONs + `STATE.json`. If Phase G expects such a file, it does
   not currently exist.

7. **No project-level cumulative architecture document exists.** The closest
   approximations are per-milestone `resolved_manifest.json` (only when
   `spec_reconciliation_enabled` is ON, which defaults OFF at config.py:840)
   and the hand-written repo-root `ARCHITECTURE_REPORT.md` (not builder-
   written).

8. **Fix prompt repeatedly inlines the entire `task_text`** (the whole PRD)
   at cli.py:6428. Under 1M context this is cheap; under smaller context
   windows this plus `_ANTI_BAND_AID_FIX_RULES` plus the feature block can
   be a surprisingly large portion of the budget.

9. **`_n17_prefetch_cache`** (cli.py:3976) is per-milestone, per-wave
   (B & D only). If Phase G wants Context7 idiom docs available to the audit
   or fix path, that cache must be broadened.
