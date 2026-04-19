# Phase FINAL — Exit Criteria

Canonical gating list for the Phase FINAL smoke. This file is the source of truth; the copy in MASTER_IMPLEMENTATION_PLAN_v2.md may be stale.

The post-h1b smoke (smoke #12) will be scored against these 20 criteria. These are not equal-weight: some criteria are load-bearing, others are diagnostic.

MUST-PASS criteria (any failure = smoke fails):
- #1 All milestones M1-M6 PASS
- #12 Wave T ran at least once
- #3 audit_health=passed for each milestone

SHOULD-PASS criteria (≥80% required):
- #4, #5, #6, #7, #8, #9, #10, #11 (structural quality markers)

MAY-PASS criteria (diagnostic, honest ❌ acceptable with documentation):
- #13 Codex app-server dispatch (❌ expected — Bug #20 deferred to H2)
- #14 post-Wave-E scanners (partial expected if D/T/T.5/E didn't all run)
- #15 UI_DESIGN_TOKENS consumed by D.5 (depends on Wave D running)
- #17 orphan detection / wedge recovery (zero firings acceptable if zero wedges)

Item #20 (PHASE_FINAL_SMOKE_REPORT.md captures coverage matrix) is an output, not a pass/fail criterion — write it regardless.

A "pass" means: all MUST-PASS criteria green AND ≥80% of SHOULD-PASS green AND all ❌ in MAY-PASS are accompanied by a documented reason.

- [ ] All milestones M1-M6 PASS
- [ ] ≤5 findings total across all milestones
- [ ] audit_health=passed for each milestone
- [ ] AUDIT_REPORT.json contains `scope` field (N-15)
- [ ] FIX_CYCLE_LOG.md populated (N-08 observability)
- [ ] Cascade findings consolidated (N-11)
- [ ] Framework idioms cache populated at `.agent-team/framework_idioms_cache.json` (N-17)
- [ ] STATE.json invariants consistent (NEW-7) — `summary.success` matches `failed_milestones`
- [ ] No duplicate Prisma modules (NEW-1) — only src/database/ populated
- [ ] Scaffold self-verification passed (N-13) — port consistency check green
- [ ] SPEC.md reconciliation ran cleanly (N-12) — no RECONCILIATION_CONFLICTS.md emitted
- [ ] **Wave T ran at least once on at least one milestone with non-empty test output (NEW-3)**
- [ ] **Codex app-server transport handled at least one Wave B dispatch successfully (NEW-4 + Bug #20)**
- [ ] **All 6 post-Wave-E scanners ran on at least one milestone; results in audit report (NEW-5)**
- [ ] **UI_DESIGN_TOKENS.json loaded and consumed by Wave D.5 on at least one milestone (NEW-6)**
- [ ] Every Claude agent session shows `mcp__*` tools in allowed_tools (NEW-9 + NEW-10)
- [ ] At least one wedge recovery via `client.interrupt()` observed OR orphan detection fired (NEW-10)
- [ ] Budget stayed under $50 cap
- [ ] No regressions from baseline
- [ ] PHASE_FINAL_SMOKE_REPORT.md captures full coverage matrix mapping every N-item + NEW-item + latent wiring to its validation evidence

## H1b — Operator guidance for new flags

Phase H1b adds three new `v18` config keys. All default `False` / `2`; h1b is a silent no-op until operators flip them on.

### `v18.wave_a_schema_enforcement_enabled: bool = False`

Enables the Wave A ARCHITECTURE.md schema gate. When True, the gate:
- Validates allowed / disallowed H2 sections against the allowlist in `src/agent_team_v15/wave_a_schema.py`
- Rejects fabricated injection-variable placeholders (`WAVE-A-SCHEMA-UNDECLARED-REF-001` MEDIUM)
- Rejects hardcoded concrete references (ports, entity names, file paths, AC IDs) that aren't derivable from the Wave A injection sources (`WAVE-A-SCHEMA-REFERENCE-001` HIGH) — closes the smoke #11 `PORT ?? 8080` class of drift
- Retries up to `wave_a_rerun_budget` times via the existing `[PRIOR ATTEMPT REJECTED]` feedback channel
- Raises `GateEnforcementError(gate="A-SCHEMA")` on retry exhaustion

**Interaction:** silent no-op when `v18.architecture_md_enabled=False` (Wave A doesn't emit ARCHITECTURE.md, so there's nothing to validate). Operators flipping the schema flag MUST also ensure `architecture_md_enabled=True` — an INFO log fires once per milestone when the schema flag is on but ARCHITECTURE.md emission is off.

### `v18.wave_a_rerun_budget: int = 2`

Canonical shared rerun budget across schema gate + stack-contract rejection retry + A.5 gate. Worst case: 1 initial Wave A rollout + `wave_a_rerun_budget` reruns = `1 + N` rollouts per milestone. Cost impact: at ~$0.50–2 per rollout × 5 milestones, budget=2 caps Wave A overhead at ~$7.50–30/smoke.

**Legacy alias:** `v18.wave_a5_max_reruns` is preserved for backwards-parse. When set to any non-default value, `_get_effective_wave_a_rerun_budget` forwards it as the effective budget and emits a `DeprecationWarning` (once per source location). Update configs to use the canonical key.

### `v18.auditor_architecture_injection_enabled: bool = False`

Enables per-milestone ARCHITECTURE.md XML injection into the INTERFACE + TECHNICAL auditor prompts, plus a `<three_way_compare>` directive. When True, those two auditors cross-check entity names / ports / endpoints / DB credentials / package dependencies across the three documents (ARCHITECTURE.md, REQUIREMENTS.md, generated code) — emitting `ARCH-DRIFT-{PORT,ENTITY,ENDPOINT,CREDS,DEPS}-001` HIGH findings when two of three disagree.

**Graceful skip:** when per-milestone ARCHITECTURE.md is missing, the renderer skips injection silently and falls back to the base prompt. Operators flipping this flag without also flipping `architecture_md_enabled` will see the flag active but no injections until ARCHITECTURE.md exists.

### Suggested rollout for the post-h1b smoke

- Flip ALL h1a flags ON: `dod_feasibility_verifier_enabled`, `ownership_enforcement_enabled`, `probe_spec_oracle_enabled`, `runtime_tautology_guard_enabled` (shipped in PR #42; see that PR's description for operator guidance).
- Flip `wave_a_schema_enforcement_enabled=True` AND `architecture_md_enabled=True` together.
- Flip `auditor_architecture_injection_enabled=True`.
- Leave `wave_a_rerun_budget` at default 2 (or explicitly set to 2 for auditability).
- PRD must have ≥3 entities and ≥5 ACs on M1 so A.5 and the derivability validator have real scope to bite against — smoke #11's zero-scope M1 made several checks vacuous.
