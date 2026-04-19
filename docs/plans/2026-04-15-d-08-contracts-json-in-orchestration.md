# D-08 — CONTRACTS.json generated in recovery pass, not orchestration

**Tracker ID:** D-08 (maps to T1-06)
**Source:** B-008, §4.3 ("CONTRACTS.json not found after orchestration" → recovery pass)
**Session:** 4
**Size:** M (~80 LOC)
**Risk:** MEDIUM (orchestration ordering)
**Status:** plan

---

## 1. Problem statement

Orchestration completed without producing `CONTRACTS.json`. The gate check then fired "CONTRACTS.json not generated", and a "contract-generation recovery pass" had to be launched after-the-fact. Recovery succeeded, but the normal path shouldn't require recovery.

## 2. Root cause hypothesis

`contract_generator.py` is likely gated on a condition (Wave C output format or a missing Swagger artifact) that doesn't always hold at end-of-orchestration. Possible specific causes:
1. Contract generation is conditional on Swagger `/api/docs` being live (`runtime_verification.py` passing), and when runtime verification is skipped (as in build-j due to missing compose), contract gen is skipped.
2. Contract generation is conditional on Wave C success (OpenAPI extraction), and Wave C "skip" in some milestone paths means it never runs.
3. Contract generation is scheduled but silently swallowed by an exception.

Investigation: read `contract_generator.py` + `cli.py` orchestration phase + `BUILD_LOG.txt` for "contract" / "CONTRACTS" log markers.

## 3. Proposed fix shape

Two moves:

### 3a. Unconditional contract generation at end of orchestration

Make contract generation a deterministic step regardless of runtime verification status. If runtime is skipped, fall through to static-analysis contract generation (the path that DID succeed in recovery).

### 3b. Keep the recovery path as belt-and-suspenders

The recovery pass should still exist as a last-resort fallback, but the primary producer should be the orchestration step. Add a log marker at orchestration end: `"Contract generation: {primary | recovery-fallback}"` so operators can see which path ran.

### 3c. Surface failures loudly

If both primary and recovery fail, the gate check should hard-fail (not just warn), because downstream verification depends on it.

## 4. Test plan

File: `tests/test_contract_generation_orchestration.py`

1. **Contracts generated at orchestration end even with no runtime.** Mock state with runtime verification skipped; run orchestration; assert `CONTRACTS.json` exists at end.
2. **Primary path used when available.** Assert log marker says `primary`.
3. **Recovery fallback works if primary fails.** Mock primary path to raise; assert recovery fires and succeeds.
4. **Double failure hard-fails the pipeline.** Mock both paths to fail; assert gate check marks pipeline FAILED.

Target: 4 tests.

## 5. Rollback plan

Feature flag `config.v18.contracts_unconditional_generation: bool = True`. Flip off to restore conditional behavior.

## 6. Success criteria

- Unit tests pass.
- Gate A smoke: `CONTRACTS.json` exists after orchestration without needing recovery; log shows `Contract generation: primary`.

## 7. Sequencing notes

- Land in Session 4 alongside D-04, D-05, D-06, D-11.
- Couples loosely with D-09 (Contract Engine MCP). If D-09 lands first (Session 5), primary contract generation can use the real Contract Engine; if not, primary falls back to static analysis — still better than recovery-pass-only.
