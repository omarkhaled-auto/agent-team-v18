# Phase H1b — Wave 3B Wiring Verification Report

> Author: `wiring-verifier` (Wave 3B). Read-only pass over Wave 2A/2B deliveries.
> Branch: `phase-h1b-wave-a-architecture-md-schema`. Baseline: `integration-2026-04-15-closeout`.
> Structural tests: `tests/test_h1b_wiring_invariants.py` (22 tests, all pass locally).

Every claim below is checked against source at h1b HEAD. File:line citations use the head of the
branch; they will drift when the files change. Run the companion test file in CI to catch drift.

---

## Summary

| Section | Scope | Verdict |
|---|---|---|
| 4A | Execution position — schema gate fires inside Wave A iteration, before stack-contract retry and before the separate A.5 iteration | PASS (with clarification) |
| 4B | Config gating — flag combinations + shared budget resolver | PASS (with two observations) |
| 4C | Crash isolation — validator/loader/structured-emission crashes caught | PASS |
| 4D | Reporting integration — rejection channel + GateEnforcementError + GATE_FINDINGS.json | PASS (with observation) |
| 4E | Pattern-id registration — new codes unique, no stray escalation id | PASS |
| 4F | No mutable module-level retry state in new modules | PASS |
| 4G | No unsubstituted placeholders in rendered Wave A prompt | PASS |
| 4H | Gate signature mirror — inspect.signature + raise sites | PASS (with observation) |
| 4I | Static auditor prompts byte-identical vs baseline | PASS |

No REJECTs. Three observations documented inline below (one drift in file co-location, one nuance
in the A.5 budget resolution path, one structured-emission target is `GATE_FINDINGS.json` rather
than `AUDIT_REPORT.json` directly).

---

## 4A — Execution position

**CLAIM (from dispatch):** Schema gate is the FIRST gate in the Wave A enforcement loop — BEFORE
stack-contract retry AND BEFORE A.5 retry.

**EVIDENCE:** Inside `_execute_milestone_waves_with_stack_contract` at `src/agent_team_v15/wave_executor.py:4195`:

- The `for wave_letter in waves[start_index:]` loop treats `"A"` and `"A5"` as separate
  iterations. `_wave_sequence(...)` at `wave_executor.py:424` enumerates them in order
  A → Scaffold → … → A5.
- Within the `wave_letter == "A"` iteration, the ordering is:
  1. Dispatch Wave A via `_execute_wave_sdk(...)` at `wave_executor.py:4628` (the `else:` branch that
     handles generic waves; Wave A uses this path).
  2. `WAVE_A_CONTRACT_CONFLICT.md` + ownership forbidden-writes check at `wave_executor.py:4821-4865`.
  3. **Schema gate at `wave_executor.py:4867-4895`** — `_enforce_gate_wave_a_schema(...)` fires only
     when `wave_letter == "A" and wave_result.success`. If it returns `(True, review)`, the feedback
     is formatted via `_format_schema_rejection_feedback`, appended to `wave_a_schema_rejection_context`,
     `wave_a_rerun_count` is bumped, and `continue` loops back to the top of the `while True:` at
     `wave_executor.py:4437`.
  4. Stack-contract retry at `wave_executor.py:4897+` — also guarded by `wave_letter == "A" and wave_result.success`.
  5. Wave A iteration completes; the outer `for` loop advances to Scaffold / A5.
- The `_enforce_gate_a5` call is in the SEPARATE `wave_letter == "A5"` branch at `wave_executor.py:4456-4530`.
  It seeds `_a5_rerun = wave_a_rerun_count` at line 4479 so the shared counter bleeds into A.5 —
  meaning if schema gate consumed the budget, A.5 cannot rerun.

**Clarification:** The dispatch prompt said "BEFORE A.5 (line ~4375)". Line 4375 is actually inside
the scaffold-verifier hook. The A.5 enforcement runs in a subsequent iteration of the outer wave
loop — it is literally not in the same `while True:`. The schema gate's position relative to A.5
is therefore "earlier wave iteration" rather than "earlier inside the same retry loop." The shared
rerun counter (`wave_a_rerun_count`) is what enforces the budget across the two iterations.

**Signature mirror:** `_enforce_gate_wave_a_schema` vs `_enforce_gate_a5` — both kw-only, same
parameter names/kinds/ordering. Returns differ by design: A.5 returns `tuple[bool, list[dict[str, Any]]]`
(findings list) and schema returns `tuple[bool, dict[str, Any]]` (review dict). Both are 2-tuples;
this matches the plan's wording "2-tuples (bool, dict-or-Finding-like)". Verified via
`inspect.signature` in `tests/test_h1b_wiring_invariants.py::test_gate_wave_a_schema_signature_mirrors_gate_a5`.

