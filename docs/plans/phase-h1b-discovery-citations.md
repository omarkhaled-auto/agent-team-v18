# Phase H1b — Discovery Citations

> Branch: `phase-h1b-wave-a-architecture-md-schema` @ integration HEAD `d2ce167` (post-h1a).
> Author: `discovery-agent` (Wave 1).
> Every `file.py:NNNN` reference used in `phase-h1b-architecture-report.md` or `phase-h1b-allowlist-evidence.md` is verified here against h1b HEAD — no carry-over from h1a citations or smoke #11 notes.

Quotes are single-line excerpts sufficient to anchor the citation. Longer context can be read directly at the cited span.

---

## 1A — Wave A prompt + SDK path

| Reference | Line | Verification quote |
|---|---|---|
| `build_wave_a_prompt` signature | `src/agent_team_v15/agents.py:8132-8144` | `def build_wave_a_prompt(` ... `stack_contract_rejection_context: str = "",` |
| Prompt body — `[WAVE A - SCHEMA / FOUNDATION SPECIALIST]` | `src/agent_team_v15/agents.py:8223` | `"[WAVE A - SCHEMA / FOUNDATION SPECIALIST]",` |
| Prompt body — `[PRIOR ATTEMPT REJECTED]` injection point | `src/agent_team_v15/agents.py:8287-8292` | `if stack_contract_rejection_context:` / `"[PRIOR ATTEMPT REJECTED]",` |
| Prompt body — `[PER-MILESTONE ARCHITECTURE HANDOFF — MUST]` | `src/agent_team_v15/agents.py:8318-8328` | `if v18_cfg is not None and bool(getattr(v18_cfg, "architecture_md_enabled", False)):` ... `"[PER-MILESTONE ARCHITECTURE HANDOFF — MUST]",` |
| Injection variable — `_select_ir_entities` call | `src/agent_team_v15/agents.py:8167` | `entities = _select_ir_entities(ir, milestone, milestone_scope=milestone_scope)` |
| Injection variable — `_select_ir_acceptance_criteria` | `src/agent_team_v15/agents.py:8168` | `acceptance_criteria = _select_ir_acceptance_criteria(` |
| Injection variable — `_build_backend_codebase_context` | `src/agent_team_v15/agents.py:8171` | `backend_context = _build_backend_codebase_context(cwd, scaffolded_files)` |
| Cumulative project architecture block (repo-root) | `src/agent_team_v15/agents.py:8179-8189` | `if cwd and v18_cfg is not None and bool(getattr(v18_cfg, "architecture_md_enabled", False)):` |
| SDK dispatch — `_execute_wave_sdk` | `src/agent_team_v15/wave_executor.py:2814-2823` | `async def _execute_wave_sdk(` |
| Wave A call site (regular path) | `src/agent_team_v15/wave_executor.py:4514-4522` | `wave_result = await _execute_wave_sdk(` |
| Wave A prompt build (regular path) | `src/agent_team_v15/wave_executor.py:4480-4504` | `prompt = await _invoke(` / `build_wave_prompt,` / `stack_contract_rejection_context=wave_a_rejection_context,` |
| Wave A existing single-retry on stack-contract | `src/agent_team_v15/wave_executor.py:4783-4808` | `if wave_letter == "A":` / `if critical and hard_block and wave_a_retry_count < 1 and rollback_snapshot is not None:` / `wave_a_rejection_context = format_stack_violations(critical)` |

**Key finding:** `build_wave_a_prompt`'s output is consumed by a single `_execute_wave_sdk(...)` call per attempt (not multi-turn). There IS already a single-retry path for stack-contract CRITICALs (`wave_a_retry_count < 1`) that feeds `wave_a_rejection_context` through `stack_contract_rejection_context`. The h1b schema gate must funnel schema rejections through this SAME channel, not a parallel one.

---

## 1C — Auditor prompt sites

