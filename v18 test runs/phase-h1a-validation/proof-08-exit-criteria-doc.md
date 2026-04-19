# Proof 08 — PHASE_FINAL_EXIT_CRITERIA.md ↔ plan diff

## Feature

Phase H1a Item 8: `PHASE_FINAL_EXIT_CRITERIA.md` is a new repo-root file
(created by Wave 2C) that canonicalizes the 20 exit criteria previously
buried at `MASTER_IMPLEMENTATION_PLAN_v2.md:1086-1105`. The new file is
the source of truth; the plan copy may be stale. The new file's
checkbox lines must match the plan lines character-for-character so
nothing is silently reordered or dropped in the canonicalization.

## Production call chain

This is a documentation artifact, not a code path. The invariant is
structural: a textual equality between the two files' checkbox line
sets, so auditors can cite either file and get identical gating.

## Command

```bash
python "v18 test runs/phase-h1a-validation/scripts/proof_08_exit_criteria.py" \
  > "v18 test runs/phase-h1a-validation/proof_08_output.txt"
```

## Salient output

```
EXIT_CRITERIA checkbox count: 20
PLAN:1086-1105 checkbox count: 20

==============================================================================
Line-for-line diff (EXIT_CRITERIA vs PLAN)
==============================================================================
  [ 1] MATCH: - [ ] All milestones M1-M6 PASS...
  [ 2] MATCH: - [ ] ≤5 findings total across all milestones...
  [ 3] MATCH: - [ ] audit_health=passed for each milestone...
  [ 4] MATCH: - [ ] AUDIT_REPORT.json contains `scope` field (N-15)...
  [ 5] MATCH: - [ ] FIX_CYCLE_LOG.md populated (N-08 observability)...
  [ 6] MATCH: - [ ] Cascade findings consolidated (N-11)...
  [ 7] MATCH: - [ ] Framework idioms cache populated at `.agent-team/framework_idioms_cache.j...
  [ 8] MATCH: - [ ] STATE.json invariants consistent (NEW-7) — `summary.success` matches `fai...
  [ 9] MATCH: - [ ] No duplicate Prisma modules (NEW-1) — only src/database/ populated...
  [10] MATCH: - [ ] Scaffold self-verification passed (N-13) — port consistency check green...
  [11] MATCH: - [ ] SPEC.md reconciliation ran cleanly (N-12) — no RECONCILIATION_CONFLICTS.m...
  [12] MATCH: - [ ] **Wave T ran at least once on at least one milestone with non-empty test ...
  [13] MATCH: - [ ] **Codex app-server transport handled at least one Wave B dispatch success...
  [14] MATCH: - [ ] **All 6 post-Wave-E scanners ran on at least one milestone; results in au...
  [15] MATCH: - [ ] **UI_DESIGN_TOKENS.json loaded and consumed by Wave D.5 on at least one m...
  [16] MATCH: - [ ] Every Claude agent session shows `mcp__*` tools in allowed_tools (NEW-9 +...
  [17] MATCH: - [ ] At least one wedge recovery via `client.interrupt()` observed OR orphan d...
  [18] MATCH: - [ ] Budget stayed under $50 cap...
  [19] MATCH: - [ ] No regressions from baseline...
  [20] MATCH: - [ ] PHASE_FINAL_SMOKE_REPORT.md captures full coverage matrix mapping every N...

SUMMARY
==============================================================================
  checkbox count matches (20 == 20):                 True
  all 20 lines match line-for-line:                  True
```

## Interpretation

All 20 `- [ ]` checkbox lines under "Exit Criteria" in
`PHASE_FINAL_EXIT_CRITERIA.md` match `MASTER_IMPLEMENTATION_PLAN_v2.md`
lines 1086-1105 verbatim, including the three `**bold**` NEW-4/NEW-5/NEW-6
emphasis markers and the unicode `≤` and em-dash characters. The
new-doc header (lines 1-23 of PHASE_FINAL_EXIT_CRITERIA.md — the
must-pass/should-pass/may-pass categorization) is additive and does NOT
duplicate or conflict with the plan's list. **PASS.**

## Status: PASS
