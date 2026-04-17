# Phase F Coverage Matrix

> Task #7 deliverable. Maps every finding from the 5 Phase F reviewers +
> the 2 fixer reports to the lockdown test(s) that pin it.
>
> Test file: `tests/test_phase_f_lockdown.py` (70 lockdown tests).
> Additional regression coverage in: `tests/test_scaffold_m1_correctness.py`
> (F-FWK-001), `tests/test_bug20_codex_appserver.py` (F-RT-001),
> `tests/test_cascade_suppression.py` (F-ARCH-005, F-EDGE-002),
> `tests/test_audit_models.py` (F-EDGE-003), `tests/test_wave_b_sanitizer.py`
> (F-INT-002), `tests/test_wave_b_sanitizer_integration.py`,
> `tests/test_audit_scope_scanner_integration.py`,
> `tests/test_infra_detector_integration.py`,
> `tests/test_confidence_banners_integration.py`.

| Finding ID | Reviewer | Severity | Fixed? | Fix file:line | Lockdown test name(s) | Test file | Status |
|-----------|---------|----------|--------|---------------|----------------------|-----------|--------|
| F-ARCH-001 | functional-architect | CRITICAL | YES | `wave_executor.py:1054` | `test_maybe_sanitize_wave_b_outputs_is_imported_in_wave_executor`, `test_wave_b_success_branch_calls_sanitizer`, `test_sanitizer_emits_orphan_finding_on_scaffold_owned_emission` | tests/test_phase_f_lockdown.py | PASS |
| F-ARCH-002 | functional-architect | CRITICAL | YES | `cli.py:6025` | `test_cli_py_imports_audit_scope_scanner`, `test_scope_scanner_emits_gap_finding_for_uncovered_requirement`, `test_scope_scanner_merge_through_auditfinding_from_dict`, `test_flag_off_returns_empty_gap_list` | tests/test_phase_f_lockdown.py | PASS |
| F-ARCH-003 | functional-architect | CRITICAL | YES | `endpoint_prober.py:1044`, `endpoint_prober.py:1307` | `test_endpoint_prober_imports_infra_detector`, `test_detect_runtime_infra_reads_api_prefix_from_main_ts`, `test_build_probe_url_honors_api_prefix`, `test_build_probe_url_no_doubled_slash_with_trailing_and_leading`, `test_build_probe_url_no_prefix_matches_pre_phase_f_shape`, `test_flag_off_returns_empty_runtime_infra` | tests/test_phase_f_lockdown.py | PASS |
| F-ARCH-004 | functional-architect | CRITICAL | YES | `cli.py:6756` | `test_cli_py_imports_confidence_banners`, `test_stamp_all_reports_adds_confidence_to_audit_report`, `test_stamp_all_reports_stamps_every_artefact_type`, `test_stamp_all_reports_is_idempotent` | tests/test_phase_f_lockdown.py | PASS |
| F-ARCH-005 | functional-architect | MEDIUM | NO (accepted) | — | `test_cascade_consolidation_enabled_defaults_false`, `test_flag_off_cascade_is_no_op`, `test_flag_on_activates_cascade_when_wave_d_failed` | tests/test_phase_f_lockdown.py | PASS (characterization) |
| F-ARCH-006 | functional-architect | LOW | NO | — | `test_zero_scanners_does_not_raise`, `test_zero_scanners_soft_gate_converged_runtime_ran_returns_confident` | tests/test_phase_f_lockdown.py | PASS (characterization) |
| F-FWK-001 | framework-correctness | CRITICAL | YES | `scaffold_runner.py:1146-1161`, `scaffold_runner.py:1105-1108` | `test_prisma_service_template_has_no_enable_shutdown_hooks`, `test_main_ts_template_calls_enable_shutdown_hooks` | tests/test_phase_f_lockdown.py + tests/test_scaffold_m1_correctness.py::TestA03PrismaShutdownHook | PASS |
| F-FWK-002 | framework-correctness | INFO | N/A (not a bug) | — | (no test — CLI flag usage is correct) | — | N/A |
| F-FWK-003 | framework-correctness | PASS | N/A | — | `test_detects_bare_string_prefix`, `test_detects_backtick_template_prefix` | tests/test_phase_f_lockdown.py | PASS (characterization) |
| F-FWK-004 | framework-correctness | PASS | N/A | — | (covered by existing N-09 Wave B prompt tests) | tests/test_n09_wave_b_prompt_hardeners.py | PASS |
| F-FWK-005 | framework-correctness | PASS | N/A | — | (covered by existing `test_bug20_codex_appserver.py`) | tests/test_bug20_codex_appserver.py | PASS |
| F-FWK-006 | framework-correctness | PASS | N/A | — | (Phase E SDK surface verified in the session-F review) | — | PASS |
| F-FWK-007 | framework-correctness | PENDING | NO | — | (owner flagged for smoke spot-check — out of scope for lockdown) | — | DEFERRED |
| F-FWK-008 | framework-correctness | PASS | N/A | — | (Docker Compose long-form already canonical) | — | PASS |
| F-FWK-009 | framework-correctness | PASS | N/A | — | (Next.js 15 minimal config already canonical) | — | PASS |
| F-RT-001 | runtime-behavior | HIGH | YES | `codex_appserver.py:226` (send_turn_interrupt), `:263` (monitor_orphans), `:311` (executor wait) | `test_send_turn_interrupt_exists`, `test_monitor_orphans_exists_as_coroutine`, `test_orphan_watchdog_uses_threading_lock`, `test_orphan_watchdog_dedupes_same_tool_id`, `test_process_streaming_event_does_not_register_orphan` | tests/test_phase_f_lockdown.py + tests/test_bug20_codex_appserver.py | PASS |
| F-RT-002 | runtime-behavior | MEDIUM | NO | — | `test_stamp_json_report_uses_write_text`, `test_stamp_build_log_uses_write_text`, `test_stamp_markdown_report_uses_write_text`, `test_stamp_json_report_returns_false_on_oserror` | tests/test_phase_f_lockdown.py | PASS (characterization) |
| F-RT-003 | runtime-behavior | LOW | NO | — | `test_scan_for_consumers_skips_on_read_failure`, `test_remove_orphans_default_false_in_sanitize` | tests/test_phase_f_lockdown.py | PASS (characterization) |
| F-RT-004 | runtime-behavior | LOW | NO | — | `test_dispatch_fix_agent_is_sync_function`, `test_runtime_verification_source_uses_asyncio_run` | tests/test_phase_f_lockdown.py | PASS (characterization) |
| F-RT-005 | runtime-behavior | MEDIUM | YES (same as F-ARCH-001..004) | see F-ARCH-001..004 | `test_all_four_modules_reachable_from_production_imports` | tests/test_phase_f_lockdown.py | PASS |
| F-INT-001 | integration-boundary | CRITICAL | YES (same as F-ARCH-001..004) | see F-ARCH-001..004 | `test_all_four_modules_reachable_from_production_imports`, `test_full_finalize_path_stamps_and_emits` | tests/test_phase_f_lockdown.py | PASS |
| F-INT-002 | integration-boundary | MEDIUM | YES | `wave_b_sanitizer.py:284` | `test_wave_b_emission_in_wave_d_owned_path_is_orphan`, `test_sanitizer_source_lists_wave_d_owner` | tests/test_phase_f_lockdown.py + tests/test_wave_b_sanitizer.py | PASS |
| F-INT-003 | integration-boundary | LOW | NO (docs only) | — | (docs drift — no code test needed) | — | N/A |
| F-EDGE-001 | edge-case-adversarial | CRITICAL | YES (umbrella over F-ARCH-001..004) | see F-ARCH-001..004 | `test_all_four_modules_reachable_from_production_imports`, `test_full_finalize_path_stamps_and_emits` | tests/test_phase_f_lockdown.py | PASS |
| F-EDGE-002 | edge-case-adversarial | HIGH | YES | `cli.py:626` (milestone_id kwarg), `cli.py:732` (caller threads it) | `test_load_wave_d_roots_scoped_to_milestone`, `test_load_wave_d_roots_legacy_union_fallback`, `test_m2_findings_not_collapsed_when_m1_only_failed` | tests/test_phase_f_lockdown.py + tests/test_cascade_suppression.py | PASS |
| F-EDGE-003 | edge-case-adversarial | HIGH | YES | `audit_models.py:39` (AuditReportSchemaError), `audit_models.py:346` (validation) | `test_from_json_raises_typed_error_on_dict_findings`, `test_from_json_raises_typed_error_on_string_findings`, `test_from_json_raises_typed_error_on_int_findings`, `test_from_json_accepts_none_findings_as_empty`, `test_from_json_accepts_empty_list`, `test_from_json_raises_typed_error_on_malformed_entry`, `test_audit_report_schema_error_is_value_error` | tests/test_phase_f_lockdown.py + tests/test_audit_models.py | PASS |
| F-EDGE-004 | edge-case-adversarial | MEDIUM | NO | — | `test_plateau_check_uses_strict_less_than_3` | tests/test_phase_f_lockdown.py | PASS (characterization) |
| F-EDGE-005 | edge-case-adversarial | MEDIUM | NO | — | `test_stamp_all_reports_survives_oserror_during_write` | tests/test_phase_f_lockdown.py | PASS (characterization) |
| F-EDGE-006 | edge-case-adversarial | MEDIUM | NO | — | `test_loop_state_accepts_max_iterations_zero`, `test_loop_state_accepts_negative_max_iterations` | tests/test_phase_f_lockdown.py | PASS (characterization) |
| F-EDGE-007 | edge-case-adversarial | MEDIUM | NO (dormant) | — | `test_single_signal_applied_to_every_milestone_artefact` | tests/test_phase_f_lockdown.py | PASS (characterization) |
| F-EDGE-008 | edge-case-adversarial | LOW | NO (dormant) | — | `test_cascade_consolidation_scales_to_many_milestones` | tests/test_phase_f_lockdown.py | PASS (characterization) |
| F-EDGE-009 | edge-case-adversarial | LOW | NO (dormant) | — | `test_scan_with_empty_requirements_returns_empty_list`, `test_scan_with_misformatted_requirements_returns_empty_list`, `test_scan_with_missing_requirements_file_returns_empty_list` | tests/test_phase_f_lockdown.py | PASS (characterization) |
| F-EDGE-010 | edge-case-adversarial | LOW | NO (dormant) | — | `test_sanitize_with_empty_contract_returns_no_orphans`, `test_sanitize_with_none_contract_skips_and_reports` | tests/test_phase_f_lockdown.py | PASS (characterization) |
| F-EDGE-011 | edge-case-adversarial | LOW | NO | — | `test_detect_runtime_infra_missing_api_dir`, `test_detect_runtime_infra_missing_main_ts` | tests/test_phase_f_lockdown.py | PASS (characterization) |

