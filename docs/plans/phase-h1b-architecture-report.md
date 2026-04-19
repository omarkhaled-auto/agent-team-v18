# Phase H1b — Architecture Blueprint (Wave A ARCHITECTURE.md Schema + Validator + Retry + Auditor Injection)

> Branch: `phase-h1b-wave-a-architecture-md-schema` cut from `integration-2026-04-15-closeout` @ `d2ce167` (post-h1a merge).
> Author: `discovery-agent` (Wave 1, Phase H1b).
> Companions: `phase-h1b-discovery-citations.md` (line-anchored proofs), `phase-h1b-allowlist-evidence.md` (section allowlist + ALLOWED_REFERENCES).

## Overview

Phase H1a shipped downstream enforcement against Wave A's freeform `.agent-team/milestone-{id}/ARCHITECTURE.md`. h1b closes the loop upstream: it prevents Wave A from emitting a drifted or fabricated handoff in the first place via (1) a deterministic schema, (2) a validator that runs at Wave-A-completion, (3) a retry loop that funnels violations back through the existing `stack_contract_rejection_context` / `[PRIOR ATTEMPT REJECTED]` channel, (4) a `GateEnforcementError`-based escalation that mirrors `_enforce_gate_a5` exactly. Wave 2B also wires a three-way compare into one or more auditor prompts plus structured emission for h1a pattern codes that currently escape as raw strings. All line numbers verified at h1b HEAD.

---

## Section 1A — Wave A prompt structure (exact)

### Signature

