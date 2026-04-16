# Session A — Phase A Production-Caller Validation

**Date:** 2026-04-16
**Branch:** phase-a-foundation
**Scope:** N-01, N-15, NEW-7, NEW-8, State.finalize silent-swallow fix, cli.py:13491 `except: pass` upgrade to `print_warning`.

## Purpose

Per MASTER_IMPLEMENTATION_PLAN_v2.md inviolable rule #3 ("No 'validated' without
end-to-end proof"), every phase lands a production-caller-proof artifact that
shows the change actually fires on the hot path — not only in unit tests.

This directory contains deterministic scripts that exercise the production
entry points of each Phase A change against fixtures derived from build-l's
preserved state (where available) or synthetic fixtures (where the real
fixture is missing because build-l halted early).

## Artefacts

| Script | Proves |
|--------|--------|
| `validate_extras_roundtrip.py` | N-15: loading build-l's scorer-raw `AUDIT_REPORT.json` via `AuditReport.from_json` then re-serializing via `to_json` preserves all 14 scorer-side extras keys (verdict, health, threshold_pass, overall_score, schema_version, generated, milestone, notes, category_summary, finding_counts, deductions_total, deductions_capped, pass_notes, summary, score_breakdown, dod_results, raw_finding_count, deduplicated_finding_count). |
| `validate_port_detection.py` | N-01: the 6-source precedence chain (config.browser_testing.app_port → root `.env` → `apps/api/.env.example` → `apps/api/src/main.ts` → `docker-compose.yml` → loud `:3080` fallback) all resolve correctly and produce a single LOUD WARNING when all five detection sources return None. |
| `validate_state_invariants.py` | NEW-7: given a state mirroring build-l's root cause (`failed_milestones=['milestone-1']` + explicit `summary={"success": True}`), `save_state` refuses the write and raises `StateInvariantError`; given a clean state with unset summary, save_state auto-computes `success=False` without raising. |
| `validate_finalize_warning.py` | cli.py:13491 fix: a `finalize()` throw now surfaces as `print_warning` output instead of being silently swallowed. |
| `RESULTS.md` | Per-script pass/fail, observed vs expected, timestamp. |
| `phase_a_full.log` / `phase_a_full_v2.log` | Raw pytest output (test-engineer artefact). |
| `pytest-baseline.txt` | Human-readable test-count summary (test-engineer artefact). |

## Production-caller coverage

Each script walks the same import chain that cli.py uses in a real run. No
mocks of `AuditReport` or `RunState` — only synthetic input data feeding the
real constructors + real methods.

## How to run

```bash
cd C:/Projects/agent-team-v18-codex
python "v18 test runs/session-A-validation/validate_extras_roundtrip.py"
python "v18 test runs/session-A-validation/validate_port_detection.py"
python "v18 test runs/session-A-validation/validate_state_invariants.py"
python "v18 test runs/session-A-validation/validate_finalize_warning.py"
```

Each script exits 0 on success, non-zero on any assertion failure, and echoes
a structured PASS/FAIL line per sub-check.

## Why not `pytest`?

These are production-caller proofs, not unit tests. They load real fixtures
(build-l's preserved JSON) and run them through the actual import chain.
Unit tests live in `tests/`. This directory is the "does the fix fire in
production" audit trail per N-14 template (doc TBD in Phase C).
