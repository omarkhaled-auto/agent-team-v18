# Phase H1a — Discovery Citations Receipt

> Branch: `phase-h1a-compose-ownership-enforcement` @ `b77fca0`
> Companion: `docs/plans/phase-h1a-architecture-report.md`
>
> Flat list of every file:line citation the architecture report relies on. Each entry has a 1-line note. Wave 2 / Wave 3 agents should grep this receipt before editing to confirm the citation is still valid at their HEAD.

---

## Section 1A — Wave B prompt structure

- `src/agent_team_v15/agents.py:8364-8376` — `build_wave_b_prompt` signature.
- `src/agent_team_v15/agents.py:8416-8432` — `parts` accumulator init, `[WAVE B - BACKEND SPECIALIST]` + `[EXECUTION DIRECTIVES]` block.
- `src/agent_team_v15/agents.py:8434-8441` — optional `[CURRENT FRAMEWORK IDIOMS]` (mcp_doc_context) block.
- `src/agent_team_v15/agents.py:8444-8493` — `[CANONICAL NESTJS 11 / PRISMA 5 PATTERNS]` AUD-009..023 hardeners.
- `src/agent_team_v15/agents.py:8495-8499` — `[YOUR TASK]` header.
- `src/agent_team_v15/agents.py:8501-8513` — `[CODEBASE CONTEXT]`.
- `src/agent_team_v15/agents.py:8514-8518` — `[MILESTONE REQUIREMENTS]` + `[MILESTONE TASKS]`.
- `src/agent_team_v15/agents.py:8538-8552` — optional `[INTEGRATION CONTEXT]` + `[ADAPTER PORTS]`.
- `src/agent_team_v15/agents.py:8554-8597` — `[DESIGN SYSTEM]` / `[IMPLEMENTATION PATTERNS]` / `[FILE ORGANIZATION]` / `[MODULE REGISTRATION]` / `[BARREL EXPORTS]` / `[TESTING REQUIREMENTS]`; **insertion point for `[INFRASTRUCTURE WIRING]` is between `:8587` and `:8589`**.
- `src/agent_team_v15/agents.py:8584-8587` — `[MODULE REGISTRATION]` block (no compose-wiring directive).
- `src/agent_team_v15/agents.py:8599-8605` — optional `[DEPENDENCY ARTIFACTS]`.
- `src/agent_team_v15/agents.py:8608-8618` — `[VERIFICATION CHECKLIST]`.
- `src/agent_team_v15/agents.py:8620` — `_format_ownership_claim_section("wave-b", config)` appender.
- `src/agent_team_v15/codex_prompts.py:10-157` — `CODEX_WAVE_B_PREAMBLE` definition (full body end-to-end).
- `src/agent_team_v15/codex_prompts.py:46-153` — AUD-009..023 hardener block in Codex path.
- `src/agent_team_v15/codex_prompts.py:152-157` — tail of PREAMBLE (AUD-023 terminal + closing `---`); **insertion point for Codex-path compose-wiring directive**.
- `src/agent_team_v15/codex_prompts.py:159-177` — `CODEX_WAVE_B_SUFFIX` verification checklist.
- `src/agent_team_v15/codex_prompts.py:245-248` — `_WAVE_WRAPPERS` registry mapping wave letter → (preamble, suffix).
- `src/agent_team_v15/codex_prompts.py:251-284` — `wrap_prompt_for_codex` composition; `:273-274` `wrapped = preamble + original_prompt + suffix`.
- `src/agent_team_v15/provider_router.py:298-303` — wraps `prompt` via `wrap_prompt_for_codex` → `codex_prompt`; import at `:300`.
- `src/agent_team_v15/provider_router.py:272-425` — fallback call sites (each passes the raw unwrapped `prompt` to `_claude_fallback`, stripping PREAMBLE/SUFFIX).
- `src/agent_team_v15/provider_router.py:429-459` — `_claude_fallback` definition; `:442-446` invokes `_execute_claude_wave(prompt=prompt, ...)`.
- `src/agent_team_v15/codex_transport.py:687-760` — `execute_codex` signature + retry loop; confirms prompt is flat stdin.
- `src/agent_team_v15/codex_transport.py:727-733` — `_execute_once(prompt, cwd, config, codex_home, ...)` — single-pass CLI invocation; no structural preamble/suffix distinction at transport.