`build_wave_a_prompt` at `src/agent_team_v15/agents.py:8132-8144`. Keyword-only args:
- `milestone: Any` (carries `.id`, `.feature_refs`, `.ac_refs`, `.parallel_group`, `.merge_surfaces`)
- `ir: Any` (Product IR)
- `dependency_artifacts: dict[str, dict[str, Any]] | None` (predecessor milestones' outputs)
- `scaffolded_files: list[str] | None`
- `config: AgentTeamConfig | None`
- `existing_prompt_framework: str` (caller-supplied base: stack contract summary, PRD excerpt, Phase-A/B headers)
- `cwd: str | None = None`
- `stack_contract: dict[str, Any] | None = None`
- `stack_contract_rejection_context: str = ""` — **load-bearing** for h1b retry plumbing
- `mcp_doc_context: str | None = None`

### Section order (exact, from the `parts: list[str]` accumulator at `agents.py:8191-8329`)

1. Optional `[PROJECT ARCHITECTURE]` block (cumulative repo-root ARCHITECTURE.md, `:8192-8200`) — injected when `v18.architecture_md_enabled=True` AND the file exists with at least one prior-milestone section.
2. `existing_prompt_framework` (caller-supplied base), `:8201`.
3. Optional stack contract block (`stack_contract_block`), `:8202-8206`.
4. Optional `<framework_idioms>` XML block (MCP doc-context pre-fetch), `:8210-8220`, gated on `v18.mcp_doc_context_wave_a_enabled`.
5. `[WAVE A - SCHEMA / FOUNDATION SPECIALIST]` + `[YOUR TASK]`, `:8221-8227`.
6. `[SCAFFOLDED FILES - START HERE]`, `:8228-8229`.
7. `[ENTITIES TO CREATE FOR THIS MILESTONE]` (from `_select_ir_entities`), `:8231-8232`.
8. `[MILESTONE ACCEPTANCE CRITERIA]` + AC-field-implication teaching, `:8234-8240`.
9. `[EXISTING ENTITY EXAMPLES IN THIS REPO - MIRROR THESE PATTERNS]` (backend_context paths), `:8242-8248`.
10. Optional `[DEPENDENCY ARTIFACTS - REFERENCE ONLY, DO NOT RECREATE]`, `:8252-8257`.
11. `[DOWNSTREAM HANDOFF - WAVE B CONSUMES WHAT YOU PRODUCE]` (Schema Handoff shape), `:8260-8271`.
12. `[OUTPUT STRUCTURE]` — required top-level Markdown headers (`## Migrations` / `## Entities` / `## Relationships` / `## Schema Handoff`), `:8273-8280`.
13. Optional stack contract block re-inclusion, `:8282-8286` (yes, twice; legacy — benign).
14. Optional `[PRIOR ATTEMPT REJECTED]` block, `:8287-8292`. **THIS IS THE CHANNEL h1b'S RETRY MUST FUNNEL SCHEMA REJECTIONS THROUGH.**
15. `[RULES]` block — general constraints, `:8293-8310`.
16. Optional `[PER-MILESTONE ARCHITECTURE HANDOFF — MUST]` — the "write `.agent-team/milestone-{id}/ARCHITECTURE.md`" directive, `:8318-8328`. Flag-gated on `v18.architecture_md_enabled`.

The final prompt is a single newline-joined string; `check_context_budget(result, label="wave A prompt (...)")` enforces context fitness.

### Call chain

`build_wave_a_prompt` → regular dispatch at `wave_executor.py:4480-4504` (via `build_wave_prompt=...` callback): single `await _execute_wave_sdk(...)` call at `:4514-4522`. `_execute_wave_sdk` itself lives at `wave_executor.py:2814-2823` and dispatches to either the Codex provider path or the Claude fallback in a single SDK turn (not multi-turn). Existing single-retry on stack-contract violations lives at `:4783-4808`, already using `wave_a_retry_count < 1` as the cap and already wiring feedback through `wave_a_rejection_context → stack_contract_rejection_context`.

The A.5 gate-rerun loop is the SEPARATE, later retry path at `:4375-4425` (`while True: ... _enforce_gate_a5 ... break`). **h1b schema gate must hook on the Wave A path itself (post-SDK, pre-Scaffold), NOT stack the retry on top of A.5.**

### Existing validation on Wave A output (pre-h1b)

1. `WAVE_A_CONTRACT_CONFLICT.md` presence check at `wave_executor.py:4707-4714` — if Wave A wrote the conflict file, `wave_result.success = False`.
2. Ownership forbidden-writes check at `wave_executor.py:4716-4751` — h1a's `check_wave_a_forbidden_writes`.
3. Stack contract violation retry at `wave_executor.py:4783-4808` — re-runs Wave A once on CRITICAL stack-contract violations, funneling through `wave_a_rejection_context`.
4. Schema-handoff parsing (Wave B at `agents.py:8376+` parses Wave A's text for entity_files / migrations / etc).

**No existing schema validation on the `.agent-team/milestone-{id}/ARCHITECTURE.md` file itself.** h1b fills that gap.

---

## Section 1C — Auditor prompt sites

### Registry (8 constants, static strings)

`AUDIT_PROMPTS` at `src/agent_team_v15/audit_prompts.py:1386-1395`:
1. `"requirements"` → `REQUIREMENTS_AUDITOR_PROMPT`
2. `"technical"` → `TECHNICAL_AUDITOR_PROMPT` (defined `:358`)
3. `"interface"` → `INTERFACE_AUDITOR_PROMPT` (defined `:394`)
4. `"test"` → `TEST_AUDITOR_PROMPT`
5. `"mcp_library"` → `MCP_LIBRARY_AUDITOR_PROMPT`
6. `"prd_fidelity"` → `PRD_FIDELITY_AUDITOR_PROMPT`
7. `"comprehensive"` → `COMPREHENSIVE_AUDITOR_PROMPT`
8. `"scorer"` → `SCORER_AGENT_PROMPT`

### Injection / render sites (CORRECTION to dispatch plan)

The plan said "target cli.py renderers at ~1482 / ~1559, NOT audit_prompts.py constants." **At h1b HEAD, the renderers `get_auditor_prompt` and `get_scoped_auditor_prompt` live in `audit_prompts.py` — NOT cli.py.** Exact lines:

- `get_auditor_prompt(auditor_name, requirements_path=None, prd_path=None, tech_stack=None) -> str` at `audit_prompts.py:1482-1522`. Reads `AUDIT_PROMPTS[auditor_name]`, substitutes `{requirements_path}` / `{prd_path}`, appends `_TECH_STACK_ADDITIONS` when tech_stack is provided.
- `get_scoped_auditor_prompt(auditor_name, *, scope=None, config=None, ...)` at `audit_prompts.py:1559-1589`. Calls `get_auditor_prompt(...)`, applies Wave T.5 gap-rule conditionally (Slice 5e), then `build_scoped_audit_prompt_if_enabled(base, scope, config)` for C-01 scope preamble.

`cli.py` does not render auditor prompts at h1b HEAD. The consumer files are:
- `audit_team.py:35`: `from .audit_prompts import AUDIT_PROMPTS, get_auditor_prompt, get_scoped_auditor_prompt`.
- `audit_agent.py`: dispatch wrapper. `max_turns=1` is hard-coded at `audit_agent.py:83`. Auditor-agent (Wave 2B) **does NOT edit `audit_agent.py`** — the plan's constraint holds.

**This is not a HALT** — auditor-agent (Wave 2B) will edit `audit_prompts.py` at `:1482` and `:1559` (not cli.py). The line numbers match by coincidence; the file is different.

### Max-turns constraint

`audit_agent.py:81-86` instantiates `ClaudeAgentOptions(model=..., max_turns=1, ...)`. The auditor cannot chain multi-turn SDK calls; any three-way compare must be expressed as a SINGLE-TURN prompt with the three artifacts pre-rendered inline. Auditor-agent designs the compare as a prompt-side instruction: "Compare the following three inputs: (A) ARCHITECTURE.md contents, (B) REQUIREMENTS.md DoD port, (C) resolved scaffold port. Report any mismatch as a structured finding."

### Which auditor(s) should gain three-way compare

- **INTERFACE_AUDITOR_PROMPT** (`audit_prompts.py:394`) — owns port-drift / API-surface consistency checks. Three-way compare anchors: `apps/api/src/main.ts` `app.listen(...)` port, `docker-compose.yml` `services.api.ports[0]`, and `.agent-team/milestones/{id}/REQUIREMENTS.md` DoD port. This is the PORT triad that smoke #11 drifted on.
- **TECHNICAL_AUDITOR_PROMPT** (`audit_prompts.py:358`) — owns architecture-drift checks. Three-way compare anchors: Wave A's `.agent-team/milestone-{id}/ARCHITECTURE.md`, resolved `StackContract`, and Phase G Slice 5a cumulative ARCHITECTURE.md (repo-root). Catches "Wave A claims NestJS, stack contract says NestJS 11, but ARCHITECTURE.md describes Express".

Recommend **INTERFACE** (port-drift) as the first three-way insertion (highest ROI — directly catches the h1a smoke #11 defect class). **TECHNICAL** is the second-priority insertion. Auditor-agent chooses the exact wording — the plan directive is "add 3-way compare to INTERFACE and optionally TECHNICAL; do not touch other auditors."

### `audit_agent.py` — NO EDITS

`audit_agent.py` is the dispatch wrapper (Claude SDK caller). Auditor-agent does not touch it unless a wiring gap surfaces. No gap observed at h1b HEAD — `get_scoped_auditor_prompt` is already the single render entry point via `audit_team.py:35`.

---

## Section 1D — Per-milestone ARCHITECTURE.md injection pattern

### Helper

`_load_per_milestone_architecture_block(cwd, milestone_id, v18_cfg) -> str` at `src/agent_team_v15/agents.py:8051-8083`.

Signature — all positional:
- `cwd: str | None`
- `milestone_id: str`
- `v18_cfg: Any`

Returns a ready-to-emit `<architecture>\n{content}\n</architecture>` XML block when:
- `cwd` is truthy AND
- `v18_cfg.architecture_md_enabled` is truthy AND
- `milestone_id` is non-empty and not `"milestone-unknown"` AND
- `<cwd>/.agent-team/milestone-{milestone_id}/ARCHITECTURE.md` exists AND
- file body is non-empty after `.strip()`.

Otherwise returns `""` (empty string). Flag-off byte-identical behavior preserved.

**Path anchor:** `.agent-team/milestone-{milestone_id}/ARCHITECTURE.md`. Because `milestone_id` is formatted as e.g. `"milestone-1"`, the on-disk directory is literally `.agent-team/milestone-milestone-1/`. Confirmed against preserved smokes.

### Call sites (4 downstream waves)

| Wave | File | Line |
|---|---|---|
| Wave B | `src/agent_team_v15/agents.py` | `:8407-8421` (`_arch_xml_b = _load_per_milestone_architecture_block(...)`; `parts.extend([_arch_xml_b, ""])`) |
| Wave D | `src/agent_team_v15/agents.py` | `:9274-9278` |
| Wave T | `src/agent_team_v15/agents.py` | `:8929-8934` |
| Wave E | `src/agent_team_v15/agents.py` | `:8664-8667` |

### Auditor injection point (h1b — auditor-agent Wave 2B)

Auditor prompts do not today load the per-milestone ARCHITECTURE.md. h1b's three-way-compare wiring adds injection at either:
- **Inside `get_scoped_auditor_prompt` at `audit_prompts.py:1559-1589`** — read the ARCHITECTURE.md via `_load_per_milestone_architecture_block`-equivalent (or a new helper that takes `scope.milestone_id`), append as `<architecture_handoff>...</architecture_handoff>` block to the rendered prompt BEFORE the scope-wrapper application. Flag-gate via new `v18.audit_architecture_injection_enabled` (default OFF). Only apply to `{"interface", "technical"}` auditors — other auditors get unchanged prompts.
- Alternative: inside `audit_team.py` where the scope object is constructed. This is called ONCE per audit run, so it's the right flag-gate boundary.

Either site is correct; auditor-agent picks. The schema is: if the flag is on AND the auditor name is in the 3-way-compare subset AND ARCHITECTURE.md exists, inject the `<architecture_handoff>` block. Otherwise emit unchanged prompt (byte-identical flag-off path).

Writers of the ARCHITECTURE.md file on disk: Wave A (this is what h1b is actually about).

---

## Section 1E — Structured finding emission sites for h1a patterns

### h1a pattern IDs and current emission shape

| Pattern ID | Emits from | Current shape |
|---|---|---|
| `SCAFFOLD-COMPOSE-001` | `scaffold_verifier.py:212` | **String** appended to `summary` list on `ScaffoldVerifierReport`. Surfaces as log line, NOT as `WaveFinding`. |
| `SCAFFOLD-PORT-002` | `scaffold_verifier.py:201` | **String** in `summary`. Same shape as above. |
| `PROBE-SPEC-DRIFT-001` | `endpoint_prober.py:1095-1111` + `endpoint_prober.py:728-732` | **Exception class** `ProbeSpecDriftError`; also emitted as `DockerContext.startup_error` string. NOT a `WaveFinding`. |
| `OWNERSHIP-DRIFT-001` | `ownership_enforcer.py:310, 435` | **Structured** `Finding` dataclass. Converted to `WaveFinding` via the wave_executor hook sites. |
| `OWNERSHIP-WAVE-A-FORBIDDEN-001` | `ownership_enforcer.py:361-373` | **Structured** `Finding`. Converted at `wave_executor.py:4737-4746`. |
| `DOD-FEASIBILITY-001` | `dod_feasibility_verifier.py:276` | **Structured** `Finding`. |
| `RUNTIME-TAUTOLOGY-001` | `cli.py:239, 251, 263, 268` | **String** returned from `_runtime_tautology_guard`. Printed / logged. Not a `WaveFinding`. |

### Post-Wave-E scanners (Phase F — the pattern to copy)

`_run_post_wave_e_scans(cwd: str) -> list[WaveFinding]` at `wave_executor.py:2024-2075`. Each scanner yields `Violation` objects (from `quality_checks.py` — the struct dataclass at `quality_checks.py:95`); adapter `_violation_to_finding(...)` at `wave_executor.py:2137-2150` maps them to `WaveFinding`. Severity map: `error → HIGH`, `warning → MEDIUM`, `info → LOW`, `critical → HIGH`. `WIRING-CLIENT-001` at `quality_checks.py:8220` is the exemplar: `check="WIRING-CLIENT-001",` in a `Violation` constructor.

### h1b's structured-emission work (auditor-agent Wave 2B)

**Do NOT refactor `scaffold_verifier.py` / `endpoint_prober.py` / `cli._runtime_tautology_guard` to stop emitting strings.** The strings are the current user-visible channel; ripping them out would regress logs.

**DO add structured emission AT THE WAVE HOOK SITES** where the string output is consumed, wrapping it as a `WaveFinding` and appending to `wave_result.findings`. Specifically:

1. **Scaffold verifier — SCAFFOLD-COMPOSE-001 + SCAFFOLD-PORT-002:** at `wave_executor.py:4194-4212` (the `_maybe_run_scaffold_verifier` call site). Parse `report.summary_lines` looking for the `SCAFFOLD-COMPOSE-001` / `SCAFFOLD-PORT-002` tokens; emit a `WaveFinding` per match with severity HIGH. The malformed-tuple list already carries the diagnostic string — read it directly, do not re-parse.
2. **Endpoint prober — PROBE-SPEC-DRIFT-001:** at `wave_executor.py:3920-3944` (the `_run_wave_b_probing` call site). Catch `ProbeSpecDriftError` (already raised at `endpoint_prober.py:1188`); construct a `WaveFinding(code="PROBE-SPEC-DRIFT-001", severity="HIGH", file=str(drift.requirements_path), message=...)` and append.
3. **Runtime tautology — RUNTIME-TAUTOLOGY-001:** at `cli.py:13662-13674` (the existing tautology-guard call site from h1a's 1E). When the guard returns a non-None string, wrap it into a `WaveFinding` and thread it into the `persist_wave_findings_for_audit` block at `wave_executor.py:4834-4840`.

**Pattern:** none of these require editing the emitter file (scaffold_verifier.py / endpoint_prober.py / cli.py helper). They all happen at the wave-executor consumer boundary using `_violation_to_finding` / `_stack_violation_to_finding`-style adapter helpers. Auditor-agent writes three small adapters (`_scaffold_summary_to_findings`, `_probe_drift_to_finding`, `_runtime_tautology_to_finding`) in `wave_executor.py` and calls them at the three hook sites above.

---

## Section 1F — Retry and escalation pattern (reuse _enforce_gate_a5 exactly)

### MIRROR TABLE — A.5 gate vs h1b schema gate

| Component | Wave A.5 (existing) | Wave A schema gate (h1b) |
|---|---|---|
| Gate function | `_enforce_gate_a5(*, config, cwd, milestone_id, rerun_count) -> (should_rerun, critical_findings)` at `cli.py:9902-9953` | Shipped as `_enforce_gate_wave_a_schema(*, config, cwd, milestone_id, rerun_count) -> (should_rerun, review_dict)` at `cli.py:10136-10139+`. Same keyword-only shape; returns the full review dict (not just critical findings) so the caller can render schema feedback. Lives in `cli.py` next to `_enforce_gate_a5`. |
| Fixture JSON | `.agent-team/milestones/{id}/WAVE_A5_REVIEW.json` (loader at `cli.py:9872-9884`) | NEW `.agent-team/milestones/{id}/WAVE_A_SCHEMA_REVIEW.json` (new loader `_load_wave_a_schema_review` — identical shape to `_load_wave_a5_review`). |
| Feedback formatter | `_format_plan_review_feedback(findings: list[dict[str, Any]]) -> str` at `wave_executor.py:3093` — emits `[PLAN REVIEW FEEDBACK]` text | Shipped as `_format_schema_rejection_feedback(review, *, rerun_count, max_reruns) -> str` at `cli.py:10100+` — emits `[SCHEMA FEEDBACK]` text with the same `[<category>] <ref>` bullet shape. **Note the file split:** `_format_plan_review_feedback` lives in `wave_executor.py` co-located with the A.5 retry loop; `_format_schema_rejection_feedback` lives in `cli.py` co-located with `_enforce_gate_wave_a_schema` — each formatter sits next to the gate consumer that renders it, so the two live in different files by design. |
| Feedback channel | `stack_contract_rejection_context` kwarg on `build_wave_a_prompt` (`agents.py:8142`) → renders as `[PRIOR ATTEMPT REJECTED]` block (`agents.py:8287-8292`) | **SAME CHANNEL** — concatenate `[SCHEMA FEEDBACK]` text into `stack_contract_rejection_context` as a second paragraph. The `[PRIOR ATTEMPT REJECTED]` block carries BOTH A.5 findings AND schema findings when both fire. Do NOT create a parallel `[SCHEMA REJECTION]` block. |
| Retry loop | `while True:` at `wave_executor.py:4375-4425` — wraps A.5 dispatch | NEW `while True:` wrapping Wave A dispatch (the regular Wave A path at `wave_executor.py:4477-4504`). The existing single-retry at `:4783-4808` (`wave_a_retry_count < 1`) handles the stack-contract CRITICAL case; the new schema retry loop handles the ARCHITECTURE.md-schema-violation case. **Design decision:** the h1b schema retry replaces the ad-hoc single-retry by promoting it to a generalized while-loop driven by `_enforce_gate_a_schema` (same pattern as A.5). |
| Rerun budget | `wave_a5_max_reruns: int = 1` at `config.py:873`; coerced at `config.py:2805-2807` | Shipped as **Option 2 (Add + alias)** per team-lead authorization, overriding discovery's Option 1 recommendation. Canonical key: `wave_a_rerun_budget: int = 2` at `config.py:885`. Legacy `wave_a5_max_reruns` is kept as a deprecated alias — when set to a non-default value, `_get_effective_wave_a_rerun_budget` (`cli.py:10020`) forwards it as the effective budget and emits a `DeprecationWarning` (once per source location via Python's `warnings` module — no module-global dedupe sets). Both `_enforce_gate_wave_a_schema` and `_enforce_gate_a5` read the budget through the same resolver, preserving the shared-budget invariant. |
| Gate flag | `wave_a5_gate_enforcement: bool = False` at `config.py:870` | Shipped as `wave_a_schema_enforcement_enabled: bool = False` at `config.py:884`. Separate flag so the schema validator can roll out independently of A.5 gate enablement. |
| Auditor injection flag | (n/a for A.5) | Shipped as `auditor_architecture_injection_enabled: bool = False` at `config.py:804`. Gates per-milestone ARCHITECTURE.md XML injection into the INTERFACE + TECHNICAL auditor prompts plus the `<three_way_compare>` directive. |
| Exhaustion signal | `raise GateEnforcementError(..., gate="A5", milestone_id=..., critical_count=...)` | `raise GateEnforcementError(..., gate="A-SCHEMA", milestone_id=..., critical_count=...)` — same class, different `.gate` string. Existing catch sites branch on `.gate` already. |

### SCHEMA-GATE-FIRST ORDERING

Sequence within the Wave A dispatch block at `wave_executor.py:4477+`:
1. Dispatch Wave A via `_execute_wave_sdk` (existing code path).
2. Ownership + contract-conflict checks (existing, `:4707-4751`).
3. **NEW: schema validator runs on `.agent-team/milestone-{id}/ARCHITECTURE.md`.** Persist findings to `WAVE_A_SCHEMA_REVIEW.json`.
4. Call `_enforce_gate_a_schema(config, cwd, milestone_id, rerun_count=schema_rerun)`:
   - `(False, [])` → continue to Wave A.5 (unchanged).
   - `(True, findings)` → format `[SCHEMA FEEDBACK]`, concat into `wave_a_rejection_context`, continue loop → re-dispatch Wave A.
   - `raise GateEnforcementError(gate="A-SCHEMA")` → propagates to milestone boundary.
5. Stack-contract violation single-retry (existing, `:4783-4808`) — BUT refactored to share the same rerun budget. If schema gate already consumed the 1 allowed rerun, stack-contract CRITICAL goes straight to `success=False` with no additional rerun.
6. A.5 dispatch + `_enforce_gate_a5` retry loop (existing, `:4375-4425`) — **UNCHANGED** path-wise; behavior unchanged because A.5's rerun budget is the same shared `wave_a5_max_reruns`.

**Budget arithmetic:** with the shipped default `wave_a_rerun_budget=2` (canonical), up to two Wave A reruns are available across all three gates. Priority: schema → stack-contract → A.5. If schema fails and consumes the rerun, stack-contract and A.5 findings surface as `GateEnforcementError` on first failure (no further reruns). When a legacy `wave_a5_max_reruns` value is present, `_get_effective_wave_a_rerun_budget` forwards it as the effective budget and emits `DeprecationWarning`.

**Rejection-feedback concatenation rule:** when multiple gates fire in the same rerun, the `[PRIOR ATTEMPT REJECTED]` block body is a concatenation of `[SCHEMA FEEDBACK]`, `[STACK CONTRACT VIOLATIONS]`, and `[PLAN REVIEW FEEDBACK]` sub-blocks separated by blank lines. Format helpers MUST preserve this ordering so Wave A sees the same sub-block order deterministically.

### GateEnforcementError definition + catch

`class GateEnforcementError(RuntimeError)` at `cli.py:9837-9869` — carries `.gate`, `.milestone_id`, `.critical_count`. Caught by the orchestrator main loop (grep `except GateEnforcementError` to find the exact handler — existing catch handles `gate ∈ {"A5", "T5"}`; h1b adds `"A-SCHEMA"` to the set). Handler behavior: log + abort the milestone cleanly (do NOT propagate to full-pipeline crash).

### NO NEW INFRASTRUCTURE

h1b must NOT introduce:
- New persistence layer (reuse `.agent-team/milestones/{id}/WAVE_A_SCHEMA_REVIEW.json` analog of `WAVE_A5_REVIEW.json`).
- New state-coupling (no touching `state.py`).
- New escalation mechanism (reuse `GateEnforcementError`).
- New rejection-feedback block (reuse `[PRIOR ATTEMPT REJECTED]`).
- New rerun-budget knob beyond the shipped `wave_a_rerun_budget` canonical + `wave_a5_max_reruns` alias pair (Option 2). All three gates share a single effective budget via `_get_effective_wave_a_rerun_budget`.

Any deviation from this mirror = HALT.

### Section header for schema-agent

> **Schema gate mirrors A.5 exactly — reuse, don't rebuild.**
> The validator writes `WAVE_A_SCHEMA_REVIEW.json`. The gate function is a copy of `_enforce_gate_a5` with a different file path. The feedback formatter is a copy of `_format_plan_review_feedback` with a different block header. The retry loop reuses `wave_a5_max_reruns`. The escalation is the same `GateEnforcementError` class with `gate="A-SCHEMA"`. No new config knobs. No new persistence layout. No new escalation class. If you are writing more than ~150 LOC for the gate + formatter + loader, you are duplicating something — stop and re-read `_enforce_gate_a5`.

---

## Section 1G — Existing tests to pattern-match

| Target | Test file | Why copy |
|---|---|---|
| `_enforce_gate_a_schema` | `tests/test_gate_enforcement.py:62-200+` — `test_gate_8_noop_when_enforcement_disabled`, `test_gate_8_passes_on_pass_verdict`, etc. | Direct `_cli._enforce_gate_a5(config=..., cwd=..., milestone_id="M1", rerun_count=0)` over seeded JSON fixtures via `_seed_a5_review(tmp_path, "M1", {...})`. Copy verbatim: fixtures become `_seed_schema_review`, calls become `_cli._enforce_gate_a_schema`. |
| Wave A prompt rendering | `tests/test_mcp_doc_context_wave_a.py`, `tests/test_architecture_wave_a_must.py` | Direct `build_wave_a_prompt(milestone=..., ir=..., config=..., existing_prompt_framework="...")`. Assert the rendered text contains/excludes specific headers. For h1b: assert `[SCHEMA FEEDBACK]` appears inside `[PRIOR ATTEMPT REJECTED]` when `stack_contract_rejection_context` carries the concatenated block. |
| Wave A section ownership (H1a analog) | `tests/test_h1a_wave_b_prompt_compose_directive.py` | Assert a specific block appears/does not appear in the rendered prompt. For h1b schema: assert the validator-rejection-text-mentions-section-names pattern. |
| Structured finding emission | `tests/test_h1a_ownership_enforcer.py` | Workspace fixtures, check emitted `Finding` objects have expected code/severity/message. Copy shape for `WaveFinding` adapter tests in Wave 2B's auditor work. |
| Audit prompt rendering | `tests/test_audit_prompts.py:43-250+`, `tests/test_audit_scope_wiring.py` | `test_contains_scope_section` pattern. For h1b 3-way compare: assert the rendered interface/technical auditor prompt contains `<architecture_handoff>` when the flag is on AND the file exists; does NOT contain it when flag is off. |

---

## Section 1H — HALT points

**None at this stage.** The plan's assumption that renderers live in `cli.py` was incorrect; the correct site is `audit_prompts.py:1482` / `1559`. This is a plan-dispatch correction, not a HALT — auditor-agent edits the correct files with no change to scope.

Other non-HALT caveats discovery-agent flags:

1. **Rerun budget design shipped as Option 2 (Add + alias), overriding discovery's Option 1 recommendation.** Team-lead authorized Option 2 at dispatch time; discovery had recommended reusing `wave_a5_max_reruns` literally (Option 1). Rationale for the override: (a) no silent default-change for existing configs — `wave_a5_max_reruns` is still honored via the deprecation-warned alias path; (b) new operators write the canonical name `wave_a_rerun_budget`; (c) budget goes from 1→2 only when operators opt into the new key, so legacy smokes reproduce bit-for-bit. Shared-budget invariant preserved via `_get_effective_wave_a_rerun_budget` — schema gate + stack-contract retry + A.5 all drain one counter; concurrent fires still concatenate into one retry.

2. **Cross-milestone section stability for M2+ is empirically unverifiable** — no preserved smoke completed past M1. The allowlist is M1-first with conditional sections for M2+ (required when IR has ≥1 entity in scope). Schema validator must flip the conditional based on `_select_ir_entities(...)` return. This is a scope call-out, not a HALT.

3. **`audit_agent.py:83` hard-codes `max_turns=1`.** Auditor-agent's 3-way-compare prompt design must fit in a single SDK turn; cannot chain iterative checks. Scope call-out, not a HALT.

4. **h1a pattern emission is mixed (string vs structured).** Auditor-agent's structured-emission wiring lands in `wave_executor.py` at the hook sites, NOT in `scaffold_verifier.py` / `endpoint_prober.py` / `cli.py`. Scope call-out.

5. **Architecture.md path shape is `.agent-team/milestone-{id}/` (singular "milestone-" + id, produces literal `milestone-milestone-1/` on disk).** This is NOT `.agent-team/milestones/{id}/` which is a separate directory. Easy to confuse; schema-agent should read the former.

---

## Companion artifacts

- `docs/plans/phase-h1b-discovery-citations.md` — every `file.py:NNNN` anchor verified at h1b HEAD.
- `docs/plans/phase-h1b-allowlist-evidence.md` — ALLOWLIST, DISALLOW-LIST, named-reason rejection texts, ALLOWED_REFERENCES set, section-stability analysis.

---

## 11. Post-review corrections (2026-04-19)

This section records the gap between discovery's original design (Sections 1–10 above) and what actually shipped. Earlier sections have been surgically updated; this list is the audit trail.

- **Option 2 chosen for the rerun budget (shared resolver, not literal key-reuse).** Team-lead authorized Option 2 (Add + alias) at dispatch time, overriding discovery's Option 1 recommendation. Canonical key: `v18.wave_a_rerun_budget: int = 2` at `config.py:885`. Legacy `v18.wave_a5_max_reruns` is preserved as a deprecated alias. Both `_enforce_gate_wave_a_schema` and `_enforce_gate_a5` read through `_get_effective_wave_a_rerun_budget` at `cli.py:10020`, so the shared-budget invariant is preserved while new operators get the canonical name and legacy configs reproduce bit-for-bit (with a `DeprecationWarning` per source location).
- **Formatter file split.** `_format_schema_rejection_feedback` lives in `cli.py` next to `_enforce_gate_wave_a_schema` (its gate consumer), not in `wave_executor.py` alongside `_format_plan_review_feedback`. The two formatters sit in different files because each is co-located with its own gate consumer — not because of layering asymmetry.
- **Derivability validator added in the post-review fix round.** Pattern ID `WAVE-A-SCHEMA-REFERENCE-001` (HIGH). Flags hardcoded ports / entity names / file paths / AC IDs in ARCHITECTURE.md that are not derivable from the Wave A injection sources (`scaffolded_files`, `ir.entities`, `stack_contract`, `backend_context`). This closes the smoke #11 `PORT ?? 8080` class of drift — a root-cause fix for finding 1 in the adversarial review.
- **Module globals replaced with `warnings.warn`.** The `_WAVE_A_SCHEMA_ALIAS_WARNED` / `_SKIP_LOGGED` module-level dedupe sets were replaced with Python's standard `warnings.warn(..., DeprecationWarning)` approach in the post-review fix round (verified: `rg '_WAVE_A_SCHEMA_(ALIAS_WARNED|SKIP_LOGGED)' src/agent_team_v15/cli.py` → 0 matches). Dedup is now handled by the warnings module's once-per-source-location behavior rather than custom module state.
- **Shipped flag names (authoritative).** `v18.wave_a_schema_enforcement_enabled` (not `wave_a_schema_gate_enabled`), `v18.wave_a_rerun_budget`, `v18.auditor_architecture_injection_enabled`. Earlier sections of this report originally used the pre-ship discovery names; those tables have been updated in place.