**Retry re-dispatch channel:** The next Wave A re-dispatch is built at `wave_executor.py:4596-4618`
(the generic `else:` branch). `merged_rejection = wave_a_rejection_context`; when
`wave_letter == "A" and wave_a_schema_rejection_context`, the two are concatenated and passed via
`stack_contract_rejection_context=merged_rejection` kwarg on `build_wave_prompt`. No new
`schema_rejection_context` kwarg — confirmed via grep.

**Escalation:** `_enforce_gate_wave_a_schema` raises `GateEnforcementError(gate="A-SCHEMA", ...)` at
`cli.py:10224`. No `audit_health="requires_review"` path — this is a hard fail propagated to the
milestone boundary.

**Auditor injection site:** `_maybe_inject_three_way_compare` is invoked from `get_auditor_prompt`
at `audit_prompts.py:1617-1623` — render-time, BEFORE any SDK call. Both registry-level wrappers
(`get_auditor_prompt`, `get_scoped_auditor_prompt`) route the injection through this helper.

**Structured-findings reporter path:** `_cli_gate_violations.append(...)` at `cli.py:14175-14188`
for RUNTIME-TAUTOLOGY-001; the list is persisted to `.agent-team/GATE_FINDINGS.json` at
`cli.py:12852-12866` and again post-orchestration at `cli.py:14061-14074`. See 4D below for the
observation on AUDIT_REPORT.json.

**Verdict: PASS.**

---

## 4B — Config gating

**CLAIM:** Flag combinations behave as specified; the shared budget resolver honors both
canonical and legacy keys.

**EVIDENCE:**

- `wave_a_schema_enforcement_enabled=False` short-circuits the gate: `cli.py:10166-10167` —
  `if not getattr(v18, "wave_a_schema_enforcement_enabled", False): return False, {}`. The
  validator is never imported or invoked.
- `wave_a_schema_enforcement_enabled=True` + `architecture_md_enabled=False`:
  `cli.py:10169-10178` — logs an INFO line (deduped via `_WAVE_A_SCHEMA_SKIP_LOGGED` keyed
  on `(id(v18), milestone_id)`) and returns `(False, {})`. Enforcement is a no-op.
- `wave_a_schema_enforcement_enabled=True` + `architecture_md_enabled=True`: full validator
  path at `cli.py:10180-10234`.
- Wave A prompt schema block is double-gated at `agents.py:8367-8371`:
  `if v18_cfg is not None and bool(getattr(v18_cfg, "wave_a_schema_enforcement_enabled", False))
   and bool(getattr(v18_cfg, "architecture_md_enabled", False))`.
- Shared budget resolver: `_get_effective_wave_a_rerun_budget` at `cli.py:10020-10053`. Called by
  schema gate (`cli.py:10214`) and by stack-contract retry in wave_executor (`wave_executor.py:4941`).
  Default canonical value is `2`. Legacy `wave_a5_max_reruns` is forwarded when non-default with a
  one-shot deprecation warning keyed on `id(v18)` via `_WAVE_A_SCHEMA_ALIAS_WARNED`.
- `auditor_architecture_injection_enabled=False` → `_maybe_inject_three_way_compare` at
  `audit_prompts.py:1558` returns prompt unchanged.
- `auditor_architecture_injection_enabled=True` + auditor_name ∈ `{"interface", "technical"}` →
  injection fires. `_THREE_WAY_COMPARE_AUDITORS = frozenset({"interface", "technical"})` at
  `audit_prompts.py:1507`. Other 5 auditors unaffected (early return at `audit_prompts.py:1551-1552`).
- No feature flag gates the structured-emission adapters (`_scaffold_summary_to_findings`,
  `_probe_startup_error_to_finding`, the `_cli_gate_violations.append` for RUNTIME-TAUTOLOGY-001).
  They fire unconditionally — this matches the plan's "bug fix, not capability" framing.

**Observation 1 (minor):** `_enforce_gate_a5` itself reads `wave_a5_max_reruns` directly at
`cli.py:9940` — not via `_get_effective_wave_a_rerun_budget`. The budget is still effectively
shared because `_a5_rerun` is seeded from `wave_a_rerun_count` at `wave_executor.py:4479`, but the
resolver call is NOT symmetric across both gate functions. This matches the plan's stated budget
arithmetic; it is a small deviation from the "both gates read the resolver" wording in the dispatch.

