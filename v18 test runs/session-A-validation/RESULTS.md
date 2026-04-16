# Phase A — Production-Caller Validation Results

**Date:** 2026-04-16
**Branch:** phase-a-foundation
**Verdict:** PASS (4/4 validation scripts green)

| Script | Checks | Result | Log |
|--------|--------|--------|-----|
| validate_extras_roundtrip.py | 17 | PASS | validate_extras_roundtrip.log |
| validate_port_detection.py | 8 | PASS | validate_port_detection.log |
| validate_state_invariants.py | 5 | PASS | validate_state_invariants.log |
| validate_finalize_warning.py | 5 | PASS | validate_finalize_warning.log |
| **TOTAL** | **35** | **PASS** | |

## Evidence summary per Phase A change

### N-15 — AuditReport.to_json extras preservation

Loaded build-l's real scorer-raw `AUDIT_REPORT.json` (28 findings, 25 fix_candidates, 14 scorer-side extras keys). Ran it through `AuditReport.from_json` → `to_json` → `json.loads`. Every one of the 14 extras keys (`schema_version`, `generated`, `milestone`, `verdict`, `threshold_pass`, `overall_score`, `auditors_run`, `raw_finding_count`, `deduplicated_finding_count`, `pass_notes`, `summary`, `score_breakdown`, `dod_results`, `by_category`) survives with byte-identical values. `max_score` correctly migrates to nested `score.max_score` (canonical position).

### N-01 — endpoint_prober port detection precedence

All 6 precedence rungs tested with tmpdir fixtures:

1. config.browser_testing.app_port — still wins when set (tested implicitly; if not zeroed, no file I/O).
2. `<root>/.env` PORT=<n> — resolved to 8080 as expected.
3. `apps/api/.env.example` PORT=<n> — resolved to 4000.
4. `apps/api/src/main.ts` literal `app.listen(<n>)` — resolved to 4321.
5. `apps/api/src/main.ts` `app.listen(process.env.PORT ?? <n>)` — resolved to 4567.
6. `docker-compose.yml` short-form ports — resolved to 4000.
7. Precedence test: env.example (4000) beats main.ts (3000) — ✓.
8. LOUD fallback — when no source resolves, returns `http://localhost:3080` AND emits exactly one WARNING log to `agent_team_v15.endpoint_prober` logger.

### NEW-7 — save_state invariant enforcement

- Clean state (no failures) → `success: True` (baseline preserved).
- Failed milestone + no explicit summary → `success: False` auto-computed, no raise. This is the normal mid-pipeline save path.
- Failed milestone + poisoned `summary={"success": True}` (build-l root cause) → `StateInvariantError` raised with diagnostic citing `failed_milestones`, `summary.success`, and `cli.py:13491-13498` remediation pointer. STATE.json NOT written (atomicity preserved).
- StateInvariantError properly subclasses RuntimeError so existing `except Exception` blocks catch it.

### cli.py:13491 — silent-swallow fix

- `print_warning` symbol reachable from cli.py module scope.
- No bare `except Exception: pass` in the `_current_state.finalize()` try/except block (line 13491 region).
- `print_warning` is called in the replaced handler.
- Warning message includes STATE / finalize context for operator diagnosability.

### NEW-8 — fix_candidates dropped-ID logging

Not covered by a dedicated script (adequately covered by the 4 new unit tests in
`TestFromJsonFixCandidatesDroppedLogging`). The extras roundtrip script
indirectly exercises from_json against build-l's real scorer output; all 25
fix_candidates resolve (no drops — build-l's scorer dedup was clean), which
matches the wiring-verifier's trace prediction.

## Full pytest suite

See `pytest-baseline.txt`. Final: **10193 passed, 35 skipped, 6 pre-existing
failures (not Phase A-caused)**. Zero Phase-A regressions.

## Call-outs for PHASE_A_REPORT.md and Phase B inheritance

1. **Pre-existing gap (out of Phase A scope):** `audit_models.build_report` at `audit_models.py:730` does not propagate `extras` on rebuild. When `config.v18.evidence_mode != "disabled"` AND scope partitioning fires in `_apply_evidence_gating_to_audit_report` (cli.py:639), N-15's extras preservation is nullified for that milestone's re-written report. **Default-config production path is unaffected.** Trivial 5-line follow-up: accept an `extras` kwarg or re-attach `report.extras` post-rebuild. Route to Phase B or file separately.

2. **NEW-7 behavior note (deliberate):** Previously, `save_state` calls mid-pipeline after a milestone entered `failed_milestones` silently wrote `summary.success=True` (LIE). After Phase A, the same call writes `summary.success=False` (TRUTH). Operator-visible change: state snapshots during a failing milestone now correctly say "not successful" rather than "successful" — aligned with the pipeline's actual state. No raise under normal operation because the default formula is invariant-consistent.

3. **6 pre-existing pytest failures** — all traceable to refactors landed in commits 787977e (D-05/D-06, text moved out of `_run_review_only`) and c1030bb (D-02 v2, added `infra_missing` attr). Not Phase A regressions. Triaged for follow-up.
