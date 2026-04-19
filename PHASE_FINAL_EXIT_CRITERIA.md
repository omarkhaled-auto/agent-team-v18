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