**Observation 2 (nomenclature):** Auditor names in `_THREE_WAY_COMPARE_AUDITORS` are lowercase
(`"interface"`, `"technical"`) to match `AUDIT_PROMPTS` dict keys. The dispatch prompt used
uppercase `{"INTERFACE", "TECHNICAL"}`; behavior is correct (lowercase matches the registry).

**Verdict: PASS.**

---

## 4C — Crash isolation

**CLAIM:** Validator, architecture-handoff loader, and structured-emission crashes are caught and
do not abort the pipeline.

**EVIDENCE:**

- Validator crash: `cli.py:10185-10206` wraps `load_architecture_md` + `validate_wave_a_output`
  in a single try/except. Any exception logs a WARNING and returns `(False, {})` — pipeline
  continues.
- Markdown parse crash inside `validate_wave_a_output`: `wave_a_schema_validator.py:174-181`
  catches heading-regex failures and sets `skipped_reason`, returning an empty result.
- Architecture-handoff loader: `_maybe_load_architecture_handoff_block` at `audit_prompts.py:1510-1532`
  wraps the import of `agents._load_per_milestone_architecture_block` and its invocation in
  separate try/except blocks, each returning `""` on failure — the auditor prompt falls back to
  the base (unmodified) render.
- Scaffold-summary adapter: `_scaffold_summary_to_findings` at `wave_executor.py:1112-1166` wraps
  the JSON read in try/except (`wave_executor.py:1141-1143`), logs a warning, returns `[]`.
- Probe adapter: `_probe_startup_error_to_finding` at `wave_executor.py:1169-1193` is pure
  string-parsing — no I/O. Falls through with `None` on any non-drift startup error.
- `_persist_wave_a_schema_review` at `cli.py:10075-10100` catches `OSError` and returns `None` —
  failing to persist the review JSON does not abort the gate (the findings are still returned
  to the caller).

**Verdict: PASS.**

---

## 4D — Reporting integration

**CLAIM:** Rejection signals feed the retry loop; exhaustion raises `GateEnforcementError`;
structured emissions reach the audit report.

**EVIDENCE:**

- `WAVE-A-SCHEMA-REJECTION-001` / `WAVE-A-SCHEMA-UNDECLARED-REF-001` — the validator emits these
  as the `pattern_id` field inside `SchemaValidationResult.to_review_dict()` at
  `wave_a_schema_validator.py:93, 106, 120`. They surface via `_format_schema_rejection_feedback`
  into the Wave A re-prompt's `[PRIOR ATTEMPT REJECTED]` channel (rejection signals consumed by
  the retry loop, not direct AUDIT_REPORT.json entries — matches plan.).
- Exhaustion: `GateEnforcementError(gate="A-SCHEMA", ...)` at `cli.py:10224` carries
  `critical_count` and `milestone_id`. The existing orchestrator catch path handles it the same
  way it handles `gate="A5"` / `gate="T5"`.
- `ARCH-DRIFT-*` findings live inside the injected `<three_way_compare>` directive text at
  `audit_prompts.py:1499-1503`. The auditor emits them as part of its normal audit-report output
  path; no new reporter.
- RUNTIME-TAUTOLOGY-001 structured emission: `_cli_gate_violations.append({"gate":
  "runtime_tautology", "code": "RUNTIME-TAUTOLOGY-001", "severity": "HIGH", "message": ...})`
  at `cli.py:14183-14188`. The pre-H1b `print_warning(_tautology_finding)` log lines at
  `cli.py:14168, 14171` are preserved — they remain the operator-visible channel.
- Scaffold + probe findings: `_scaffold_summary_to_findings(cwd)` invoked at
  `wave_executor.py:4376` and attached to the SCAFFOLD `WaveResult.findings` list at
  `wave_executor.py:4383`. Probe findings returned as the third element of the tuple at
  `wave_executor.py:2325`; callers attach them to the Wave B `WaveResult.findings`.

