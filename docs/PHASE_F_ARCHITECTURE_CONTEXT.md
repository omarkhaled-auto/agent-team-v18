# Phase F — Architecture Context for Reviewers

> Shared resource for Part 2 reviewers. Compiled from the end of Phase F
> sweeper work, immediately before the review fleet is dispatched.

## Branch state

* **Branch**: `phase-f-final-review`
* **HEAD at Phase F start**: `05fea20c40d5a4ecedd7d60bbd665162cba2be0f`
  (Phase E closeout: NEW-10 Claude bidirectional migration + Bug #20
  Codex app-server)
* **Baseline pytest**: 10,461 passed + 6 pre-existing failures
  (captured at `session-F-validation/baseline-pytest.log`).
* **Post-sweeper pytest**: **10,530 passed, 35 skipped, 0 failed**
  (captured at `session-F-validation/post-sweeper-pytest.log`).

## Phase A–F source tree changes vs `master`

Modified / added under `src/agent_team_v15/` (by net diff size, per
`git diff --stat master..HEAD` + Phase F working-tree additions):

| File | Origin | Net change summary |
| --- | --- | --- |
| `scaffold_runner.py` | Phase B (N-02/N-04/N-12) | Ownership contract + scaffold-config parameterisation |
| `wave_executor.py` | Phases A/B/C/D | Wave A-E orchestration, N-11/N-13 hooks, NEW-1 cleanup |
| `cli.py` | All phases | Orchestrator wiring, audit loop, recovery, N-11 cascade, now extended Wave D branch |
| `scaffold_verifier.py` | Phase B (N-13) | Scaffold report emission consumed by N-11 |
| `stack_contract.py` | Phase A | Stack contract model + validation |
| `codex_appserver.py` | Phase E (Bug #20) | Codex app-server migration |
| `milestone_scope.py` | Phase C (C-01) | Milestone scope model |
| `forbidden_content_scanner.py` | Phase C (N-10) | Forbidden-content scanner |
| `milestone_spec_reconciler.py` | Phase B | Per-milestone spec reconciliation |
| `endpoint_prober.py` | Phase A (N-01) | Port detection + docker-context normalisation |
| `import_resolvability_scan.py` | Phase D | Wave D import resolvability |
| `audit_scope.py` | Phase C (C-01) | Milestone-scoped audit prompts |
| `m1_startup_probe.py` | Phase D (D-20) | M1 startup AC probe |
| `mcp_servers.py` | Phase C (D-14) + Phase A | MCP wiring + fidelity label header |
| `audit_models.py` | Phase C | Finding fields (cascade_count, etc.) |
| `runtime_verification.py` | Phase A + Phase F | Runtime fix loop + Phase F budget softening |
| `scope_filter.py` | Phase A (A-09) | Wave prompt scope |
| `state.py` | Phase D (D-13) | State finalize consolidation |
| `agents.py` | All phases | Orchestrator system prompt |
| `provider_router.py` | Phase E (NEW-10) | Claude bidirectional migration |
| `codex_prompts.py` | Phase E | Codex prompt helpers |
| `config.py` | All phases | V18Config — central flag registry |
| `audit_team.py` | Phases A-D | Audit team deployment |

**Phase F NEW modules (~1,035 LOC across 4 files)**:

| File | LOC | Feature |
| --- | --- | --- |
| `src/agent_team_v15/infra_detector.py` | ~275 | §7.5 broader runtime detection |
| `src/agent_team_v15/confidence_banners.py` | ~250 | §7.10 confidence banners |
| `src/agent_team_v15/audit_scope_scanner.py` | ~230 | Auditor scope completeness |
| `src/agent_team_v15/wave_b_sanitizer.py` | ~280 | N-19 Wave B sanitization |

Each new module has a matching `tests/test_<name>.py`.

## Tests added / modified during Phase F

| File | Source | Notes |
| --- | --- | --- |
| `tests/test_infra_detector.py` | new (19 methods) | Touch 2 |
| `tests/test_confidence_banners.py` | new (17 methods) | Touch 3 |
| `tests/test_audit_scope_scanner.py` | new (12 methods) | Touch 4 |
| `tests/test_wave_b_sanitizer.py` | new (10 methods) | Touch 5 |
| `tests/test_cascade_suppression.py` | extended (+5 methods) | Touch 1 Wave D cascade |
| `tests/test_config_agent.py` | updated (2 methods) | Budget advisory |
| `tests/test_coordinated_builder.py` | updated (1 method) | Budget advisory |
| `tests/test_phase2_audit_fixes.py` | updated (5 methods) | Budget advisory |
| `tests/test_runtime_verification.py` | updated (2 methods) | Budget advisory |
| `tests/test_drawspace_critical_fixes.py` | updated (2 methods) | Review prompt introspection fix |
| `tests/test_e2e_12_fixes.py` | updated (1 method) | Review prompt introspection fix |
| `tests/test_v10_2_bugfixes.py` | updated (2 methods) | Recovery prompt assembled-check |
| `tests/test_v18_decoupling.py` | updated (1 method) | `_Ctx` stub gains `infra_missing` |

## Test count summary

| Metric | Value |
| --- | --- |
| Baseline passing | 10,461 |
| Baseline pre-existing failures | 6 |
| Post-Phase-F passing | **10,530** |
| Post-Phase-F failing | **0** |
| Post-Phase-F skipped | 35 (environmental — docker / network) |
| New tests added | +69 |
| Pre-existing failures resolved | 6 |

## V18Config feature-flag table (all phases, current defaults)

### Phase A

| Flag | Default |
| --- | --- |
| `scaffold_verifier_enabled` | True |
| `live_endpoint_check` | True |
| `evidence_mode` | `"soft_gate"` |
| `spec_reconciliation_enabled` | False |

### Phase B

| Flag | Default |
| --- | --- |
| `cascade_consolidation_enabled` | False |
| `duplicate_prisma_cleanup_enabled` | False |
| `template_version_stamping_enabled` | False |
| `audit_milestone_scoping` | True |

### Phase C

| Flag | Default |
| --- | --- |
| `content_scope_scanner_enabled` | False |
| `audit_fix_iteration_enabled` | False |
| `mcp_informed_dispatches_enabled` | **True** |
| `recovery_prompt_isolation` | True |

### Phase D

| Flag | Default |
| --- | --- |
| `orphan_tool_failfast_enabled` | True |
| `m1_startup_probe_enabled` | True |
| `truth_score_calibration_enabled` | True |

### Phase E

| Flag | Default |
| --- | --- |
| `codex_appserver_migration_enabled` | True |
| `claude_bidirectional_enabled` | True |

### Phase F (new, all default True)

| Flag | Default |
| --- | --- |
| `runtime_infra_detection_enabled` | **True** |
| `confidence_banners_enabled` | **True** |
| `audit_scope_completeness_enabled` | **True** |
| `wave_b_output_sanitization_enabled` | **True** |

## Phase A-E reports index

All reports in `docs/plans/`:

* `2026-04-16-phase-a-architecture-report.md`
* `2026-04-16-phase-a-report.md`
* `2026-04-16-phase-a-wiring-verification.md`
* `2026-04-16-phase-b-architecture-report.md`
* `2026-04-16-phase-b-report.md`
* `2026-04-16-phase-b-wiring-verification.md`
* `2026-04-16-phase-c-architecture-report.md`
* `2026-04-16-phase-c-report.md`
* `2026-04-16-phase-c-wiring-verification.md`
* `2026-04-16-phase-d-architecture-report.md`
* `2026-04-16-phase-d-report.md`
* `2026-04-16-phase-d-wiring-verification.md`
* `2026-04-16-phase-e-architecture-report.md`
* `2026-04-16-phase-e-report.md`
* `2026-04-16-phase-e-wiring-verification.md`
* `2026-04-16-phase-e-sdk-verification.md`

Upstream canonical references:

* `docs/plans/2026-04-16-deep-investigation-report.md` — the N / D /
  NEW item catalogue.
* `docs/plans/2026-04-16-handoff-post-gate-a-deep-investigation.md` —
  handoff context.

## Phase F deliverables at a glance

| Path | Purpose |
| --- | --- |
| `session-F-validation/SWEEPER_REPORT.md` | This sprint's Task 1A/1B/1C summary |
| `session-F-validation/BUDGET_REMOVAL_AUDIT.md` | CAP-vs-TELEMETRY audit table |
| `session-F-validation/post-sweeper-pytest.log` | Full pytest output, 10,530 passed |
| `docs/PHASE_F_ARCHITECTURE_CONTEXT.md` | This file |

_End of architecture context._
