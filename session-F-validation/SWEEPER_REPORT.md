# Phase F — Sweeper Implementer Report

> Task #1 deliverable. Covers Task 1A (budget removal), 6 implementation
> touches, and Task 1C (closure verification + deliverables).

## 1. Budget removal (Task 1A)

See `BUDGET_REMOVAL_AUDIT.md` for the full CAP-vs-TELEMETRY table. In
summary:

* 12 CAP points removed or softened across `cli.py`,
  `coordinated_builder.py`, `config_agent.py`, `runtime_verification.py`,
  and `agents.py`.
* 10 TELEMETRY sites retained (max_budget_usd field, budget_exceeded
  telemetry flag, RuntimeReport formatters, prompt placeholder).
* 8 tests updated to assert advisory behavior; 0 tests deleted.
* The orchestrator system prompt (`agents.py:809-810`) was reworded so
  it never tells the model to shrink fleets when `max_budget_usd` is
  set; the app must ship correctly first, always.

## 2. Six implementation touches

### Touch 1 — N-11 Wave D cascade extension

**File:line changes**

* `src/agent_team_v15/cli.py`:
  * Added `_load_wave_d_failure_roots(cwd)` at `cli.py:540` (reads
    `.agent-team/STATE.json` via `state.load_state`; returns
    `["apps/web", "packages/api-client"]` when any milestone's
    `wave_progress` entry has `failed_wave == "D"`; otherwise `[]`).
  * `_consolidate_cascade_findings` now accepts both scaffold roots
    and Wave D roots. The roots list is the union
    `scaffold_roots + wave_d_roots`.
  * Cascade notes on representative findings now distinguish "scaffold
    root cause" vs "Wave D root cause".
  * The `F-CASCADE-META` summary + remediation branches on which
    cascade(s) contributed — "upstream scaffold", "upstream Wave D",
    or "upstream scaffold + Wave D" — so operators see where to look
    first.

**Tests added** — `tests/test_cascade_suppression.py::TestCascadeSuppressionWaveDFailure`
(5 new test methods):

  * `test_flag_on_no_state_no_cascade`
  * `test_flag_on_state_but_wave_d_not_failed`
  * `test_wave_d_failure_collapses_web_app_findings`
  * `test_wave_d_failure_collapses_api_client_findings`
  * `test_wave_d_cascade_note_labels_root_kind`

### Touch 2 — §7.5 broader runtime infrastructure detection

**New module** — `src/agent_team_v15/infra_detector.py` (~275 LOC).

Exports:

* `RuntimeInfra` dataclass — `app_url`, `api_prefix`, `cors_origin`,
  `database_url`, `jwt_audience`, `sources`.
* `detect_runtime_infra(project_root, *, config)` — reads
  `apps/api/src/main.ts` (for `setGlobalPrefix`), `.env` / `apps/api/.env`
  / `apps/api/.env.example` (for `CORS_ORIGIN`, `DATABASE_URL`), and
  scans `apps/api/src/**/*.ts` for a JWT audience registration. Flag
  `v18.runtime_infra_detection_enabled` gates it (default True).
* `build_probe_url(app_url, route, *, infra)` — composes a probe URL
  that honors the detected `api_prefix`, no doubled slashes.

Phase A's PORT detection in `endpoint_prober._detect_app_url` is
unchanged; this module is strictly additive.

**Tests added** — `tests/test_infra_detector.py` (19 test methods)
cover every detection path, flag-off short-circuit, and
`build_probe_url` path assembly.

### Touch 3 — §7.10 confidence banners on ALL reports

**New module** — `src/agent_team_v15/confidence_banners.py` (~250 LOC).

Extends Phase C's D-14 fidelity labels (only on 4 verification
artefacts) to every user-facing report:

  * `AUDIT_REPORT.json` — adds `confidence` + `confidence_reasoning`
    keys via `stamp_json_report`.
  * `BUILD_LOG.txt` — prepends `[CONFIDENCE=LABEL] reasoning` header via
    `stamp_build_log`.
  * `GATE_*_REPORT.md` and `*_RECOVERY_REPORT.md` — prepends
    `## Confidence: LABEL` block via `stamp_markdown_report`.

Derivation (`derive_confidence`) is deterministic from
`ConfidenceSignals(evidence_mode, scanners_run, scanners_total,
fix_loop_converged, fix_loop_plateaued, runtime_verification_ran)` —
never tells an operator "CONFIDENT" when evidence is missing.