| Reference | Line | Verification quote |
|---|---|---|
| `AUDIT_PROMPTS` registry | `src/agent_team_v15/audit_prompts.py:1386-1395` | `AUDIT_PROMPTS = {` / `"requirements": REQUIREMENTS_AUDITOR_PROMPT,` (8 entries through `"scorer"`) |
| `REQUIREMENTS_AUDITOR_PROMPT` | `src/agent_team_v15/audit_prompts.py` | constant defined earlier (one of 8) |
| `TECHNICAL_AUDITOR_PROMPT` | `src/agent_team_v15/audit_prompts.py:358` | `TECHNICAL_AUDITOR_PROMPT = """You are a TECHNICAL AUDITOR in the Agent Team audit-team.` |
| `INTERFACE_AUDITOR_PROMPT` | `src/agent_team_v15/audit_prompts.py:394` | `INTERFACE_AUDITOR_PROMPT = """You are an INTERFACE AUDITOR in the Agent Team audit-team. Your mandate is to` |
| `get_auditor_prompt` renderer | `src/agent_team_v15/audit_prompts.py:1482-1522` | `def get_auditor_prompt(` / `prompt = AUDIT_PROMPTS[auditor_name]` |
| `get_scoped_auditor_prompt` renderer | `src/agent_team_v15/audit_prompts.py:1559-1589` | `def get_scoped_auditor_prompt(` / `base = get_auditor_prompt(...)` |
| Audit dispatch max_turns constraint | `src/agent_team_v15/audit_agent.py:81-86` | `options = ClaudeAgentOptions(` / `max_turns=1,` |
| `audit_agent` import from `audit_prompts` (dispatch wrapper) | `src/agent_team_v15/audit_agent.py:36` | `from .audit_prompts import _STRUCTURED_FINDINGS_OUTPUT` |
| `audit_team` consumer of renderers | `src/agent_team_v15/audit_team.py:35` | `from .audit_prompts import AUDIT_PROMPTS, get_auditor_prompt, get_scoped_auditor_prompt` |

**Plan correction:** the dispatch plan asserted the renderers live in `cli.py` at `~1482` and `~1559` ("target cli.py renderers, NOT audit_prompts.py constants"). That is incorrect at h1b HEAD. The renderers `get_auditor_prompt` and `get_scoped_auditor_prompt` live in **`audit_prompts.py` at lines 1482 and 1559** respectively — the line numbers match by coincidence. The 8 constants AND the renderers both live in `audit_prompts.py`; `cli.py` does not render auditor prompts. `audit_team.py` and `audit_agent.py` are the dispatch wrappers; injection for h1b's three-way compare should happen inside `get_auditor_prompt` / `get_scoped_auditor_prompt` (audit_prompts.py), or at the earliest dispatch wrapper that has cwd + milestone_id in scope (audit_team.py). **No HALT** — the feature can still land at the correct site, the plan's site identification just needs to be updated. Auditor-agent (Wave 2B) should target `audit_prompts.py:1482` and `audit_prompts.py:1559`.

---

## 1D — Per-milestone ARCHITECTURE.md injection

| Reference | Line | Verification quote |
|---|---|---|
| `_load_per_milestone_architecture_block` definition | `src/agent_team_v15/agents.py:8051-8083` | `def _load_per_milestone_architecture_block(` / `return f"<architecture>\\n{content}\\n</architecture>"` |
| Path pattern | `src/agent_team_v15/agents.py:8075` | `arch_path = _Path(cwd) / ".agent-team" / f"milestone-{mid}" / "ARCHITECTURE.md"` |
| Call in `build_wave_b_prompt` | `src/agent_team_v15/agents.py:8407-8421` | `_arch_xml_b = _load_per_milestone_architecture_block(` / `parts.extend([_arch_xml_b, ""])` |
| Call in Wave E prompt builder | `src/agent_team_v15/agents.py:8664-8667` | `arch_xml_e = _load_per_milestone_architecture_block(cwd, str(milestone_id), v18_config)` |
| Call in Wave T prompt builder | `src/agent_team_v15/agents.py:8929-8934` | `arch_xml_block = _load_per_milestone_architecture_block(cwd, milestone_id, v18_cfg)` |
| Call in Wave D prompt builder | `src/agent_team_v15/agents.py:9274-9278` | `_arch_xml_d = _load_per_milestone_architecture_block(` |
| Flag name | `src/agent_team_v15/config.py:795` | `architecture_md_enabled: bool = False` |
| Flag coercion at config load | `src/agent_team_v15/config.py:2620-2622` | `architecture_md_enabled=_coerce_bool(` / `v18.get("architecture_md_enabled", cfg.v18.architecture_md_enabled),` |