## Section 1B — Scaffold verifier

- `src/agent_team_v15/scaffold_verifier.py:36` — `Verdict = Literal["PASS", "WARN", "FAIL"]`.
- `src/agent_team_v15/scaffold_verifier.py:39-56` — `ScaffoldVerifierReport` dataclass.
- `src/agent_team_v15/scaffold_verifier.py:64-178` — `run_scaffold_verifier` end-to-end.
- `src/agent_team_v15/scaffold_verifier.py:94-97` — violation accumulators (`missing`, `malformed`, `deprecated_emitted`, `summary`).
- `src/agent_team_v15/scaffold_verifier.py:119-131` — scope-filter logic for `allowed_file_globs`.
- `src/agent_team_v15/scaffold_verifier.py:160` — `_check_port_consistency` invocation; **insertion point for new `_check_compose_topology` and DoD-port oracle calls**.
- `src/agent_team_v15/scaffold_verifier.py:165-170` — verdict aggregation rules.
- `src/agent_team_v15/scaffold_verifier.py:186-195` — regex constants for PORT parsing (`_MAIN_TS_PORT_RE`, `_JOI_PORT_DEFAULT_RE`, `_ENV_EXAMPLE_PORT_RE`).
- `src/agent_team_v15/scaffold_verifier.py:252-298` — `_check_port_consistency` full body.
- `src/agent_team_v15/scaffold_verifier.py:281-292` — compose-yaml read; **only reads `services.api.environment.PORT`, not `services.api.ports[0]`** (smoke #11 gap).
- `src/agent_team_v15/scaffold_runner.py:94-119` — `ScaffoldConfig` dataclass (holds `port` default).
- `src/agent_team_v15/scaffold_runner.py:122-176` — `OwnershipContract` dataclass + parsing.

## Section 1C — Endpoint prober

- `src/agent_team_v15/endpoint_prober.py:1064-1096` — `_detect_app_url` full body.
- `src/agent_team_v15/endpoint_prober.py:1066-1068` — precedence #1 config.browser_testing.app_port.
- `src/agent_team_v15/endpoint_prober.py:1071-1073` — precedence #2 `<root>/.env`.
- `src/agent_team_v15/endpoint_prober.py:1076-1078` — precedence #3 `<root>/apps/api/.env.example`.
- `src/agent_team_v15/endpoint_prober.py:1081-1083` — precedence #4 `<root>/apps/api/src/main.ts`.
- `src/agent_team_v15/endpoint_prober.py:1086-1088` — precedence #5 `<root>/docker-compose.yml`.
- `src/agent_team_v15/endpoint_prober.py:1091-1096` — precedence #6 loud-warning fallback to `:3080`.
- `src/agent_team_v15/endpoint_prober.py:1099-1109` — `_port_from_env_file` helper shape.
- `src/agent_team_v15/endpoint_prober.py:1112-1128` — `_port_from_main_ts` helper shape.
- `src/agent_team_v15/endpoint_prober.py:1131-1163` — `_port_from_compose` helper shape (supports string and long-form dict port entries).
- `src/agent_team_v15/endpoint_prober.py:1166-1183` — `_poll_health` — first-source wins + retry-til-deadline; no mismatch error class.
- `src/agent_team_v15/endpoint_prober.py:707, 712, 725, 771, 796` — five call sites of `_detect_app_url` (milestone_id plumbing targets).

## Section 1D — Runtime verifier

- `src/agent_team_v15/cli.py:13640-13645` — runtime-verification invocation with config knobs.
- `src/agent_team_v15/cli.py:13646-13654` — `RUNTIME_VERIFICATION.md` report-text write.
- `src/agent_team_v15/cli.py:13662-13674` — `Runtime verification: N/M services healthy` emitter; **insertion point for expected-service-count tautology guard**.
- `src/agent_team_v15/cli.py:13666-13672` — per-service unhealthy loop + error prints.
- `src/agent_team_v15/cli.py:13673-13674` — zero-services-found branch (current tautology surface).
- `src/agent_team_v15/cli.py:13676` — Docker-unavailable branch.
- `src/agent_team_v15/cli.py:14598-14603` — `print_verification_summary` call; **secondary insertion point for empty-state tautology fix**.
- `src/agent_team_v15/display.py:436-464` — `print_verification_summary` function body; `:442-444` health default, `:457-458` banner line.
- `src/agent_team_v15/verification.py:82` — `overall_health` default is `"green"` on empty state (tautology root).
- `src/agent_team_v15/verification.py:377-392` — `update_verification_state` sets health from results.
- `src/agent_team_v15/verification.py:395-409` — `_health_from_results`: empty dict → `"green"` (fix point).
- `src/agent_team_v15/runtime_verification.py:1015-1210` — runtime verification core (`RuntimeReport` construction, `services_total` derivation).
- `src/agent_team_v15/runtime_verification.py:1133` — "All services healthy!" success log.
- `src/agent_team_v15/runtime_verification.py:1210` — runtime-verification-complete summary log.

## Section 1E — BUILD_LOG summary + TRUTH injection

- `src/agent_team_v15/cli.py:13725-13751` — TRUTH scoring block; `:13730-13733` console emit; `:13742-13751` `TRUTH_SCORES.json` persist.
- `src/agent_team_v15/cli.py:13754-13786` — Truth-threshold corrective action (post-TRUTH logic); **insertion point for TRUTH block panel is BEFORE `:13754`**.
- `src/agent_team_v15/gate_enforcer.py:316-336` — `TRUTH_SCORES.json` consumer (GATE_TRUTH_SCORE).
- `src/agent_team_v15/confidence_banners.py:179-219` — `stamp_build_log` function.
- `src/agent_team_v15/confidence_banners.py:257-291` — `stamp_all_reports` walks `.agent-team/` and stamps BUILD_LOG at `:288-291`.
- `MASTER_IMPLEMENTATION_PLAN_v2.md:1086-1105` — Phase FINAL exit criteria list (oracle for exit-criteria matrix).

## Section 1F — Ownership enforcer

- `docs/SCAFFOLD_OWNERSHIP.md:22-87` — Root (9 files) ownership rows.
- `docs/SCAFFOLD_OWNERSHIP.md:89-287` — apps/api (28 files) ownership rows.
- `docs/SCAFFOLD_OWNERSHIP.md:289-389` — apps/web (14 files) ownership rows.
- `docs/SCAFFOLD_OWNERSHIP.md:391-435` — packages/shared (6 files) ownership rows.
- `docs/SCAFFOLD_OWNERSHIP.md:437-460` — packages/api-client (3 files) ownership rows.
- `docs/SCAFFOLD_OWNERSHIP.md:464-471` — ownership totals table (44 scaffold / 12 wave-b / 1 wave-d / 3 wave-c-generator).
- `docs/SCAFFOLD_OWNERSHIP.md:476-479` — emits_stub breakdown (13 rows).
- `docs/SCAFFOLD_OWNERSHIP.md:480-494` — DRIFT summary table (9 clusters).
- `src/agent_team_v15/wave_executor.py:311-315` — `WAVE_SEQUENCES` (Wave A before Scaffold in all three templates).
- `src/agent_team_v15/wave_executor.py:4158-4167` — scaffold-artifact save (Scaffold completion hook site; **insertion point for ownership enforcer call #2**).
- `src/agent_team_v15/wave_executor.py:4193-4212` — `_maybe_run_scaffold_verifier` call + failure handling.
- `src/agent_team_v15/wave_executor.py:4620-4627` — Wave A completion block reading `WAVE_A_CONTRACT_CONFLICT.md`; **insertion point for ownership enforcer call #1**.
- `src/agent_team_v15/wave_executor.py:3881-3913` — per-wave artifact extract/save (first dispatch); `:3913` is **insertion point for ownership enforcer call #3 (first dispatch path)**.
- `src/agent_team_v15/wave_executor.py:4695-4700` — per-wave artifact extract/save (second dispatch); **insertion point for ownership enforcer call #3 (second dispatch path)**.
- `src/agent_team_v15/wave_executor.py:4821-4827` — `on_wave_complete` callback site (reference — do NOT edit).
- `src/agent_team_v15/wave_executor.py:2024-2075` — `_run_post_wave_e_scans` (pattern template for new `_run_ownership_enforcer`).
- `src/agent_team_v15/wave_executor.py:2078-2089` — `_violation_to_finding` severity map.
- `src/agent_team_v15/scaffold_runner.py:259-335` — `run_scaffolding` entry; `:306-314` `_scaffold_m1_foundation` call.
- `src/agent_team_v15/scaffold_runner.py:338-381` — `_maybe_validate_ownership` (N-02 soft warning).
- `src/agent_team_v15/scaffold_runner.py:713-736` — `_scaffold_m1_foundation` driver.
- `src/agent_team_v15/scaffold_runner.py:739-751` — `_write_if_missing` — `if path.exists(): return None` at `:740-741` (collision-skip with Wave A).
- `src/agent_team_v15/scaffold_runner.py:754-777` — `_scaffold_root_files` (6 files).
- `src/agent_team_v15/scaffold_runner.py:780-784` — `_scaffold_docker_compose`.
- `src/agent_team_v15/scaffold_runner.py:787-832` — `_scaffold_api_foundation`.
- `src/agent_team_v15/scaffold_runner.py:973-1031` — `_docker_compose_template()` body (externally importable).

## Section 1G — DoD feasibility

- `v18 test runs/build-final-smoke-20260419-043133/.agent-team/milestones/milestone-1/REQUIREMENTS.md:131-138` — M1 `## Definition of Done` section + bullet-list format.
- `v18 test runs/build-final-smoke-20260419-043133/.agent-team/milestones/milestone-2/REQUIREMENTS.md:142` — M2 `## Definition of Done` heading (format consistency).
- `v18 test runs/build-final-smoke-20260419-043133/.agent-team/milestones/milestone-1/REQUIREMENTS.md:134` — canonical probe anchor `GET http://localhost:3080/api/health` (port drift vs scaffold 4000).
- `v18 test runs/build-final-smoke-20260419-043133/.agent-team/milestones/milestone-1/REQUIREMENTS.md:85-86` — pnpm commands `openapi:export` and `@taskflow/api-client generate`.
- `v18 test runs/build-final-smoke-20260419-043133/.agent-team/milestones/milestone-1/REQUIREMENTS.md:112` — pnpm test commands list.
- `src/agent_team_v15/scaffold_runner.py:999-1000` — docker-compose template publishes `4000:4000` (source of drift).
- `src/agent_team_v15/scaffold_runner.py:1044-1050` — `apps/api/package.json` scripts (`build`, `start`, `start:dev`, `test`, `openapi`).
- `src/agent_team_v15/wave_executor.py:4834-4840` — `persist_wave_findings_for_audit` call (milestone teardown, ALWAYS fires post-loop).
- `src/agent_team_v15/wave_executor.py:4842-4861` — `architecture_writer.append_milestone` call (also fires post-loop); **insertion point for DoD feasibility verifier is between `:4840` and `:4842`**.
- `src/agent_team_v15/wave_executor.py:4829-4832` — `break` on failed wave; confirms teardown still runs after failure.

## Section 1H — Prompt-evolution history (git log)

- `git log --oneline src/agent_team_v15/agents.py` — top 10 commits `6069e1f, f57d9f6, 3bb7c47, 3ec96ba, 4f1270a, 466c3b9, 05fea20, a7db3e8, a0a053c, fbc8902` (as of discovery run on `b77fca0`).
- `git log --oneline src/agent_team_v15/codex_prompts.py` — top 4 commits `a7db3e8, d6a2020, dc66069, 66f1717`.
- Commit `a0a053c` — Phase B scaffold + spec alignment; introduced docker-compose topology emission without updating Wave B prompt.
- Commit `a7db3e8` — Phase C AUD-009..023 hardeners; the parallel Claude-path + Codex-path pattern to copy for compose-wiring.

## Section 1I — Test patterns

- `tests/test_scaffold_verifier_post_scaffold.py:23` — `test_verifier_call_appears_after_save_wave_artifact_scaffold` (AST call-ordering assertion).
- `tests/test_scaffold_verifier_post_scaffold.py:68` — `test_scaffold_verifier_fail_uses_scaffold_error_wave`.
- `tests/test_scaffold_verifier_post_scaffold.py:94` — `test_verifier_not_called_from_wave_a_post_compile_block`.
- `tests/test_scaffold_verifier_scope.py:34-41` — `_contract([...])` fixture helper for minimal `OwnershipContract`.
- `tests/test_scaffold_verifier_scope.py:44-52` — `_m1_foundation_files` fixture helper for minimal workspace.
- `tests/test_scaffold_verifier_scope.py:60` — `test_scope_aware_filters_m2_m5_rows` (verdict + summary-line assertion).
- `tests/test_scaffold_verifier_scope.py:117` — `test_scope_aware_still_flags_in_scope_missing`.
- `tests/test_scaffold_verifier_scope.py:169` — `test_no_scope_preserves_legacy_all_rows`.
- `tests/test_scaffold_verifier_scope.py:195` — `test_empty_globs_preserves_legacy_behaviour`.
- `tests/test_scaffold_verifier_ordering.py:63` — `test_scaffolding_start_wave_contract` (parametrized template contract).
- `tests/test_scaffold_verifier_ordering.py:87` — `test_wave_a_verifier_does_not_fire_before_scaffolder` (AST negative assertion).
- `tests/test_scaffold_verifier_ordering.py:131` — `test_at_least_one_verifier_call_site_exists`.
- `tests/test_endpoint_prober.py:17-22` — `_cfg(app_port=N)` fixture helper.
- `tests/test_endpoint_prober.py:25` — `test_detect_from_config_browser_testing_app_port_still_wins`.
- `tests/test_endpoint_prober.py:31, 37, 44, 51, 58, 65` — full precedence-chain per-source tests.
- `tests/test_endpoint_prober.py:72, 80` — precedence-ordering tests (each higher source beats lower).
- `tests/test_endpoint_prober.py:90` — `test_fallback_warning_when_all_sources_fail` (caplog pattern).
- `tests/test_v18_wave_executor_extended.py:42-114` — `_run_waves(tmp_path, ...)` harness helper for integration tests.
- `tests/test_v18_wave_executor_extended.py:394` — `test_on_wave_complete_called_for_each_wave` (integration callback assertion).
- `tests/test_v18_wave_executor_extended.py:405` — `test_on_wave_complete_receives_wave_result`.
- `tests/test_n09_wave_b_prompt_hardeners.py:1-50` — pattern for asserting PROMPT content contains required ID strings (copy for compose-wiring directive presence tests).

---

## Verification stamp

All line numbers above were opened and read during the Wave 1 discovery session on branch `phase-h1a-compose-ownership-enforcement` @ `b77fca0`. A future agent verifying this receipt should spot-check 3-5 random citations by direct file-read before relying on the architecture report.