All three stamp helpers are idempotent. `stamp_all_reports` walks the
`.agent-team/` tree and returns `{path: modified}` for observability.
Flag `v18.confidence_banners_enabled` gates all emissions (default True).

**Tests added** — `tests/test_confidence_banners.py` (17 test methods)
cover derivation rules (CONFIDENT / MEDIUM / LOW), stamping each of
the four artefact types, idempotence, and flag-off short-circuit.

### Touch 4 — Auditor scope completeness scanner

**New module** — `src/agent_team_v15/audit_scope_scanner.py` (~230 LOC).

Reads a milestone's `REQUIREMENTS.md`, checks each requirement against
known coverage surfaces (i18n/RTL via N-10, UI_DESIGN_TOKENS.json
presence, scaffold/stack-contract via scaffold_verifier_report.json,
file-path evidence via regex match on `apps/|packages/|src/|docs/`
paths), and emits `ScopeGap` records for uncovered items. Serialised
via `build_scope_gap_findings` into `AUDIT-SCOPE-GAP-<REQ_ID>`
INFO-severity meta-findings (never fail the audit alone).

Flag `v18.audit_scope_completeness_enabled` gates it (default True).

**Tests added** — `tests/test_audit_scope_scanner.py` (12 test methods)
cover coverage-by-file-path, i18n with / without N-10, design tokens
with / without file, stack contract with / without scaffold verifier,
no-keyword/no-path gap, mixed coverage, flag-off, and serialisation
shape.

### Touch 5 — N-19 Wave B output sanitization

**New module** — `src/agent_team_v15/wave_b_sanitizer.py` (~280 LOC).

Post-Wave-B hook: compares emitted files against the ownership
contract (`docs/SCAFFOLD_OWNERSHIP.md`). Any Wave B emission in a
scaffold-owned path is flagged as an orphan candidate. Before any
cleanup, `_scan_for_consumers` does a deterministic ripgrep-like scan
(module-specifier variants across `.ts`/`.tsx`/`.js` files) and
records up to 3 consumer samples. `remove_orphans=True` is opt-in and
only removes orphans with NO detected consumers. Every action logged.

Returns a `SanitizationReport` with `OrphanFinding`s; serialised via
`build_orphan_findings` into audit findings (MEDIUM/PARTIAL when
unremoved without consumers; INFO/PARTIAL with consumers; INFO/PASS
when removed).

Flag `v18.wave_b_output_sanitization_enabled` gates it (default True).

**Tests added** — `tests/test_wave_b_sanitizer.py` (10 test methods)
cover legitimate paths not flagged, orphan detection, consumer-aware
removal safety, remove_orphans flow, and finding-dict serialisation.

### Touch 6 — Fix 6 pre-existing pytest failures

Root-cause analysis and disposition, with rationale:

| # | Test | Disposition | Why |
| --- | --- | --- | --- |
| 1 | `test_drawspace_critical_fixes.py::test_cli_source_has_phase_tag` | **Updated** — introspect `_build_recovery_prompt_parts` instead of `_run_review_only` | D-05 refactored the review-only prompt into a helper; the `[PHASE: REVIEW VERIFICATION]` tag survives in the legacy rollback branch of the helper. Test now points at the actual location; semantic intent preserved. |
| 2 | `test_drawspace_critical_fixes.py::test_cli_source_has_system_tag` | **Updated** — same refactor | Same reasoning. |
| 3 | `test_e2e_12_fixes.py::test_review_only_prompt_has_increment` | **Updated** — introspect `_build_recovery_prompt_parts` | `"review_cycles: N) to (review_cycles: N+1)"` lives in the helper's `user_task` string now. |
| 4 | `test_v10_2_bugfixes.py::test_gate5_message_mentions_zero_review_cycles` | **Updated** — call the helper and check the assembled prompt | The phrase `"without running the review fleet"` spans a Python string-literal line break in the source text, so `"…" in CLI_SOURCE` never matched. Now the test builds the actual prompt via `_build_recovery_prompt_parts(...)` and asserts on the assembled string. |
| 5 | `test_v10_2_bugfixes.py::test_gate5_message_includes_checked_count` | **Updated** — same technique | Same line-break issue with `"none verified by reviewers"`. |
| 6 | `test_v18_decoupling.py::test_probes_skip_gracefully_without_docker` | **Updated** — stub gains `infra_missing = True` | D-02 added a structural `infra_missing` flag to `DockerContext` so wave_executor can distinguish "no infra" (skip) from "infra up but failed" (block). The test's `_Ctx` stub was missing the attribute, causing `AttributeError`. Adding `infra_missing = True` (which matches the test's name — "without_docker" = legitimately infra-missing) makes the test assert the correct skip path. |

