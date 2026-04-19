# Phase C Plan — Audit Plumbing + Scaffold Emission Closeout

**Date created:** 2026-04-16
**Base branch:** `integration-2026-04-15-closeout` HEAD (post-Phase-B merge: `a0a053c`)
**Branching strategy:** fresh branch `phase-c-audit-plumbing` from integration HEAD (no more stacked branches)
**Predecessor:** Phase B commit `a0a053c` — Scaffold + Spec Alignment (11 items + 6 feature flags, all default FALSE)

---

## Carry-forward items from Phase B (MUST close)

Phase B exited with 4 non-HALT findings filed for Phase C. Total carry-forward scope: **~115 LOC**.

### C-CF-1 (MUST close before Phase FINAL smoke) — OOS-1: AuditFinding.from_dict scorer-shape evidence gap

**Severity:** MEDIUM
**Source:** Phase B wiring verification §OOS-1 (docs/plans/2026-04-16-phase-b-wiring-verification.md) and Phase B report §Out-of-Scope Findings Filed for Phase C.

**Problem:** `audit_models.AuditFinding.from_dict` does not map scorer-shape `file` / `description` keys into `evidence[]`. When the scorer produces a finding with those keys but no explicit `evidence[]` array (the common case in real LLM audit output), `from_dict` leaves `evidence` empty. N-11 cascade consolidation pattern-matches on `evidence[]` / `primary_file` / `summary` for root-cause clustering — absent evidence means cascade is blind to file paths.

**Evidence:** build-l's 28 real audit findings collapsed 28→28 (zero cascade) in Phase B's V3 offline replay because all 28 hit this path. Synthetic path-bearing input collapsed 6→4 correctly. The algorithm is right; the plumbing is wrong.

**Fix shape:** extend `AuditFinding.from_dict` so that when `evidence` is absent but `file` and/or `description` keys are present, synthesize `evidence[0] = f"{file} — {description[:80]}"` (or similar minimal fold).

**Scope:** ~10 LOC + 3-4 tests covering (a) canonical shape with explicit evidence (unchanged), (b) scorer shape with file+description fold, (c) scorer shape with file only (no description), (d) build-l-style real input produces non-empty evidence after from_dict.

**Blocker relationship:** Phase FINAL smoke cannot validate N-11 cascade effectiveness against real audit output until this closes. N-11 remains correct algorithmically; it just has no substrate to match on.

### C-CF-2 (MUST close before `ownership_contract_enabled + scaffold_verifier_enabled` can run simultaneously) — OOS-3 + OOS-4: 8 scaffold-owned paths not emitted

**Severity:** MEDIUM (OOS-3) + LOW (OOS-4, turbo.json residual)
**Source:** Phase B wiring verification §OOS-3 + team-lead DRIFT-4 residual flag during Wave 2.

**Problem:** `docs/SCAFFOLD_OWNERSHIP.md` assigns 8 files to scaffold with `optional: false` + `audit_expected: true`, but current scaffold emission does NOT produce them:

1. `apps/api/nest-cli.json` — NestJS CLI requires this for `nest build` to resolve src entry
2. `apps/api/tsconfig.build.json` — standard NestJS build config excluding test/
3. `apps/api/src/modules/auth/auth.module.ts` — empty NestJS module stub (Wave B extends with strategies in later milestones)
4. `apps/api/src/modules/users/users.module.ts` — empty stub
5. `apps/api/src/modules/projects/projects.module.ts` — empty stub
6. `apps/api/src/modules/tasks/tasks.module.ts` — empty stub
7. `apps/api/src/modules/comments/comments.module.ts` — empty stub
8. `turbo.json` — pipeline orchestrator config for `pnpm -r build/test/lint`

**Impact:** Currently flag-OFF default is unaffected. But **simultaneous activation of `v18.ownership_contract_enabled` + `v18.scaffold_verifier_enabled` would FAIL** because the verifier enumerates contract-required scaffold paths and finds 8 missing — flipping `wave_result.success=False` and halting Wave B dispatch. Individual flag-ON use remains safe.

**Fix shape:**
- Add 8 new template helper functions + `_scaffold_api_nest_cli_template`, `_scaffold_api_tsconfig_build_template`, per-module stub template (parameterized by feature name), `_scaffold_root_turbo_template`
- Extend `_scaffold_api_foundation` and `_scaffold_root_files` to call them
- For the 5 module stubs: use `ScaffoldConfig.modules_path` (already `src/modules` per default) so emission tracks canonical path

**Scope:** ~100 LOC total (~12 per template × 8 templates + wiring). Plus tests per stub + plus integration test that flag-ON verifier reports PASS on a fresh scaffold tree.