**Path shape note:** disk layout is `.agent-team/milestone-{milestone_id}/ARCHITECTURE.md` (singular "milestone-", with the id appended). Because `milestone_id` is e.g. `"milestone-1"`, the actual directory path is `.agent-team/milestone-milestone-1/`. Preserved smokes confirm: e.g. `v18 test runs/build-final-smoke-20260419-043133/.agent-team/milestone-milestone-1/ARCHITECTURE.md`. This is NOT `.agent-team/milestones/milestone-1/` (which is a DIFFERENT directory holding REQUIREMENTS.md / TASKS.md / CONTRACTS.json). Schema-agent should read from the former path; WAVE_A5_REVIEW.json still lives in the latter. Both paths coexist.

---

## 1E — Structured finding emission sites for h1a patterns

| Pattern ID | Emit site | Line | Emission shape |
|---|---|---|---|
| `SCAFFOLD-COMPOSE-001` | `src/agent_team_v15/scaffold_verifier.py:212` | 212 | `summary.append(f"SCAFFOLD-COMPOSE-001 {topology_diag}")` — **string** appended to `summary` list. Not a `WaveFinding`. |
| `SCAFFOLD-PORT-002` | `src/agent_team_v15/scaffold_verifier.py:201` | 201 | `summary.append(f"SCAFFOLD-PORT-002 PORT_INCONSISTENCY {port_diag}")` — **string**. Not a `WaveFinding`. |
| `PROBE-SPEC-DRIFT-001` (exception class) | `src/agent_team_v15/endpoint_prober.py:1095-1111` | 1095 | `class ProbeSpecDriftError(RuntimeError):` — raised as an **exception** carrying `dod_port`/`code_port`/`requirements_path`. |
| `PROBE-SPEC-DRIFT-001` (startup_error string) | `src/agent_team_v15/endpoint_prober.py:728-732` | 728 | `context.startup_error = (f"PROBE-SPEC-DRIFT-001: code-port {drift.code_port} does not match ...")` — **string** on the `DockerContext`. Not a `WaveFinding`. |
| `OWNERSHIP-DRIFT-001` | `src/agent_team_v15/ownership_enforcer.py:310-323, 435` | 312 | `findings.append(Finding(code="OWNERSHIP-DRIFT-001", severity="HIGH", ...))` — **structured** as `Finding` (custom dataclass in `ownership_enforcer`). |
| `OWNERSHIP-WAVE-A-FORBIDDEN-001` | `src/agent_team_v15/ownership_enforcer.py:361-373` | 363 | `Finding(code="OWNERSHIP-WAVE-A-FORBIDDEN-001", severity="HIGH", ...)` — **structured**. Converted to `WaveFinding` at `wave_executor.py:4737-4746`. |
| `DOD-FEASIBILITY-001` | `src/agent_team_v15/dod_feasibility_verifier.py:276` | 276 | `code="DOD-FEASIBILITY-001",` — **structured** as `Finding`. |
| `RUNTIME-TAUTOLOGY-001` | `src/agent_team_v15/cli.py:177-270` | 239, 251, 263, 268 | `return f"RUNTIME-TAUTOLOGY-001: ..."` — **string** returned from `_runtime_tautology_guard`. Not a `WaveFinding`. |
| `WIRING-CLIENT-001` (Phase F analog) | `src/agent_team_v15/quality_checks.py:8220` | 8220 | `check="WIRING-CLIENT-001",` — **structured** as `Violation`. Converted to `WaveFinding` via `_violation_to_finding`. |

