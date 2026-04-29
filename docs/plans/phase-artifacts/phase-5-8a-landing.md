---
name: Phase 5.8a pipeline-upgrade landing
description: As-shipped state of Phase 5.8a (advisory cross-package OpenAPI/TS-client diagnostic — partial R-#42 closure pending §K.2); required reading before Phase 5.8b OR the Wave A spec-quality follow-up
type: project
originSessionId: 7efafdd8-6e21-4cfc-a5c5-9a7ea04a8e21
---

Phase 5.8a of the 9-phase Phase 5 plan landed direct-to-master on
2026-04-29 off baseline `51c1001` (Phase 5.7 outer-layer cap-halt) as a
single source-only commit. Plan:
`docs/plans/2026-04-28-phase-5-quality-milestone.md` §K.1 + §M.M7 +
§M.M16. R-#42 partial closure: the diagnostic step ships; full closure
deferred pending §K.2 decision gate (operator-authorised sequential
M1+M2 smoke batch, NOT this session).

Phase 5.8a is the FIRST Wave 4 phase per §0.3 and is **diagnostic-first
per §M.M7** — the source patch ships ONE diagnostic step + ONE advisory
finding code (`CONTRACT-DRIFT-DIAGNOSTIC-001`). The §K.2 decision-gate
session reads the per-milestone `PHASE_5_8A_DIAGNOSTIC.json` artifacts
to decide: 3 correlated divergences (same `divergence_class` across ≥3
distinct DTOs in the smoke batch) → Phase 5.8b ships; otherwise close
R-#42 by Wave A spec-quality investment instead.

## Files touched (matches plan §K.1 + scope check-in extensions)

| File | Change |
|---|---|
| **NEW** `src/agent_team_v15/cross_package_diagnostic.py` | Core module (~570 lines): `DivergenceRecord` + `DiagnosticOutcome` dataclasses; locked enum constants (4 divergence classes + 2 tooling states + log tag + filename); type-class normalisation (`_classify_openapi_type` / `_classify_ts_type` — handles primitives, arrays, refs, nullability, modern `type:[X,"null"]`); name normalisation for camelCase ⟷ snake_case; embedded Node TypeScript-AST helper script (resolves `typescript` from generated workspace via `createRequire(<projectRoot>/package.json)` per scope check-in correction #4); `compute_divergences` crash-isolated entry; `divergences_to_finding_dicts` converter with explicit advisory message; per-milestone `write_phase_5_8a_diagnostic` artifact writer; `k2_decision_gate_satisfied` predicate. |
| `src/agent_team_v15/openapi_generator.py` | `ContractResult` extended with 4 additive fields (`diagnostic_findings`, `diagnostic_metrics`, `diagnostic_tooling`, `diagnostic_unsupported_polymorphic_schemas`). `generate_openapi_contracts` calls `compute_divergences` after `_generate_client_package` ONLY on the canonical openapi-ts path (`client_generator == "openapi-ts"`). Crash-isolated try/except: any exception sets fields to safe defaults + logs warning + Wave C continues unaffected (per Q2 — diagnostic NEVER fails Wave C). Minimal-ts fallback path skips the diagnostic entirely. |
| `src/agent_team_v15/wave_executor.py` | `_coerce_contract_result` (line 2775) extended to thread the 4 new fields through the dataclass→dict path (correction #5 — load-bearing; without this update the dataclass route silently loses diagnostics). `_execute_wave_c` (line ~6162) calls new helper `_emit_phase_5_8a_diagnostic`. The helper converts each finding-dict to `WaveFinding(severity="LOW", code="CONTRACT-DRIFT-DIAGNOSTIC-001", file=<.gen.ts path>, line=N, message=<advisory>)`, extends `result.findings`, writes `<run-dir>/.agent-team/milestones/<id>/PHASE_5_8A_DIAGNOSTIC.json` (per-milestone path; M1+M2 cannot collide — correction #3), and emits the `[CROSS-PACKAGE-DIAG]` summary log line. Crash-isolated; tolerates empty `contract_result` (legacy / minimal-ts path). |
| `src/agent_team_v15/audit_prompts.py` | Section 1b §WAVE_FINDINGS.json Reconciliation extended with explicit advisory exception for `CONTRACT-DRIFT-DIAGNOSTIC-001` (correction #2). The scorer agent is instructed: if reflected in AUDIT_REPORT.json, set `verdict="UNVERIFIED"` and `severity="LOW"`; NEVER promote to `verdict="FAIL"`; NEVER raise severity. They MUST NOT count toward the unresolved-FAIL counter or the cascade quality gate. |
| `docs/plans/2026-04-28-phase-5-quality-milestone.md` | §O.4 closeout-evidence checklist appended with rows O.4.12 (per-milestone PHASE_5_8A_DIAGNOSTIC.json artifact), O.4.13 (`[CROSS-PACKAGE-DIAG]` log line at end-of-Wave-C), O.4.14 (§K.2 decision-gate evidence — 3 correlated divergences across distinct DTOs) per scope check-in correction #6. |
| **NEW** `tests/test_cross_package_contract_diagnostics.py` | 30 fixtures covering AC1-AC8 + the 6 supporting locks listed in §H.5 below. |

**Not touched** (per §0.1 invariant 15):

* `audit_models.py` — no central finding-code catalogue exists in the
  repo (verified by `grep`); the `CONTRACT_DRIFT_DIAGNOSTIC_CODE`
  constant lives at the emission site (`cross_package_diagnostic.py`)
  per existing precedent (`STACK-IMPORT-002`, `WAVE-A-CONTRACT-DRIFT-001`,
  `WAVE-D-SELF-VERIFY` are all defined at their emission sites).
* Phase 4.x cascade primitives (anchor, lock, hook, owner_wave, ship-block).
* Phase 5.{1,2,3,4,5,6,7} primitives (score normalisation, audit-team
  plumbing, STATE.json quality-debt fields, cycle-1 dispatch, Quality
  Contract resolver, unified build gate, bootstrap watchdog).
* `pyproject.toml` package-data — embedding the JS as a module-level
  Python string + writing to a tempfile at runtime avoids the
  `package-data` churn and keeps the diagnostic fully self-contained
  (correction #4).

## Actual API surface shipped

Module `agent_team_v15.cross_package_diagnostic` (NEW):

* `CONTRACT_DRIFT_DIAGNOSTIC_CODE = "CONTRACT-DRIFT-DIAGNOSTIC-001"` —
  the locked finding-code constant. Emitted by Wave C's diagnostic step
  ONLY; severity LOW; advisory.
* `DIAGNOSTIC_SEVERITY = "LOW"`,
  `DIAGNOSTIC_VERDICT_HINT = "UNVERIFIED"`,
  `DIAGNOSTIC_LOG_TAG = "[CROSS-PACKAGE-DIAG]"`,
  `PHASE_5_8A_DIAGNOSTIC_FILENAME = "PHASE_5_8A_DIAGNOSTIC.json"`.
* `ALL_DIVERGENCE_CLASSES` — locked enum tuple:
  `("missing-export", "camelCase-vs-snake_case", "optional-vs-required", "type-mismatch")`.
  Polymorphic OpenAPI schemas (`oneOf`/`anyOf`/`allOf`) are SKIPPED as
  unsupported metadata; they do NOT inflate divergence count and surface
  in `unsupported_polymorphic_schemas` instead (correction #1).
* `TOOLING_PARSER_NODE_TS_AST = "node-typescript-ast"`,
  `TOOLING_PARSER_UNAVAILABLE = "unavailable"`.
* `@dataclass DivergenceRecord` — 8 fields:
  `divergence_class`, `schema_name`, `property_name`, `spec_value`,
  `client_value`, `client_file`, `client_line`, `details`.
* `@dataclass DiagnosticOutcome` — `divergences`, `metrics`, `tooling`,
  `unsupported_polymorphic_schemas`.
* `compute_divergences(spec_path, client_dir, project_root, *, node_bin=None, parser_override=None) -> DiagnosticOutcome`
  — main entry. Crash-isolated. `parser_override` is for tests; the
  default path shells out to the embedded Node helper (timeout 30s).
* `divergences_to_finding_dicts(outcome) -> list[dict]` — converter.
  Each dict carries the WaveFinding kwargs (`code` / `severity` / `file` /
  `line` / `message`) plus the original `divergence_class` /
  `schema_name` / etc. for the `PHASE_5_8A_DIAGNOSTIC.json` artifact.
  Message includes explicit `[Phase 5.8a advisory; verdict=UNVERIFIED,
  severity=LOW; does NOT block Quality Contract]` prefix (correction #2
  — second line of defence even if the auditor never reads
  `audit_prompts.py`).
* `write_phase_5_8a_diagnostic(cwd, milestone_id, outcome, *, smoke_id="", correlated_compile_failures=0, timestamp=None) -> Path | None`
  — best-effort artifact writer at the per-milestone path
  `<cwd>/.agent-team/milestones/<id>/PHASE_5_8A_DIAGNOSTIC.json`.
* `k2_decision_gate_satisfied(per_milestone_diagnostics, *, correlated_threshold=3) -> bool`
  — locked §K.2 predicate. Distinct `(divergence_class, schema_name)`
  pairs sharing the SAME class across the smoke batch ≥ threshold.

Module `agent_team_v15.openapi_generator`:

* `ContractResult.diagnostic_findings: list[dict] = []`
* `ContractResult.diagnostic_metrics: dict = {}`
* `ContractResult.diagnostic_tooling: dict = {}`
* `ContractResult.diagnostic_unsupported_polymorphic_schemas: list[str] = []`

Module `agent_team_v15.wave_executor`:

* `_emit_phase_5_8a_diagnostic(*, cwd, milestone, contract_result, wave_result) -> None`
  — Phase 5.8a-internal helper called from `_execute_wave_c`. Performs
  WaveFinding extension + per-milestone artifact write + log emission.
  Crash-isolated.
* `_coerce_contract_result` extended with the 4 new diagnostic field
  copies.

Module `agent_team_v15.audit_prompts`:

* `SCORER_AGENT_PROMPT` — section 1b extended with explicit advisory
  exception line for `CONTRACT-DRIFT-DIAGNOSTIC-001`.

## Risks closed

* **R-#42 — partial closure (per §K.2 partial-closure semantics).**
  Phase 5.8a ships the Wave C openapi-vs-generated-client diagnostic.
  Full closure depends on the §K.2 decision-gate evaluation (separate
  operator-authorised session reading per-milestone
  `PHASE_5_8A_DIAGNOSTIC.json` artifacts):
  * 3 correlated divergences before/at the 10-smoke cap → Phase 5.8b
    ships full `cross_package_contract.py`. R-#42 closed via the
    explicit-contract path.
  * <3 correlated divergences after 10 smokes → R-#42 closed by Wave A
    spec-quality investment instead (extend Wave A prompt to emit
    fully-fleshed OpenAPI 3.1 with explicit `additionalProperties:
    false` + complete `required` lists; add Wave A.5 plan reviewer
    check for OpenAPI completeness). NO `cross_package_contract.py`
    ships in this branch.

## Diagnostic comparison algorithm shipped

* **Source:** OpenAPI 3.1 `components.schemas[X]` from
  `result.cumulative_spec_path`.
* **Target:** openapi-ts canonical `export type X = { ... };` and
  `export interface X { ... }` blocks in
  `packages/api-client/types.gen.ts`. Parsed via the embedded Node
  TypeScript-AST helper (`ts.createSourceFile` + `ts.forEachChild`);
  `typescript` is resolved from the generated workspace via
  `createRequire(<projectRoot>/package.json)` (correction #4).
* **Compared facets:** property names (case-only via name
  normalisation); optional flag (`required: ["foo"]` vs `?:` modifier);
  top-level export presence; primitive / array / ref / nullability
  type-classes (correction #1 — types in 5.8a scope).
* **Skipped (unsupported metadata):** OpenAPI polymorphic schemas
  (`oneOf` / `anyOf` / `allOf`) — surface in
  `unsupported_polymorphic_schemas` instead, do NOT inflate divergence
  count (correction #1).
* **Skipped (advisory diagnostic boundary):** sub-shape comparison
  (e.g., array element type beyond one level), generic constraints,
  mapped types, intersection types — these are 5.8b territory IF the
  K.2 decision gate fires.

Locked divergence classes (deterministic enum):

1. `missing-export` — `components.schemas[X]` exists, no matching
   `export type X` / `export interface X` in the client.
2. `camelCase-vs-snake_case` — property name case mismatch (same
   normalised name).
3. `optional-vs-required` — required-array mismatch with TS optional
   modifier (both directions reported).
4. `type-mismatch` — type-class differs between OpenAPI and TS (same
   property name + same optional flag); `nullable` is normalised so
   `string | null` ≡ `type: [string, "null"]` ≡ `string`.

## §K.2 decision-gate predicate (locked by fixture)

```
k2_decision_gate_satisfied(per_milestone_diagnostics, correlated_threshold=3) :=
    ∃ divergence_class such that
    |{ schema_name : ∃ smoke ∃ divergence in smoke.divergences with
                       divergence.divergence_class = class
                       AND divergence.schema_name = schema_name }|
    ≥ correlated_threshold
```

Locked by:

* `test_k2_decision_gate_satisfied_3_distinct_dtos_same_class`
  (positive — 3 distinct DTOs, same class → True).
* `test_k2_decision_gate_NOT_satisfied_3_props_one_dto_same_class`
  (negative — 3 properties on ONE DTO → False; distinct-schema
  discipline is the predicate, NOT property-count).
* `test_k2_decision_gate_NOT_satisfied_3_distinct_dtos_different_classes`
  (negative — 3 DTOs but different classes → False; same-class
  correlation is the predicate).
* `test_k2_decision_gate_empty_input` (degenerate — empty list /
  empty divergences → False).

The K.2 evaluator session reads every smoke's per-milestone
`PHASE_5_8A_DIAGNOSTIC.json`, passes the decoded list to
`k2_decision_gate_satisfied`, and writes
`PHASE_5_8A_DIAGNOSTIC_SUMMARY.md` with the outcome + evidence rows.
The aggregator + summary writer are NOT shipped in this Phase 5.8a
session — only the predicate semantic.

## PHASE_5_8A_DIAGNOSTIC.json schema (locked)

```json
{
  "phase": "5.8a",
  "milestone_id": "<id>",
  "smoke_id": "<run-dir-stem>",
  "generated_at": "<ISO-8601>",
  "metrics": {
    "schemas_in_spec": <int>,
    "exports_in_client": <int>,
    "divergences_detected_total": <int>,
    "unique_divergence_classes": ["camelCase-vs-snake_case", ...],
    "divergences_correlated_with_compile_failures": <int>
  },
  "divergences": [
    {
      "divergence_class": "...",
      "schema_name": "...",
      "property_name": "...",
      "spec_value": "...",
      "client_value": "...",
      "client_file": "...",
      "client_line": <int>,
      "details": "..."
    }
  ],
  "unsupported_polymorphic_schemas": ["..."],
  "tooling": {
    "ts_parser": "node-typescript-ast" | "unavailable",
    "ts_parser_version": "<tsc version>" | "",
    "error": "<reason>" | ""
  }
}
```

Locked by `test_phase_5_8a_diagnostic_json_schema_locked`. Per-milestone
path locked by `test_per_milestone_artifact_path_isolates_m1_and_m2`.

`divergences_correlated_with_compile_failures` is best-effort and ships
at `0` in the Phase 5.8a source landing. The K.2 evaluator session can
recompute correlation against Phase 5.6 `WAVE-D-SELF-VERIFY` finding's
`error_summary` typescript section at decision time (correction Q4 —
explicitly labelled best-effort, NOT used as a gate).

## Tests shipped (30 fixtures in tests/test_cross_package_contract_diagnostics.py)

Per dispatch §K.1 + scope check-in:

* AC1 — `test_empty_spec_yields_no_divergences`.
* AC2 — `test_spec_equals_client_yields_no_divergences`.
* AC3 — `test_camel_vs_snake_drift_detected`.
* AC4 — `test_optional_vs_required_drift_detected`.
* AC5 — `test_missing_export_drift_detected`.
* Type-class mismatch (correction #1):
  * `test_type_class_mismatch_detected` (string vs number).
  * `test_array_type_mismatch_detected` (array element class).
  * `test_nullable_does_not_fire_type_mismatch` (negative — nullability
    is NOT a type-class change).
* Polymorphic skip (correction #1):
  * `test_polymorphic_oneof_does_not_inflate_divergences`.
  * `test_polymorphic_anyof_and_allof_also_skipped`.
* AC6 — advisory-not-gating:
  * `test_advisory_findings_do_not_gate_quality_contract` (5
    UNVERIFIED+LOW AuditFindings → COMPLETE/clean/0/"").
  * `test_advisory_findings_do_not_trip_state_invariant_rule_1`
    (LOW + 5 unresolved → no Rule 1 violation).
  * `test_wave_finding_message_carries_advisory_wording` (advisory
    string in message; second line of defence).
* AC7 — log line emission:
  * `test_cross_package_diag_summary_log_emitted` (positive shape).
  * `test_cross_package_diag_log_fires_on_zero_divergences` (operator
    visibility — log fires at zero divergences too).
  * `test_cross_package_diag_log_fires_on_tooling_unavailable`
    (tooling-error shape).
* AC8 — schema lock:
  * `test_phase_5_8a_diagnostic_json_schema_locked`.
  * `test_per_milestone_artifact_path_isolates_m1_and_m2` (correction #3).
* Crash isolation (Q2):
  * `test_compute_divergences_parser_override_raise_does_not_propagate`.
  * `test_emit_phase_5_8a_diagnostic_handles_empty_contract_result`
    (minimal-ts fallback path stays silent).
* Threading (correction #5):
  * `test_coerce_contract_result_threads_diagnostic_fields`.
  * `test_coerce_contract_result_legacy_dataclass_yields_empty_diagnostics`.
* §K.2 predicate (locked):
  * `test_k2_decision_gate_satisfied_3_distinct_dtos_same_class`.
  * `test_k2_decision_gate_NOT_satisfied_3_props_one_dto_same_class`.
  * `test_k2_decision_gate_NOT_satisfied_3_distinct_dtos_different_classes`.
  * `test_k2_decision_gate_empty_input`.
* Tooling-unavailable (Q3):
  * `test_tooling_unavailable_emits_no_drift_findings`.
  * `test_missing_types_gen_yields_tooling_unavailable`.
  * `test_invalid_spec_json_yields_tooling_unavailable`.
* Constants smoke:
  * `test_finding_code_and_severity_constants_match_dispatch`.

## Phase 5.7 + 5.6 + 5.5 + 4.3 contract preservation evidence

* **Phase 5.7 (bootstrap watchdog).** Wave C is scripted Python
  (`generate_openapi_contracts`); not SDK-dispatched. The
  `_invoke_*_with_watchdog` family + `_cumulative_wedge_budget` +
  bootstrap respawn + productive-tool-idle watchdog are all UNTOUCHED.
  Phase 5.8a's diagnostic step is in-process Python with a 30-second
  Node-subprocess timeout; cannot trigger any watchdog.
* **Phase 5.6 (unified build gate).** `WaveBVerifyResult` /
  `WaveDVerifyResult` shapes UNTOUCHED. `unified_build_gate.run_compile_profile_sync`
  UNTOUCHED. Phase 5.8a's `divergences_correlated_with_compile_failures`
  is best-effort (defaults to 0 at write-time; K.2 evaluator
  recomputes against `WAVE-D-SELF-VERIFY` `error_summary` later).
* **Phase 5.5 (Quality Contract).** `_evaluate_quality_contract`,
  `_finalize_milestone_with_quality_contract`, `_quality.json` sidecar,
  `confirmation_status`, layer-2 invariants, §M.M13 suppression
  registry — all UNTOUCHED. Severity LOW + verdict UNVERIFIED →
  HIGH/CRITICAL filter doesn't see the finding; Rule 1 doesn't fire.
* **Phase 5.4 (cycle-1 dispatch + cost cap).** UNTOUCHED.
* **Phase 5.{1,2,3} (audit termination + path drift + STATE.json
  quality-debt fields).** UNTOUCHED.
* **Phase 4.3 (owner_wave).** Wave attribution comes for free —
  `WaveFinding(file=<.gen.ts path under packages/api-client/>)` →
  `wave_ownership.resolve_owner_wave` returns `"C"` automatically when
  the finding flows through the audit-bridge into AUDIT_REPORT.json.
* **Phase 4.5 / 4.6 / 4.7 (cascade lift, anchor capture, wave-boundary
  block).** UNTOUCHED.

## Smoke evidence (when applicable)

NOT applicable to the Phase 5.8a source landing. The live diagnostic
smoke batch is operator-authorised separately ($150-300 minimum;
$300-600 worst case at the 10-smoke cap). The K.2 decision-gate
session reads the per-milestone `PHASE_5_8A_DIAGNOSTIC.json` artifacts
to flip the binary gate. See "Open follow-ups" below for the
authorisation pointer.

## Open follow-ups (not blocking Phase 5.8a)

* **Phase 5.8a smoke batch authorisation** — operator-authorised
  sequential M1+M2 diagnostic smokes. Stop-early predicate locked at
  the source level (`k2_decision_gate_satisfied`, threshold 3).
  Expected output per smoke: per-milestone
  `PHASE_5_8A_DIAGNOSTIC.json` at
  `<run-dir>/.agent-team/milestones/<id>/PHASE_5_8A_DIAGNOSTIC.json`.
  After the smoke batch, the K.2 evaluator session writes
  `PHASE_5_8A_DIAGNOSTIC_SUMMARY.md` with the aggregate outcome.
* **§K.2 decision-gate evaluator** — separate session; reads the
  per-milestone artifacts; either ships Phase 5.8b (full
  `cross_package_contract.py`) OR closes R-#42 via Wave A
  spec-quality investment.
* **Phase 5.7 closeout-smoke rows O.4.5–O.4.11** — Phase 5.7 carry-over;
  the eventual Phase 5.7 closeout smoke validates them. Phase 5.8a
  does NOT block on those.
* **§M.M11 calibration smoke for Phase 5.6** — Phase 5.6 carry-over;
  separate operator-authorised activity.
* **AC9 (Phase 5.8a smoke-only)** — locked at the source level via
  fixtures + schema; the live-smoke evidence is the §O.4.12 / O.4.13 /
  O.4.14 closeout rows, validated by the operator-authorised smoke
  batch.

## Out-of-scope items the plan flags but Phase 5.8a did NOT touch

* `cross_package_contract.py` — does NOT exist; Phase 5.8b ships it
  IF triggered.
* Wave A / Wave B / Wave D prompts — UNCHANGED. Wave A spec-quality
  investment is the §K.2 follow-up branch IF the K.2 evaluator decides
  R-#42 is closeable without 5.8b.
* AUDIT_REPORT.json schema — unchanged. The advisory finding flows
  through WAVE_FINDINGS.json (Phase 4.3 wave-bridge) and the scorer
  prompt instructs setting `verdict=UNVERIFIED` + `severity=LOW` if
  reflected; it does NOT add a new top-level field.
* Quality Contract gate filters — unchanged. Severity LOW + verdict
  UNVERIFIED never enters the HIGH/CRITICAL gate path.
* New top-level config flags — none added (per Q2: diagnostic is
  timeout-bounded, crash-isolated, cannot fail Wave C; no kill switch
  needed). Operators can simply ignore the LOW finding.

## Verification gates passed

* **Targeted slice (§0.5 + Phase 5.{1,2,3,4,5,6,7,8a} fixtures):**
  **994 passed** at HEAD post-Phase-5.8a (was 964 baseline + 30 new
  Phase 5.8a fixtures).
* **Module import smoke (§0.7):** clean — `cli`, `audit_team`,
  `audit_models`, `fix_executor`, `wave_executor`, `state`,
  `cross_package_diagnostic` (NEW), `openapi_generator`,
  `audit_prompts`, `quality_contract`, `state_invariants` all import
  without warnings.
* **Wide-net sweep (§0.6):** see commit message — was 2235 baseline + 4
  pre-existing failures; Phase 5.8a adds the new test file's fixtures
  on top.
* **mcp__sequential-thinking + context7:** sequential-thinking used
  for the type-class normalisation truth table + cross-pipe
  finding-promotion analysis (correction #2). Context7 not needed in
  practice — `@hey-api/openapi-ts` `types.gen.ts` shape was validated
  against frozen fixtures from `v18 test runs/m1-hardening-smoke-*`
  (e.g., `m1-hardening-smoke-20260425-043358/packages/api-client/types.gen.ts`).
* **Phase 5.7 / 5.6 / 5.5 / 5.4 / 5.3 / 5.2 / 5.1 / 4.x / 3.5 / 3 /
  2 / 1.6 / 1.5 / 1 fixtures:** all green byte-identical at HEAD
  post-Phase-5.8a (none of those primitives were touched).

## Surprises

* **No central finding-code catalogue.** The dispatch said "register
  in `audit_models.py` finding-code list (or wherever finding codes
  are catalogued; verify by grep)". `grep` confirmed there is no
  catalogue — codes are emitted as string literals at construction
  sites. Existing pattern for Wave-level finding codes: define the
  constant in the emitting module (`stack_contract.py`,
  `wave_executor.py`, `audit_scope.py`, `forbidden_content_scanner.py`).
  Phase 5.8a follows that pattern: the constant lives in
  `cross_package_diagnostic.py`.
* **Wave C runs in-process Python, not via Claude SDK.** `_execute_wave_c`
  invokes scripted `generate_openapi_contracts`. This means Phase 5.7's
  bootstrap watchdog has no surface here — but it also means a Phase
  5.8a diagnostic crash MUST NOT escape, because there's no Claude SDK
  retry / wave-fail safety net to absorb it. Hence the strict
  crash-isolation (Q2 contract).
* **`audit_prompts.py` extension requires careful wording.** The
  scorer is an LLM; the prompt extension must be unambiguous. Final
  wording locks `verdict=UNVERIFIED` + `severity=LOW` + the explicit
  "MUST NOT count toward unresolved-FAIL" sentence (correction #2).
* **`_coerce_contract_result` was a load-bearing detail.** The
  scope check-in's correction #5 caught what would otherwise have
  been a silent regression: the dataclass `ContractResult` reaches
  `_coerce_contract_result` before being passed as a dict downstream,
  so adding fields to the dataclass without updating the coerce
  helper would have lost diagnostics from the Wave C → wave_executor
  hand-off. Tests `test_coerce_contract_result_threads_diagnostic_fields`
  + `test_coerce_contract_result_legacy_dataclass_yields_empty_diagnostics`
  lock this contract.

---

**Phase 5.8a is the lowest-risk Phase 5 sub-phase** (advisory-only,
non-blocking, isolated diagnostic step) and lands as a single
source-only commit. The §K.2 decision-gate session is the next gate
for R-#42 full closure.