**Observation 3 (reporting target):** The dispatch said structured findings "reach AUDIT_REPORT.json
as structured dicts." In practice, `_cli_gate_violations` is persisted to
`.agent-team/GATE_FINDINGS.json` (at `cli.py:12855` and `cli.py:14066`), NOT directly to
`AUDIT_REPORT.json`. `WaveFinding` objects attached to `wave_result.findings` do flow into the
audit persistence path (`persist_wave_findings_for_audit` — unchanged from pre-H1b). The
RUNTIME-TAUTOLOGY-001 dict is therefore a GATE_FINDINGS.json entry, not an AUDIT_REPORT.json
entry. This is consistent with the existing CLI gate-violations mechanism (h1a pattern), so it's
an observation, not a REJECT — but the downstream consumer wiring should be checked by Wave 5
before shipping.

**Verdict: PASS.**

---

## 4E — Pattern-id registration

**CLAIM:** New pattern ids are unique vs h1a, and no `WAVE-A-SCHEMA-ESCALATION-001` exists.

**EVIDENCE:** `grep -rn` results confirm:

| Pattern | Locations |
|---|---|
| `WAVE-A-SCHEMA-REJECTION-001` | `src/agent_team_v15/wave_a_schema.py:218` (declaration only) |
| `WAVE-A-SCHEMA-UNDECLARED-REF-001` | `src/agent_team_v15/wave_a_schema.py:219` (declaration only) |
| `ARCH-DRIFT-PORT-001` | `src/agent_team_v15/audit_prompts.py:1499` (prompt text) |
| `ARCH-DRIFT-ENTITY-001` | `src/agent_team_v15/audit_prompts.py:1500` |
| `ARCH-DRIFT-ENDPOINT-001` | `src/agent_team_v15/audit_prompts.py:1501` |
| `ARCH-DRIFT-CREDS-001` | `src/agent_team_v15/audit_prompts.py:1502` |
| `ARCH-DRIFT-DEPS-001` | `src/agent_team_v15/audit_prompts.py:1503` |

Uniqueness: no collisions against `SCAFFOLD-*`, `DOD-*`, `OWNERSHIP-*`, `PROBE-*`,
`RUNTIME-*`, `WIRING-*` — all prefixes differ.

`WAVE-A-SCHEMA-ESCALATION-001`: `grep` returns zero matches under `src/`. Enforced by the
companion test `test_no_wave_a_schema_escalation_pattern_id_in_source`.

**Verdict: PASS.**

---

## 4F — No mutable module-level retry state

**CLAIM:** The new schema modules contain no mutable module-level state; retry counters are
function-local.

**EVIDENCE:**

- `src/agent_team_v15/wave_a_schema.py`: every module-level assignment is `Final[...]` — tuples,
  mappings, frozensets, and strings. Grep for `^_[A-Z_]+\s*=` returns lines 20, 28, 36, 42, 50 —
  all `Final[tuple[str, ...]]`. `ALLOWED_SECTIONS` is `Final[Mapping[...]]`. `REQUIRED_SECTIONS`
  is `Final[frozenset[str]]`.
- `src/agent_team_v15/wave_a_schema_validator.py`: only 3 module-level assignments —
  `_h2_heading_re`, `_h3_heading_re`, `_brace_var_re`, `_dollar_var_re`, `_inject_var_re` at
  lines 137-141. All compiled regex pattern objects, which are immutable for our purposes.
- `cli.py` module-level sets: `_WAVE_A_SCHEMA_ALIAS_WARNED: set[int]` at `cli.py:10016` and
  `_WAVE_A_SCHEMA_SKIP_LOGGED: set[tuple[int, str]]` at `cli.py:10017`. These are in-process
  dedupe sets for LOGGING ONLY (one-shot deprecation warning + one-shot skip INFO). They
  do NOT carry retry state. Keyed on `id(v18)` which is stable per config object. **This
  behavior is acceptable per the dispatch mandate**; documenting explicitly for reviewer
  awareness.
- `wave_executor.py` retry state: `wave_a_rerun_count` and `wave_a_schema_rejection_context`
  are function-local variables of `_execute_milestone_waves_with_stack_contract` at
  `wave_executor.py:4292-4293`. Reset once per milestone. Not module-level.

**Verdict: PASS.**

Enforced by `test_wave_a_schema_module_no_mutable_globals` +
`test_wave_a_schema_validator_module_no_mutable_globals`.

---

## 4G — Injection variable validity

**CLAIM:** `build_wave_a_prompt` renders zero unsubstituted `{foo}` / `${FOO}` / `<inject:FOO>`
tokens in the output, in all flag combinations.

**EVIDENCE:** Structural test
`test_build_wave_a_prompt_no_unsubstituted_placeholders` in
`tests/test_h1b_wiring_invariants.py` renders the prompt with a realistic fixture milestone/IR
across 4 flag combinations (schema on/off × architecture_md on/off). Fenced code blocks and
inline backtick samples are stripped before the scan so legitimate example placeholders inside
teaching snippets are not flagged.

