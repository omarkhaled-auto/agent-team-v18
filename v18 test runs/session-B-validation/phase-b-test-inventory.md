# Phase B Test Inventory

**Author:** phase-b-test-engineer (Wave 3)
**Date:** 2026-04-16
**Branch:** `phase-b-scaffold-spec`
**Scope:** Tests added or modified in Phase B Wave 2 + pending Wave 3 (n11 parallel).

This is an inventory artifact. It maps each Phase B scope item to the test(s) that
cover it, counts them, and flags name-mismatches against the expected class names in
the session brief.

---

## Targeted-suite pass results

| Suite | Collected | Passed | Failed | Skipped |
|---|---:|---:|---:|---:|
| `tests/test_ownership_contract.py` | 16 | 16 | 0 | 0 |
| `tests/test_ownership_consumer_wiring.py` | 9 | 9 | 0 | 0 |
| `tests/test_scaffold_runner.py` | 14 | 14 | 0 | 0 |
| `tests/test_scaffold_m1_correctness.py` | 39 | 39 | 0 | 0 |
| `tests/test_spec_reconciler_and_verifier.py` | 12 | 12 | 0 | 0 |
| `tests/test_config.py` | 362 | 362 | 0 | 0 |
| `tests/test_agents.py` | 265 | 265 | 0 | 0 |
| `tests/test_audit_team.py` | 45 | 45 | 0 | 0 |
| **Total (Phase B & adjacent)** | **762** | **762** | **0** | **0** |

No new failures introduced. The 6 pre-existing baseline failures documented at
`v18 test runs/session-B-validation/preexisting-failures.txt` were not touched by any
Wave 2 change (those files were not included in the targeted suites above).

---

## Phase B item coverage map

| Item | Test file | Test class | Count | Notes |
|---|---|---|---:|---|
| N-02 parser | `tests/test_ownership_contract.py` | `TestOwnershipParser` | 10 | Covers 60-row invariant, owner-totals, optional flag, error paths |
| N-02 parser dataclass sanity | `tests/test_ownership_contract.py` | `TestFileOwnershipDataclass` | 2 | Hashable + immutable contract |
| N-02 consumer 3 (scaffold validation) | `tests/test_ownership_contract.py` | `TestScaffoldOwnershipValidation` | 4 | Flag-OFF no-op + flag-ON drift warnings |
| N-02 consumer 1 (wave prompts) | `tests/test_ownership_consumer_wiring.py` | `TestWavePromptInjection` | 5 | Flag-gated; asserts 12 wave-b paths, 1 wave-d path |
| N-02 consumer 2 (auditor suppression) | `tests/test_ownership_consumer_wiring.py` | `TestAuditorOptionalSuppression` | 4 | Flag-gated; 3 optional paths listed |
| N-03 packages/shared emission | `tests/test_scaffold_runner.py` | `TestScaffoldPackagesShared` | 8 | Name differs from brief (`TestN03PackagesSharedCorrectness` expected); covers all 6 files + verbatim enum/error-code/pagination content + idempotency |
| N-04 Prisma path migration | `tests/test_scaffold_m1_correctness.py` | `TestN04N05PrismaPathAndMigrations::test_prisma_module_and_service_emitted_at_src_database` | 1 | Asserts `src/database/` and absence of legacy `src/prisma/` |
| N-05 schema.prisma + migration stub | `tests/test_scaffold_m1_correctness.py` | `TestN04N05PrismaPathAndMigrations::test_schema_prisma_bootstrap_emitted`, `test_initial_migration_stub_emitted`, `test_migration_lock_toml_canonical_format` | 3 | Bootstrap, migration SQL, lock.toml |
| N-06 web scaffold + vitest setupFiles | `tests/test_scaffold_m1_correctness.py` | `TestN06WebScaffoldCompleteness` | 10 | next.config, tsconfig, postcss, openapi-ts, .env.example port=4000, Dockerfile, layout/page/middleware stubs, `test_aud_022_vitest_setup_wired`, hey-api deps |
| N-07 docker-compose full topology | `tests/test_scaffold_m1_correctness.py` | `TestN07DockerComposeFullTopology` | 5 | 3-service presence, no `version:` key, api healthcheck+port=4000, service_healthy wiring for api and web |
| N-11 cascade suppression | `tests/test_cascade_suppression.py` | — | 0 | **PENDING** (n11-new1-new2-impl Wave 3 parallel). Expected ~5 tests |
| N-12 SPEC reconciliation | `tests/test_spec_reconciler_and_verifier.py` | `TestReconciler` + `TestScaffoldConfig` + `TestReconcilerIntegration` | 8 | no-conflict path, explicit PRD-vs-REQUIREMENTS conflict, absent PRD, all-silent fallback, `ScaffoldConfig` frozen/defaults/compose, real-contract integration |
| N-13 scaffold verifier | `tests/test_spec_reconciler_and_verifier.py` | `TestScaffoldVerifier` | 4 | PASS on minimal, FAIL on missing file, FAIL on port drift, WARN on deprecated-path regression |
| NEW-1 duplicate prisma cleanup | `tests/test_duplicate_prisma_cleanup.py` | — | 0 | **PENDING** (n11 Wave 3). Expected ~4 tests |
| NEW-2 template version stamping | `tests/test_template_freshness.py` | — | 0 | **PENDING** (n11 Wave 3). Expected ~3 tests |
| A-01/A-02/A-03/A-04/A-07/A-08/D-18 (pre-Phase-B scope retained) | `tests/test_scaffold_m1_correctness.py` | `TestA01DockerCompose`, `TestA02PortDefault4000`, `TestA03PrismaShutdownHook`, `TestA04I18nLocales`, `TestA07VitestScaffold`, `TestA08GitignoreAndEnv`, `TestD18NonVulnerablePins` | 17 | Pre-existing; verified still passing alongside Phase B tests |
| Scaffold helpers + run idempotency (pre-existing) | `tests/test_scaffold_runner.py` | `TestScaffoldHelpers`, `TestRunScaffolding` | 6 | Pre-existing; verified still passing |