**Blocker relationship:** coordination warning in Phase B report explicitly says "do NOT enable ownership_contract_enabled + scaffold_verifier_enabled simultaneously in live smoke until OOS-3 closes." Phase C closes this blocker.

### C-CF-3 (MUST close before Phase FINAL smoke) — Phase A inheritance: build_report extras propagation

**Severity:** LOW (narrow trigger path)
**Source:** Phase A report §"Call-outs for Phase B and beyond" #1 + Phase A report §N-15 "Known gap (out of scope)".

**Problem:** `audit_models.build_report` at line ~730 does NOT propagate `extras` into the rebuilt AuditReport. When `_apply_evidence_gating_to_audit_report` rebuilds a report via `build_report`, the 14+ scorer-side top-level keys (verdict, health, notes, category_summary, finding_counts, deductions_total, deductions_capped, overall_score, threshold_pass, auditors_run, schema_version, generated, milestone, raw_finding_count, deduplicated_finding_count, pass_notes, summary, score_breakdown, dod_results, by_category) that D-07's `from_json` captures onto `extras` at `audit_models.py:342` are stripped.

**Trigger:** only fires when `config.v18.evidence_mode != "disabled"` AND scope partitioning fires. Default-config production path unaffected.

**Fix shape:** `build_report` accepts `extras: dict | None = None` kwarg; re-attaches post-rebuild OR spreads `**extras` into constructed AuditReport. Mirror N-15's `to_json` spread-first pattern.

**Scope:** ~5 LOC + 2 tests (extras preserved after build_report; scope partitioning rebuild preserves scorer keys).

**Blocker relationship:** Phase FINAL smoke may exercise evidence_mode != "disabled" path. Pre-smoke closure ensures extras don't silently drop.

### Carry-forward LOC total: ~115

- C-CF-1: ~10 LOC
- C-CF-2: ~100 LOC
- C-CF-3: ~5 LOC

All three are structural fixes (no containment patches). All three have clear independent scope — no cross-cutting coordination needed between them. Can ship as 3 independent commits or bundled depending on orchestration choice.

---

## Phase C exit criteria

- [ ] C-CF-1 closed: `AuditFinding.from_dict` synthesizes evidence from scorer-shape file+description; N-11 cascade on build-l's real AUDIT_REPORT.json produces non-zero collapse (target: 28 → ≤20)
- [ ] C-CF-2 closed: scaffold emits 8 previously-missing scaffold-owned paths; verifier run on clean scaffold tree with `ownership_contract_enabled + scaffold_verifier_enabled` both ON produces verdict=PASS
- [ ] C-CF-3 closed: `build_report` preserves extras through scope-partitioning rebuild path; scorer-side keys survive byte-identical
- [ ] Full pytest: 10,275 baseline preserved + new Phase C tests passing + 6 pre-existing failures unchanged + ZERO regressions
- [ ] Phase C report at `docs/plans/2026-04-16-phase-c-report.md`
- [ ] Phase C commit on fresh branch `phase-c-audit-plumbing`

---

## Scope boundaries — what's NOT in Phase C

Phase C is narrow carry-forward closure. The following are explicitly out of scope and belong to Phase FINAL smoke / Phase D / later:

- Live paid smoke run validating flags end-to-end
- N-08 audit-fix iteration wiring (separate session)
- N-09 Wave B prompt quality hardeners
- N-10 content auditor
- N-17 MCP-informed wave dispatches
- NEW-10 ClaudeSDKClient bidirectional migration (Sessions 16.5 + 17 + 18)
- Bug #20 Codex app-server migration

All of these are tracked elsewhere (investigation report Parts 4, 7, 8) and have their own planning documents.

---

## Prerequisites from Phase B

Phase B shipped the following that Phase C depends on:

- 6 feature flags (all default FALSE): `ownership_contract_enabled`, `spec_reconciliation_enabled`, `scaffold_verifier_enabled`, `cascade_consolidation_enabled`, `duplicate_prisma_cleanup_enabled`, `template_version_stamping_enabled`
- `docs/SCAFFOLD_OWNERSHIP.md` 60-entry contract (authoritative)
- `scaffold_runner.ScaffoldConfig` + `DEFAULT_SCAFFOLD_CONFIG` (Phase C's new scaffold templates consume `ScaffoldConfig.modules_path` for module stubs)
- `milestone_spec_reconciler.py` + `scaffold_verifier.py` (both tested and wired)
- `audit_models.AuditFinding` extended with `cascade_count` + `cascaded_from` optional fields (Phase C's `from_dict` fix preserves backward compat)

Phase B post-merge integration HEAD: `a0a053c`. Phase C branches from this.
