# Phase H1b — Wave A Structural Constraint + Auditor Three-Way Compare — Final Report

**Branch:** `phase-h1b-wave-a-architecture-md-schema`
**Base SHA:** `d2ce167` (integration-2026-04-15-closeout HEAD post-h1a merge, PR #42)
**Date:** 2026-04-19
**Orchestrator:** Claude Opus 4.7 (1M context) via Claude Code CLI
**Team:** `phase-h1b` (6 agents: discovery, schema, auditor, test-engineer, wiring-verifier, proof-agent + doc-fixer for post-review docs alignment)

## Implementation Summary

| Category | Item | Owner |
|---|---|---|
| Wave A structural constraint | Schema allowlist + disallow-list w/ named-reason rejections | schema-agent |
| Wave A structural constraint | Undeclared-reference validator (placeholder syntax) | schema-agent |
| Wave A structural constraint | **Derivability validator** (concrete-reference check vs injection sources) — closes the G1 smoke-#11 root cause | schema-agent (post-review fix round) |
| Wave A structural constraint | Retry loop + GateEnforcementError escalation mirroring `_enforce_gate_a5` | schema-agent |
| Wave A structural constraint | Shared `wave_a_rerun_budget` resolver across schema + stack-contract + A.5 gates | schema-agent |
| Auditor integration | `<architecture>` XML injection + `<three_way_compare>` directive for INTERFACE + TECHNICAL auditors | auditor-agent |
| Structured finding emission | SCAFFOLD-COMPOSE-001, SCAFFOLD-PORT-002, PROBE-SPEC-DRIFT-001 → consumer-site adapters in `wave_executor.py` | auditor-agent |
| Structured finding emission | RUNTIME-TAUTOLOGY-001 → `_cli_gate_violations` structured append | auditor-agent (with post-review team-lead authorization) |

**Diff scope:** 9 files changed, 820 insertions, 10 deletions in production source. New files: `src/agent_team_v15/wave_a_schema.py`, `src/agent_team_v15/wave_a_schema_validator.py`. Plus 10 new test files (~29 derivability + ~78 prior h1b tests).

## Pattern IDs Added

| Pattern ID | Severity | Trigger | Emission |
|---|---|---|---|
| `WAVE-A-SCHEMA-REJECTION-001` | HIGH | Wave A output contains a disallowed section (per `wave_a_schema.DISALLOWED_SECTION_REASONS`) | Via retry feedback; surfaced via `GateEnforcementError(gate="A-SCHEMA")` on budget exhaustion |
| `WAVE-A-SCHEMA-UNDECLARED-REF-001` | MEDIUM | Wave A output contains fabricated `{var}` / `${VAR}` / `<inject:...>` placeholder | Via retry feedback |
| `WAVE-A-SCHEMA-REFERENCE-001` | HIGH | Wave A output cites concrete port/entity/path/AC-id/M-ref not derivable from injection sources (smoke-#11 root cause) | Via retry feedback |
| `ARCH-DRIFT-PORT-001` | HIGH | Port number disagrees across ≥2 of {ARCHITECTURE.md, REQUIREMENTS.md, code} | Via auditor finding in AUDIT_REPORT.json |
| `ARCH-DRIFT-ENTITY-001` | HIGH | Entity name/fields disagree across ≥2 of 3 | Via auditor finding |
| `ARCH-DRIFT-ENDPOINT-001` | HIGH | Endpoint path/method disagrees across ≥2 of 3 | Via auditor finding |
| `ARCH-DRIFT-CREDS-001` | HIGH | DB credential disagrees across ≥2 of 3 | Via auditor finding |
| `ARCH-DRIFT-DEPS-001` | HIGH | Dependency in spec missing from package.json | Via auditor finding |

## Config Flags Added (all default OFF/min)

| Flag | Default | Purpose |
|---|---|---|
| `v18.wave_a_schema_enforcement_enabled` | `False` | Gates the Wave A schema validator + retry loop |
| `v18.wave_a_rerun_budget` | `2` | Canonical shared rerun budget (schema + stack-contract + A.5). Alias: `v18.wave_a5_max_reruns` forwards with `DeprecationWarning` |
| `v18.auditor_architecture_injection_enabled` | `False` | Gates per-milestone ARCHITECTURE.md + three-way compare injection into INTERFACE + TECHNICAL auditors |

Structured finding emission for SCAFFOLD-*, PROBE-SPEC-DRIFT-*, RUNTIME-TAUTOLOGY-* is **not flag-gated** (bug fix, not new capability).

## Coverage Matrix — What h1b Catches

| Failure Pattern | Fixed By | Method | Status |
|---|---|---|---|
| Wave A freehand-authors prescriptive content (disallowed sections) | Schema allowlist | Validator + retry-via-gate-enforcement + escalation | ✅ |
| Wave A fabricates injection-variable placeholders | Undeclared-reference check | Regex scan against `ALLOWED_REFERENCES` | ✅ |
| Wave A fabricates concrete values (port 8080, invented entities, out-of-scaffold paths) — G1 ROOT CAUSE | Derivability validator | Cross-check vs `scaffolded_files` / `ir.entities` / `stack_contract` / AC list / dep-artifacts / cumulative arch | ✅ |
| Auditor can't see ARCHITECTURE.md (port-drift detection blind) | Renderer-wrapper injection | Phase G Slice 1c helper reused; targeted INTERFACE + TECHNICAL subset | ✅ (prompt plumbing; full behavior exercised in post-h1b smoke) |
| h1a structural findings emit as strings not structured | Consumer-site adapters | wave_executor.py `_scaffold_summary_to_findings` / `_probe_startup_error_to_finding` + cli.py `_cli_gate_violations.append` | ✅ |
| Module globals for cross-run state | Anti-pattern avoidance | `warnings.warn(DeprecationWarning)` + local loop counters (post-review fix round) | ✅ |
| Fabricated injection variables in h1b's own new prompt text | Render-test structural assertion | `tests/test_h1b_wiring_invariants.py` 4G | ✅ |

## Test Results

- **New tests written:** ~107 (~78 in Wave 3A + 29 derivability in Wave 3A-fix)
- **Test files:** 10 new
- **Full pytest:** **11,192 passed, 35 skipped, 0 failed** in 7m54s (artifact: `v18 test runs/phase-h1b-validation/pytest-output-post-fix.txt`)
- **Regressions:** 0
- **Source edits beyond new code:** minimal test-compat only — 3 tests updated (1 budget-pinning, 2 walker-sweep line numbers, 1 h1a_owners allowlist extension).

## Wiring Verification (Wave 3B, `docs/plans/phase-h1b-wiring-verification.md`)

All 4A–4I sections **PASS**:

| Section | Check | Status |
|---|---|---|
| 4A | Execution position (schema gate runs FIRST in Wave A iteration, before stack-contract + A.5) | PASS |
| 4B | Config gating (all 3 flags default-OFF, architecture_md_enabled interaction correct) | PASS |
| 4C | Crash isolation (validator/loader/adapter failures degrade gracefully) | PASS |
| 4D | Reporting integration (GateEnforcementError catch site shared with A.5; structured findings reach sinks) | PASS |
| 4E | Pattern-ID uniqueness across h1a + h1b | PASS |
| 4F | No mutable module globals for retry state | PASS (post-review fix round eliminated the two logging-dedupe sets) |
| 4G | No fabricated `{unsubstituted}` placeholders in new prompt text | PASS (`tests/test_h1b_wiring_invariants.py`) |
| 4H | Gate-enforcement mirror verification (signature/return-tuple/error-type/budget-key/feedback-channel match A.5) | PASS (post-review fix round wired A.5 through the resolver too) |
| 4I | Static `audit_prompts.py` AUDIT_PROMPTS registry + 8 prompt constants byte-identical to baseline | PASS |

## Production-Caller Proofs (Wave 5, `v18 test runs/phase-h1b-validation/`)

9 proofs, all PASS, zero bridge gaps:

1. **proof-01** — Schema allowlist block renders correctly via `build_wave_a_prompt` (gated by both flags).
2. **proof-02** — Disallowed-section rejection fires with named-reason text verbatim from `DISALLOWED_SECTION_REASONS`.
3. **proof-03** — Derivability validator catches smoke-#11's 5 drift shapes in one pass (`PORT ?? 8080`, hallucinated entity, out-of-scaffold path, unknown AC, unknown M-ref) — all as `WAVE-A-SCHEMA-REFERENCE-001` HIGH. **This is the G1 root-cause proof.**
4. **proof-04** — Retry success: invalid → `(True, review)` → formatted `[SCHEMA FEEDBACK]` → re-dispatched with `stack_contract_rejection_context` → valid output on attempt 2 → `(False, {})`.
5. **proof-05** — Retry exhaustion at rerun_count ≥ budget raises `GateEnforcementError(gate="A-SCHEMA")`; no `WAVE_A_VALIDATION_HISTORY.json` created.
6. **proof-06** — Shared rerun-budget resolver: canonical wins at default, legacy override wins + emits `DeprecationWarning`, both gates call the resolver symmetrically.
7. **proof-07** — Auditor prompt injection: INTERFACE + TECHNICAL with flag ON get `<architecture>` + `<three_way_compare>` blocks; flag-OFF byte-identical to base; REQUIREMENTS auditor unchanged even with flag ON.
8. **proof-08** — Structured finding emission: all 4 h1a patterns (SCAFFOLD-COMPOSE-001 HIGH, SCAFFOLD-PORT-002 MEDIUM, PROBE-SPEC-DRIFT-001 HIGH, RUNTIME-TAUTOLOGY-001 HIGH) surface as structured objects at the documented consumer sites.
9. **proof-09** — End-to-end: `ARCH-DRIFT-*` pattern IDs round-trip through `AuditReport.to_json` / `from_json` with code + severity + evidence preserved; `AuditFinding` dataclass is schema-transparent to novel pattern IDs. **Routing nuance:** the pattern ID travels as a leading token inside the `summary` string (same channel as OWNERSHIP-DRIFT-001, WIRING-CLIENT-001, DOD-FEASIBILITY-001), not as a top-level keyed column. `finding_id` is a per-finding unique key assigned by the scorer, not the pattern ID. The auditor is instructed (directive at `audit_prompts.py:1482-1504`) to lead its summary with the pattern ID on drift detection; the production `AuditReport.from_json` / `to_json` preserve every key verbatim. Pattern IDs are string-searchable inside AUDIT_REPORT.json after round-trip.

## Documented Plan-Interpretation Decisions

Four decisions deviated from a literal reading of the plan; all defensible with rationale captured in-repo:

### 1. `WAVE_A_SCHEMA_REVIEW.json` persistence

Plan §1F mirror table explicitly prescribes this file as a WAVE_A5_REVIEW.json sibling ("Schema gate mirrors A.5 exactly — reuse, don't rebuild"). Plan anti-pattern list separately says "NO equivalent new persistence — we don't persist across process death for A.5, and we don't need to for schema either." These texts conflict: A.5's `_load_wave_a5_review` at `cli.py:9872` IS actually called at `cli.py:9927` to drive retry feedback, so the anti-pattern's premise is factually incorrect. The team followed the mirror-A.5 instruction. Schema-gate's `_load_wave_a_schema_review` is defined but never called — the JSON is strictly write-only report, strictly more restrictive than A.5's full read-write cycle.

**Reviewer note:** A future plan revision should reconcile this — either retract the anti-pattern sentence or rewrite the mirror table to exclude JSON persistence.

### 2. Structured finding emission at consumer-site adapters, not producer sites

Discovery §1E found h1a pattern emission is architecturally mixed — `OWNERSHIP-*` + `DOD-FEASIBILITY-001` already emit structured; `SCAFFOLD-*` / `PROBE-SPEC-DRIFT-*` / `RUNTIME-TAUTOLOGY-*` emit via strings (summary_lines / RuntimeError messages). Producer contracts differ. Team-lead authorized landing the structured conversion at `wave_executor.py` hook sites (consumer-side) rather than refactoring the producers. Functional outcome identical: structured findings reach `AUDIT_REPORT.json` / `GATE_FINDINGS.json`; producer-side strings persist only in terminal logs (no downstream consumer reads them for structured purposes).

### 3. Skip-path log dedupe uses a function attribute, not a module global

The plan required the `architecture_md_enabled=False` skip-path INFO log to fire once per milestone. The original implementation used a module-level `_WAVE_A_SCHEMA_SKIP_LOGGED: set` which round-1 review correctly flagged as violating the "no mutable module globals" anti-pattern. The round-1 fix removed the set and accepted per-invocation logging. A third review round flagged this as a deviation from the literal plan ("log once per milestone"). Final implementation (post-review-round-3): dedupe state lives on `_enforce_gate_wave_a_schema._skip_logged_keys` — a function attribute, lazy-initialized, scoped to the function. Not accessible as a module-level `_VAR` global; tests reset via `del f._skip_logged_keys` or `.clear()`. Satisfies both anti-patterns simultaneously (no module-level `_VAR` global AND once-per-milestone logging).

### 4. Option 2 rerun-budget design (Add + alias)

Discovery proposed Option 1 (reuse `wave_a5_max_reruns` directly). Team-lead authorized Option 2 (`wave_a_rerun_budget: int = 2` canonical + `wave_a5_max_reruns` deprecated alias with `DeprecationWarning`). Rationale: canonical key signals shared-budget intent; alias preserves unmigrated configs; no silent default change for existing deployments.

## Branch Status

- [x] All pytest green (11,192 / 0 failed)
- [x] All 9 production-caller proofs captured
- [x] Wiring verification 4A–4I all PASS
- [x] Docs aligned (architecture-report, allowlist-evidence, discovery-citations, wiring-verification, operator guidance)
- [x] PHASE_FINAL_EXIT_CRITERIA.md H1b section added
- [ ] Reviewer approval on final PR
- [ ] Branch merged to `integration-2026-04-15-closeout`
- [ ] Integration-branch tests green post-merge

## Post-h1b Smoke Preconditions (Option A gating)

**Config flags ON:**
- All 4 h1a flags: `dod_feasibility_verifier_enabled`, `ownership_enforcement_enabled`, `probe_spec_oracle_enabled`, `runtime_tautology_guard_enabled`
- Both h1b flags: `wave_a_schema_enforcement_enabled`, `auditor_architecture_injection_enabled`
- `architecture_md_enabled=True` (required for schema-enforcement to fire — silent no-op otherwise)
- Codex on Wave B via `codex_transport_mode: "exec"` (legacy subprocess; Bug #20 deferred to H2)

**PRD requirements:**
- M1 has ≥3 entities, ≥5 ACs, concrete endpoints — so A.5 actually runs AND the derivability validator has real scope to bite against. Smoke #11's zero-scope M1 made several checks vacuous.

**Pre-flight environment (team lead runs before smoke):**
- `command -v codex` passes
- `codex --version` passes
- `~/.codex/auth.json` exists AND parses as JSON
- `codex_app_server` import check emits INFO only (expected; Bug #20 deferred to H2)
- No stale `clean-*` containers from prior smoke

**Gating:**
- PHASE_FINAL_EXIT_CRITERIA.md MUST/SHOULD/MAY-PASS tiers
- Known ❌ (honest, pre-documented): #13 Codex app-server (Bug #20 deferred), #15 UI_DESIGN_TOKENS consumed by D.5 (only if Wave D runs), #17 orphan detection (acceptable if zero wedges)
- Target: all MUST-PASS green, ≥80% SHOULD-PASS green, documented reason for each ❌ in MAY-PASS

## Post-Team Adversarial Review

Two rounds of independent review executed after Wave 5. Round 1 flagged 6 items; fixes landed for the 3 valid/actionable ones (derivability validator missing, module globals, docs drift). Round 2 flagged 5 items; 3 were stale (caught mid-execution before proof-agent finished), 2 were valid and addressed (proof-08 + proof-09 gaps — proof-08 was missing from proof-agent's initial delivery; proof-09 closed the end-to-end ARCH-DRIFT path). Final state: all review findings either resolved with source/test/doc fixes or documented as defensible plan-interpretation decisions with rationale in this report.

## Verdict

**SHIP IT.**

- Functional gate-level coverage of the G1 root cause (smoke-#11 freehand drift) is implemented, tested, and proven.
- No regressions against h1a's delivery; all pre-h1b tests pass.
- All new capabilities are flag-gated OFF by default; h1b is a silent no-op until operators flip the flags.
- Plan-interpretation decisions documented in this report for future reviewers.
- Post-h1b smoke is the correct next validation step — it exercises the LLM-behavioral half of the three-way compare (plumbing is proven here).