Manual render shows the output contains no brace-wrapped variables outside code blocks. The
`[ARCHITECTURE.md SCHEMA — STRICT ALLOWLIST]` block's allowlist-examples use `.agent-team/milestone-{milestone_id}/...`
as a literal documentation string inside a fenced block — excluded from the scan.

**Verdict: PASS.**

---

## 4H — Gate-enforcement mirror verification

**CLAIM:** `_enforce_gate_wave_a_schema` mirrors `_enforce_gate_a5`'s signature, exhaustion
behavior, and feedback channel.

**EVIDENCE:**

- Signatures (via `inspect.signature`, enforced by
  `test_gate_wave_a_schema_signature_mirrors_gate_a5`):
  - `_enforce_gate_a5`: `(*, config: AgentTeamConfig, cwd: str, milestone_id: str, rerun_count: int) -> tuple[bool, list[dict[str, Any]]]`
  - `_enforce_gate_wave_a_schema`: `(*, config: AgentTeamConfig, cwd: str, milestone_id: str, rerun_count: int) -> tuple[bool, dict[str, Any]]`
  - Parameter names, kinds (all KEYWORD_ONLY), and ordering match 1:1. Return annotations both
    2-tuples; second element differs by design.
- Both raise `GateEnforcementError` on exhaustion: `cli.py:9943` (A.5) and `cli.py:10224` (schema).
  Runtime test `test_gate_wave_a_schema_raises_gate_enforcement_error_on_exhaustion` exercises the
  schema exhaustion path end-to-end with a seeded fixture directory.
- Budget resolution: schema gate calls `_get_effective_wave_a_rerun_budget(config)` at
  `cli.py:10214`; stack-contract retry calls it at `wave_executor.py:4941`. A.5 reads
  `wave_a5_max_reruns` directly at `cli.py:9940` — **Observation 1 above**. The shared-budget
  effect is preserved via the `_a5_rerun = wave_a_rerun_count` seeding at `wave_executor.py:4479`.
- Feedback channel: the Wave A re-dispatch passes concatenated rejection context through the
  `stack_contract_rejection_context` kwarg at `wave_executor.py:4617`. This is the same kwarg the
  A.5 loop uses at `wave_executor.py:4504`. No parallel channel.
- `_format_schema_rejection_feedback` co-location: **DEVIATION from dispatch.** The dispatch said
  it should be "co-located with `_format_plan_review_feedback` in cli.py (same file)." In
  practice:
  - `_format_plan_review_feedback` lives at `src/agent_team_v15/wave_executor.py:3093`
  - `_format_schema_rejection_feedback` lives at `src/agent_team_v15/cli.py:10103`
  - They are in DIFFERENT files. The architecture-report plan (Section 1F mirror table) said the
    new formatter "lives alongside `_format_plan_review_feedback`" — that is wave_executor.py, not
    cli.py. The dispatch's "in cli.py" wording appears to be the drift source. The actual
    placement (schema formatter in cli.py, alongside `_enforce_gate_wave_a_schema` and
    `_load_wave_a_schema_review`) is internally coherent: all schema-gate helpers are co-located
    in cli.py. Plan-review helpers live in wave_executor.py because that's where A.5's retry loop
    lives. This is a **non-REJECT observation** — the two formatters are correctly co-located
    with their respective gate consumers.
- No `WAVE_A_VALIDATION_HISTORY.json` in the codebase. Grep across the tree returns zero matches.

**Verdict: PASS.**

---

## 4I — Static auditor prompt constants untouched

**CLAIM:** The eight static auditor prompt string constants and the `AUDIT_PROMPTS` dict literal
are byte-identical versus `integration-2026-04-15-closeout`.

**EVIDENCE:** `git diff integration-2026-04-15-closeout -- src/agent_team_v15/audit_prompts.py`
shows 166 lines of diff, all additions (no lines removed, no lines modified in place). The diff
adds:

1. `_THREE_WAY_COMPARE_DIRECTIVE` (line 1482)
2. `_THREE_WAY_COMPARE_AUDITORS` frozenset (line 1507)
3. `_maybe_load_architecture_handoff_block` helper (line 1510)
4. `_maybe_inject_three_way_compare` helper (line 1535)
5. New kwargs (`config`, `cwd`, `milestone_id`) on `get_auditor_prompt` (line 1566)
6. `_maybe_inject_three_way_compare(...)` call inside `get_auditor_prompt` (line 1617)
7. New kwargs (`cwd`, `milestone_id`) on `get_scoped_auditor_prompt` (line 1662)
8. `effective_milestone_id` resolution inside `get_scoped_auditor_prompt` (line 1685)

