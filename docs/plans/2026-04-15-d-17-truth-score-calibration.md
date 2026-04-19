# D-17 — Truth-score calibration: `error_handling=0.06`, `test_presence=0.29`

**Tracker ID:** D-17
**Source:** §8 finding 3
**Session:** 8
**Size:** M (~80 LOC)
**Risk:** LOW
**Status:** plan

---

## 1. Problem statement

Build-j's truth score is 0.6787, with specific dimensions:
- `requirement_coverage: 0.70`
- `error_handling: 0.06` — effectively zero
- `test_presence: 0.29`

These are low against a codebase that:
- Has a global exception filter (`apps/api/src/common/filters/http-exception.filter.ts`).
- Has a response interceptor that handles error envelopes.
- M1 spec explicitly says zero test files is correct at M1 (placeholder).

The probes penalize framework-level error handling because they look for per-function try/catch; and penalize empty test suites as "missing tests" even when the milestone spec requires empty test files.

## 2. Root cause

`verification.py` (or wherever truth probes live — investigate) computes:
- `error_handling`: likely counts `try/except` occurrences and divides by function count. Framework filters aren't counted.
- `test_presence`: likely counts test files with ≥1 test; M1's "placeholder" test suites show zero.

## 3. Proposed fix shape

### 3a. `error_handling` awareness of framework patterns

Update probe to credit:
- Presence of `@Catch(...)` decorator (NestJS exception filters).
- Global exception filter registration in `main.ts` (`app.useGlobalFilters(...)`).
- Error envelope in response interceptor.
- Top-level error boundary in Next.js (`error.tsx`).

Scoring formula: baseline score from per-function try/catch + bonus for framework-level patterns, capped at 1.0.

### 3b. `test_presence` milestone-awareness

Consult `MASTER_PLAN.json` for the current milestone's complexity estimate and test expectations:
- If milestone template is `full_stack` with `entity_count=0` (M1): "placeholder" test suites pass; score 1.0.
- Otherwise: require actual tests; score by coverage.

### 3c. `requirement_coverage` — already reasonable

0.70 reflects the build-j's milestone-1 having 8 requirements and 5-6 of them being passable static-analysis. Not a calibration bug. Leave alone unless A-09/C-01 land and coverage still looks off.

## 4. Test plan

File: `tests/test_truth_score_calibration.py`

1. **Framework filter scores well on error_handling.** Feed a NestJS codebase with global filter + response interceptor; assert `error_handling >= 0.7`.
2. **Plain codebase without error handling scores low.** Feed a codebase with zero try/catch and zero filters; assert `error_handling <= 0.3`.
3. **M1 with empty tests scores 1.0 on test_presence.** Feed milestone-1 context + empty suites; assert `test_presence == 1.0`.
4. **M3 with empty tests scores low.** Feed milestone-3 context (entity_count=1); assert `test_presence < 0.3`.

Target: 4 tests.

## 5. Rollback plan

Feature flag `config.v18.truth_score_v2: bool = True`. Flip off to restore old scoring.

## 6. Success criteria

- Unit tests pass.
- Gate A smoke: truth_score overall ≥ 0.80 on M1 clearance; `error_handling` dimension ≥ 0.70.

## 7. Sequencing notes

- Land in Session 8 alongside D-12 and D-14 (telemetry hygiene cluster).
- Independent of A-09 / C-01 but benefits from them (less scope-violation noise).