No test was deleted. No test was `skipif`'d. No code was regressed —
every disposition updates the test to accurately assert the post-D-02 /
D-05 behavior, not to silence a real failure.

## 3. Closure verification (Task 1C)

Spot-checked Phase A-E claims against current tree:

* **N-01** port detection: `src/agent_team_v15/endpoint_prober.py:1023-1055`
  (`_detect_app_url` walks config → `.env` → `apps/api/.env.example` →
  main.ts → compose.yml). Verified present.
* **N-02** SCAFFOLD_OWNERSHIP.md: `docs/SCAFFOLD_OWNERSHIP.md` exists,
  60 files indexed, parsed by `scaffold_runner.load_ownership_contract`
  at `src/agent_team_v15/scaffold_runner.py:174`. Verified present.
* **N-10** forbidden-content scanner:
  `src/agent_team_v15/forbidden_content_scanner.py` and config flag
  `v18.content_scope_scanner_enabled` at `config.py:894`. Verified
  wired in `cli.py:5886-5905`.
* **N-11** cascade consolidation:
  `src/agent_team_v15/cli.py:587-729`, flag
  `v18.cascade_consolidation_enabled` at `config.py:872`. Verified —
  and now extended with Wave D branch.
* **N-17** MCP-informed dispatches: flag
  `v18.mcp_informed_dispatches_enabled=True` at `config.py:910`;
  consumer in wave B/D prompt assembly. Verified present.
* **NEW-1** duplicate-Prisma cleanup:
  `src/agent_team_v15/wave_executor.py:974-1030`
  (`_maybe_cleanup_duplicate_prisma`). Verified.
* **D-02** `infra_missing` structural flag on DockerContext: verified
  via the pre-existing failure fix (test_v18_decoupling.py stub now
  includes it).
* **D-05** recovery prompt role isolation: verified via
  `_build_recovery_prompt_parts` at `cli.py:9225-9316`; two branches
  (isolation on and legacy rollback) both present.
* **D-14** fidelity label header: verified at
  `src/agent_team_v15/mcp_servers.py:534-561` (referenced by
  `verification.py:1232-1240`). Confidence banners are the Phase F
  generalisation.

No mismatches found; no HALT triggered. All Phase A-E ✅ Closed items
point at real code in the current tree.

## 4. Final test count

* **Baseline** (session-F-validation/baseline-pytest.log): 10,461 passed
  + 6 pre-existing failures.
* **Post-Phase-F** (session-F-validation/post-sweeper-pytest.log):
  **10,530 passed, 35 skipped, 0 failed, 0 errors** — 849.95 s total
  runtime.

Delta: **+69 passing tests, 6 pre-existing failures resolved, 0 regressions.**

## 5. New source modules (Phase F)

| Module | Purpose |
| --- | --- |
| `src/agent_team_v15/infra_detector.py` | §7.5 broader runtime infra detection |
| `src/agent_team_v15/confidence_banners.py` | §7.10 confidence banners on all reports |
| `src/agent_team_v15/audit_scope_scanner.py` | Auditor scope completeness scanner |
| `src/agent_team_v15/wave_b_sanitizer.py` | N-19 Wave B output sanitization |

## 6. New feature flags (Phase F, all default True)

* `v18.runtime_infra_detection_enabled`
* `v18.confidence_banners_enabled`
* `v18.audit_scope_completeness_enabled`
* `v18.wave_b_output_sanitization_enabled`

Defined at `src/agent_team_v15/config.py:911-950`.

## 7. Deliverables

* `session-F-validation/SWEEPER_REPORT.md` — this file
* `session-F-validation/BUDGET_REMOVAL_AUDIT.md` — Task 1A detail
* `docs/PHASE_F_ARCHITECTURE_CONTEXT.md` — reviewer context
* `session-F-validation/post-sweeper-pytest.log` — full pytest output

_End of report._