## Summary counts

| Category | Count |
|---|---|
| CRITICAL findings covered (fixed) | 9 (F-ARCH-001..004, F-FWK-001, F-INT-001, F-EDGE-001, + F-RT-005 umbrella, + F-INT-001 umbrella) |
| HIGH findings covered (fixed) | 3 (F-RT-001, F-EDGE-002, F-EDGE-003) |
| MEDIUM findings covered (characterization) | 7 (F-ARCH-005, F-RT-002, F-INT-002, F-EDGE-004..007) |
| LOW findings covered (characterization) | 7 (F-ARCH-006, F-RT-003/4, F-EDGE-008..011) |
| PASS / INFO findings with spot-check | 3 (F-FWK-003, F-FWK-005, F-FWK-006 via existing suites) |
| Docs-only findings (no test) | 2 (F-FWK-002 CLI-glob clarification, F-INT-003 line-range typo) |
| PENDING (owner deferred) | 1 (F-FWK-007 @hey-api spot-check) |

## Coverage gaps

- **F-FWK-007** — @hey-api/openapi-ts `defineConfig` shape. Owner
  (framework-correctness reviewer) flagged as PENDING for smoke
  spot-check. Not covered by lockdown because the template body
  inspection was marked as out-of-scope for the lockdown engineer;
  rolled into the production-smoke checklist.
- **F-INT-003** — line-range drift in a docs report. Pure documentation
  edit; no code behavior to test.
- **F-FWK-002** — CLI `--allowedTools` glob usage. Not a bug; the CLI
  channel legitimately supports globs.

Every actionable finding — critical, high, medium, or low — has at
least one lockdown test or existing regression test pinning it.