**Key finding:** h1a's pattern emission is **mixed** — `OWNERSHIP-DRIFT-001`, `OWNERSHIP-WAVE-A-FORBIDDEN-001`, `DOD-FEASIBILITY-001` emit as `Finding` dataclasses (later mapped to `WaveFinding` at the wave_executor hook sites); `SCAFFOLD-COMPOSE-001`, `SCAFFOLD-PORT-002`, `RUNTIME-TAUTOLOGY-001`, and `PROBE-SPEC-DRIFT-001` emit as **raw strings** (in summary lines / startup_error / RuntimeError messages). Phase F's `WIRING-CLIENT-001` is structured (`Violation`). Auditor-agent (Wave 2B) should convert the string-emitted h1a codes into structured `WaveFinding`s at the relevant wave hook sites — NOT edit audit_prompts.py. The pattern to copy is `_stack_violation_to_finding` at `wave_executor.py:2151` and `_violation_to_finding` at `wave_executor.py:2137`.

---

## 1F — Retry & escalation pattern (A.5 mirror)

| Reference | Line | Verification quote |
|---|---|---|
| `GateEnforcementError` class | `src/agent_team_v15/cli.py:9837-9869` | `class GateEnforcementError(RuntimeError):` with `.gate`, `.milestone_id`, `.critical_count` attrs |
| `_enforce_gate_a5` function | `src/agent_team_v15/cli.py:9902-9953` | `def _enforce_gate_a5(` / signature `(config, cwd, milestone_id, rerun_count) -> (should_rerun, critical_findings)` |
| `_enforce_gate_a5` raise-on-exhaustion | `src/agent_team_v15/cli.py:9943-9953` | `raise GateEnforcementError(...)` when `rerun_count >= max_reruns` |
| `_format_plan_review_feedback` | `src/agent_team_v15/wave_executor.py:3004-3033` | `def _format_plan_review_feedback(findings: list[dict[str, Any]]) -> str:` — returns `[PLAN REVIEW FEEDBACK]` block text |
| Retry loop — A.5 | `src/agent_team_v15/wave_executor.py:4375-4425` | `_a5_rerun = 0` / `while True:` / `should_rerun_a, critical_a_findings = _enforce_a5(...)` / `if not should_rerun_a: break` / `_a5_feedback = _format_plan_review_feedback(critical_a_findings)` / `stack_contract_rejection_context=_a5_feedback,` / `_a5_rerun += 1` |
| `stack_contract_rejection_context` plumb — prompt builder accept | `src/agent_team_v15/agents.py:8142` | `stack_contract_rejection_context: str = "",` |
| `stack_contract_rejection_context` plumb — render site | `src/agent_team_v15/agents.py:8287-8292` | `if stack_contract_rejection_context:` / `"[PRIOR ATTEMPT REJECTED]",` / `stack_contract_rejection_context.strip(),` |
| `wave_a5_max_reruns` config | `src/agent_team_v15/config.py:866` | `wave_a5_max_reruns: int = 1` |
| Config coercion | `src/agent_team_v15/config.py:2783-2786` | `wave_a5_max_reruns=_coerce_int(v18.get("wave_a5_max_reruns", cfg.v18.wave_a5_max_reruns), cfg.v18.wave_a5_max_reruns),` |
| Flag gate | `src/agent_team_v15/config.py:870` | `wave_a5_gate_enforcement: bool = False` |
| CLI-side test patterns | `tests/test_gate_enforcement.py:1-200+` | Direct `_cli._enforce_gate_a5(config=..., cwd=..., milestone_id=..., rerun_count=0)` calls over seeded `WAVE_A5_REVIEW.json` fixtures |

**Config design decision for schema-agent:** the existing `wave_a5_max_reruns` knob is a SHARED Wave A rerun budget (A.5 logic consumes it; h1b schema gate can consume it too). Two options:

**Option 1 (SHARED):** h1b's schema gate uses the same `wave_a5_max_reruns`. When the budget is 1, Wave A can be re-run once — but by EITHER A.5 findings OR schema findings. The gates do not independently consume budget; budget is per Wave A execution, shared. The existing `[PRIOR ATTEMPT REJECTED]` block carries EITHER kind of feedback (A.5 findings formatted by `_format_plan_review_feedback` OR schema findings formatted by a new `_format_schema_feedback`). **No new config knob. No deprecation. Default 1 budget covers both.**

**Option 2 (SEPARATE):** h1b introduces `wave_a_schema_gate_max_reruns` (default 1). A.5 and schema gates each get their own budget. Higher total budget but two knobs.