**Static constants verified byte-identical** (via
`test_audit_prompt_constant_byte_identical_to_baseline` parametrized over all 8 names):

- `REQUIREMENTS_AUDITOR_PROMPT` at line 92
- `TECHNICAL_AUDITOR_PROMPT` at line 358
- `INTERFACE_AUDITOR_PROMPT` at line 394
- `TEST_AUDITOR_PROMPT` at line 651
- `MCP_LIBRARY_AUDITOR_PROMPT` at line 709
- `PRD_FIDELITY_AUDITOR_PROMPT` at line 750
- `COMPREHENSIVE_AUDITOR_PROMPT` at line 812
- `SCORER_AGENT_PROMPT` at line 1292

**Registry dict literal verified byte-identical** at `audit_prompts.py:1386-1395` via
`test_audit_prompts_registry_byte_identical_to_baseline`.

**Note:** The dispatch called out the scorer constant as `SCORER_AUDITOR_PROMPT`. The actual
source name is `SCORER_AGENT_PROMPT` — confirmed by grep. AUDIT_PROMPTS maps the key `"scorer"`
to `SCORER_AGENT_PROMPT`. The discovery citations (§1C) already had this correct.

**Verdict: PASS.**

---

## Structural tests — `tests/test_h1b_wiring_invariants.py`

22 tests, all passing locally at h1b HEAD:

- 4F: `test_wave_a_schema_module_no_mutable_globals`,
  `test_wave_a_schema_validator_module_no_mutable_globals`.
- 4G: `test_build_wave_a_prompt_no_unsubstituted_placeholders` (4 parametrized cases).
- 4H: `test_gate_wave_a_schema_signature_mirrors_gate_a5`,
  `test_gate_wave_a_schema_returns_two_tuple`,
  `test_gate_wave_a_schema_raises_gate_enforcement_error_on_exhaustion`,
  `test_get_effective_wave_a_rerun_budget_reads_canonical_key`,
  `test_format_schema_rejection_feedback_emits_block_header`.
- 4I: `test_audit_prompt_constant_byte_identical_to_baseline` (8 parametrized cases),
  `test_audit_prompts_registry_byte_identical_to_baseline`.
- 4E sanity: `test_no_wave_a_schema_escalation_pattern_id_in_source`,
  `test_wave_a_schema_pattern_ids_present`.

4I's git-diff tests skip gracefully when git is unavailable (released-wheel or shallow-clone
contexts). The baseline comparison reads git-show output as raw bytes and decodes utf-8
explicitly — this was a fix after an initial Windows-locale cp1252 decode artifact (em-dash
byte mismatch).

No external dependencies. No docker. No network. Each test completes in <100ms locally.

---

## Non-REJECT observations recap

1. **Budget resolver asymmetry.** Schema gate and stack-contract retry call
   `_get_effective_wave_a_rerun_budget`; A.5 reads `wave_a5_max_reruns` directly. Effective
   shared-budget behavior preserved by seeding `_a5_rerun = wave_a_rerun_count` in
   wave_executor. Future symmetry cleanup is out of scope for H1b.
2. **Auditor names lowercase.** `_THREE_WAY_COMPARE_AUDITORS` uses `{"interface", "technical"}`
   (lowercase) to match `AUDIT_PROMPTS` dict keys — dispatch prompt used uppercase; behavior is
   correct.
3. **Structured emission target.** RUNTIME-TAUTOLOGY-001 structured dicts land in
   `.agent-team/GATE_FINDINGS.json`, not `AUDIT_REPORT.json`. SCAFFOLD-* and PROBE-* findings
   attach to `WaveResult.findings` which flow through `persist_wave_findings_for_audit` to the
   audit pipeline. Downstream wiring into AUDIT_REPORT.json should be spot-checked by Wave 5
   production-caller proofs.
4. **Formatter file co-location.** Dispatch said both feedback formatters should live in cli.py;
   reality has `_format_plan_review_feedback` in wave_executor.py (existing) and
   `_format_schema_rejection_feedback` in cli.py (new). Each is co-located with its gate consumer
   — which is the correct structural rule. Dispatch wording was imprecise.