### Totals

- **Phase B NEW tests (Wave 2):** 64
  - `test_ownership_contract.py` (16 new) + `test_ownership_consumer_wiring.py` (9 new) + `test_spec_reconciler_and_verifier.py` (12 new) + `TestScaffoldPackagesShared` (8 new) + `TestN04N05PrismaPathAndMigrations` (4 new) + `TestN06WebScaffoldCompleteness` (10 new) + `TestN07DockerComposeFullTopology` (5 new)
- **Phase B PENDING tests (Wave 3 parallel):** ~12 (5 + 4 + 3)
- **Projected Phase B total at Wave 3 exit:** ~76

---

## Near-duplicate / overlap notes

| Test | Overlaps with | Disposition |
|---|---|---|
| `TestScaffoldPackagesShared::test_enums_match_requirements_verbatim` | None | Unique |
| `TestN06WebScaffoldCompleteness::test_env_example_canonical_port_4000` | `TestA02PortDefault4000::test_env_example_pins_port_to_4000` | Low overlap — former asserts `apps/web/.env.example`, latter asserts root `.env.example`. Both kept. |
| `TestA01DockerCompose::test_docker_compose_yaml_emitted` | `TestN07DockerComposeFullTopology::test_compose_has_three_services` | Former asserts presence + postgres shape; latter asserts 3-service topology. Both kept — different invariants. |
| `TestScaffoldConfig::test_defaults_match_canonical_m1_values` | `TestReconcilerIntegration::test_default_scaffold_config_port_matches_requirements_sample` | Latter is a secondary sanity via reconciler path. Kept — different seams. |
| `TestScaffoldOwnershipValidation::test_warns_on_unexpected_wave_owned_path_emitted` | `TestWavePromptInjection` | No overlap — validation is scaffold-side; prompt injection is wave-side. |

No redaction recommended. Test diversity is load-bearing under the feature-flag-gated design.

---

## Weak-assertion audit

Scanned files: `test_ownership_contract.py`, `test_ownership_consumer_wiring.py`, `test_spec_reconciler_and_verifier.py`, `test_scaffold_m1_correctness.py`, `test_scaffold_runner.py`.

Flagged single-token `assert X` lines (5 total), individually inspected:

| Test | Line | Verdict |
|---|---|---|
| `TestScaffoldOwnershipValidation::test_warns_on_missing_scaffold_paths_when_flag_on` | `assert any(...)` | Strong — asserts specific log text (`"N-02 ownership drift"` + `"not emitted"`) |
| `TestScaffoldOwnershipValidation::test_warns_on_unexpected_wave_owned_path_emitted` | `assert any(...)` | Strong — asserts log text + specific path + owner name |
| `TestReconciler::test_explicit_conflict_between_requirements_and_prd` | `assert result.has_conflicts` | Strong (compound) — paired with sibling asserts on `conflicts[].section`, `port`, `recovery_type`, and on-disk artifact |
| `TestScaffoldVerifier::test_fail_on_missing_required_file` | `assert any(...)` | Strong — asserts a missing-file path match |
| `TestScaffoldVerifier::test_warn_on_deprecated_path_emitted` | `assert report.deprecated_emitted` | Strong (compound) — paired with sibling `verdict == "WARN"` |

**Zero weak assertions detected** across Wave 2 tests. The four matches for `toBeDefined`/`toBeTruthy` in the repo (`test_build_verification.py`, `test_enforcement_hardening.py`, `test_e2e_phase.py`) are string literals defining TypeScript *fixtures*, not Python test assertions.

---

## Coverage gap summary

**Covered at Wave 3 start:** N-02 (parser + 3 consumers), N-03, N-04, N-05, N-06, N-07, N-12, N-13.

**Not yet covered — owned by parallel n11-new1-new2-impl agent:**

1. N-11 cascade suppression — `tests/test_cascade_suppression.py`
2. NEW-1 duplicate prisma cleanup — `tests/test_duplicate_prisma_cleanup.py`
3. NEW-2 template version stamping — `tests/test_template_freshness.py`

**Net new test additions from this (test-engineer) agent: 0.** All expected gaps are owned by the parallel Wave 3 implementation agent. Per the scope budget ("Don't add tests for things already covered"), no filler tests are warranted.

---

## Name-mismatch against session brief

The brief expected `TestN03PackagesSharedCorrectness` in `tests/test_scaffold_runner.py`; the implementing agent n03 named the class `TestScaffoldPackagesShared`. The tests cover the same N-03 scope. Disposition for team-lead: rename-on-merge is cosmetic and optional; the descriptive docstring (`"""N-03: packages/shared/* baseline must match M1 REQUIREMENTS verbatim."""`) already ties it to the scope item.

---

## Baseline integrity

The 6 pre-existing failures enumerated in `preexisting-failures.txt` remain unlisted in the targeted suites above (they live in `test_drawspace_critical_fixes`, `test_e2e_12_fixes`, `test_v10_2_bugfixes`, `test_v18_decoupling`). Wave 4 must re-verify they still fail by *exactly* the same test names; any drift is a Phase B regression.