**Recommendation: Option 1 (SHARED).** Reasons:
- A.5 and schema gate are both "Wave A produced a plan that does not pass validation" — they belong to the same failure mode.
- Wave A is expensive; two separate reruns compound latency/cost.
- The existing feedback channel (`[PRIOR ATTEMPT REJECTED]`) is designed for a mixed-provenance feedback block — Option 1 can concatenate A.5 feedback + schema feedback in the same block when both fire.
- No user-facing knob deprecation. No migration docs.

No HALT — Option 1 does not deprecate anything. If Option 2 is chosen, HALT for team-lead authorization because it adds a new config surface.

**GateEnforcementError catch at milestone boundary:** `GateEnforcementError` propagates out of `_enforce_gate_a5`. Callers of the Wave A.5 retry loop catch it at milestone boundary — look for `except GateEnforcementError` in `wave_executor.py`:

| Reference | Line |
|---|---|
| First catch in wave dispatch | `src/agent_team_v15/wave_executor.py` (grep `except GateEnforcementError`) |

Grep location confirmed — h1b's schema gate should raise the same class with `gate="A-SCHEMA"` so existing catch handlers forward the recovery path correctly.

---

## 1G — Existing tests to pattern-match

| Purpose | Test file | Line | Why copy |
|---|---|---|---|
| Gate enforcement (A.5) | `tests/test_gate_enforcement.py:62-76, 78+` | 62 | `_config()` helper flips flag; `_seed_a5_review()` writes fixture JSON; `_cli._enforce_gate_a5(config=..., cwd=..., milestone_id="M1", rerun_count=0)` direct invocation. Copy verbatim for `_enforce_gate_a_schema`. |
| Wave A prompt rendering | `tests/test_mcp_doc_context_wave_a.py`, `tests/test_wave_a_entity_scope.py`, `tests/test_architecture_wave_a_must.py` | | `build_wave_a_prompt(milestone=..., ir=..., config=..., existing_prompt_framework="...")` direct calls; assertions on returned prompt string containing/excluding specific section headers. |
| Per-milestone ARCHITECTURE.md block | `tests/test_architecture_wave_a_must.py`, plus Slice 5c tests | | Fixture tmp_path with `.agent-team/milestone-milestone-1/ARCHITECTURE.md`; assert `<architecture>` appears in Wave B/D/T/E prompt output. |
| Audit prompt construction | `tests/test_audit_prompts.py:43, 69, 137, 249` | 43 | `def test_contains_scope_section` pattern; assertions on rendered audit prompts. |
| Audit scope wiring | `tests/test_audit_scope_wiring.py` | | Scope + flag interaction. |
| Structured finding emission (ownership) | `tests/test_h1a_ownership_enforcer.py` | | Workspace fixtures; assert emitted `Finding` objects have expected codes/severities/messages. |
| Wave A prompt section (Compose directive) | `tests/test_h1a_wave_b_prompt_compose_directive.py` | | h1a analog pattern — assert a specific block appears in the Wave B prompt string. Schema-agent copies this for Wave A schema-rule block. |

---

## 1H — HALT points

None identified. The plan's expected line numbers drifted slightly from h1a citations (which mention `cli.py:1482` and `cli.py:1559`); the correct sites at h1b HEAD are `audit_prompts.py:1482` and `audit_prompts.py:1559`. This is a plan-dispatch correction, not a HALT — auditor-agent (Wave 2B) will edit the correct files.

Other non-HALT caveats:
- `max_turns=1` at `audit_agent.py:83` means the three-way compare CANNOT chain iterative SDK turns. Auditor-agent must design any three-way compare as a SINGLE-TURN prompt (prompt-side comparison instructed to the model, not orchestrator-driven).
- h1a pattern IDs emit mixed (string vs structured). Structured emission work for `SCAFFOLD-COMPOSE-001` / `SCAFFOLD-PORT-002` / `RUNTIME-TAUTOLOGY-001` is a wiring task in `wave_executor.py`, not an `audit_prompts.py` edit.
- `wave_a5_max_reruns` default = 1. Schema-agent should NOT add a second budget knob unless explicitly authorized by team-lead.
