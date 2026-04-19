# Phase H1a — Architecture Blueprint

> Branch: `phase-h1a-compose-ownership-enforcement` (cut from `integration-2026-04-15-closeout` @ `b77fca0`)
> HEAD verified: `b77fca0e2c2e41bb778ccb3da9bfaf7c222b860d`
> Author: `discovery-agent` (Wave 1, Phase H1a)
> Companion receipt: `docs/plans/phase-h1a-discovery-citations.md`

## Overview

Phase H1a fixes six structural pipeline defects exposed by smoke #11. Wave 2 will implement: (1) a Wave B compose-wiring prompt directive, (2) DoD-port oracle + compose-topology structural checks, (3) DoD-port guard in the endpoint prober, (4) an ownership-contract enforcer that runs at three pipeline boundaries, (5) a runtime-verifier expected-service-count cross-check, (6) a BUILD_LOG summary block that actually surfaces the TRUTH gate and tautology failure. This report fixes the exact insertion points and references the downstream test patterns to copy. All line numbers verified at h1a HEAD by direct read (not copied from smoke #11 notes).

---

## Section 1A — Wave B prompt structure & compose-wiring placement

### Claude path (`build_wave_b_prompt`)

`src/agent_team_v15/agents.py:8364-8624`. Signature at `:8364-8376`. Section order (via the `parts: list[str]` accumulator built `:8416-8597`, with optional appends `:8538-8605`, and closing verification checklist `:8608-8618`):

1. `existing_prompt_framework` (caller-supplied base), `:8417`
2. Optional `<architecture>` XML block (Phase G Slice 5c), `:8420-8421`
3. `[WAVE B - BACKEND SPECIALIST]` + `[EXECUTION DIRECTIVES]`, `:8423-8432`
4. Optional `[CURRENT FRAMEWORK IDIOMS]` (mcp_doc_context), `:8434-8441`
5. `[CANONICAL NESTJS 11 / PRISMA 5 PATTERNS - APPLY FOR THIS WAVE]` (AUD-009/010/012/013/016/018/020/023), `:8444-8493`
6. `[YOUR TASK]`, `:8495-8499`
7. `[CODEBASE CONTEXT]`, `:8501-8513`
8. `[MILESTONE REQUIREMENTS]` + `[MILESTONE TASKS]`, `:8514-8518`
9. `[PRODUCT IR EXTRACT]`, `[ENDPOINTS]`, `[STATE MACHINES]`, `[BUSINESS RULES]`, `[EVENTS]`, `:8520-8535`
10. Optional `[INTEGRATION CONTEXT]`, `[ADAPTER PORTS]`, `:8538-8552`
11. `[DESIGN SYSTEM ...]`, `[IMPLEMENTATION PATTERNS]`, `[FILE ORGANIZATION]`, `[MODULE REGISTRATION]`, `[BARREL EXPORTS]`, `[TESTING REQUIREMENTS]`, `:8555-8597`
12. Optional `[DEPENDENCY ARTIFACTS ...]`, `:8599-8605`
13. `[VERIFICATION CHECKLIST]`, `:8608-8618`
14. Ownership-claim section (`_format_ownership_claim_section("wave-b", config)`), `:8620`

The Wave B prompt today carries **no infrastructure-wiring directive**. `[MODULE REGISTRATION]` at `:8584-8587` is the nearest analog but it only discusses NestJS module imports, not docker-compose / env.example / main.ts PORT coupling.

**Best insertion point for the new compose-wiring directive (Claude path):** immediately after `[MODULE REGISTRATION]` and before `[BARREL EXPORTS]` — i.e. insert a new `[INFRASTRUCTURE WIRING]` block into the `parts.extend([...])` call that starts at `:8554`, slotting between the line at `:8587` and the `[BARREL EXPORTS]` header at `:8589`. The directive should: (a) quote the canonical PORT (oracle-read from REQUIREMENTS DoD, not hard-coded), (b) require PORT parity across `main.ts`, `env.validation.ts`, `.env.example`, `apps/api/.env.example`, and `docker-compose.yml services.api.{environment.PORT, ports}`, (c) require `services.api.depends_on.postgres: {condition: service_healthy}`, (d) require `services.web.depends_on.api: {condition: service_healthy}`, (e) reference `_docker_compose_template()` as the shape to match but forbid rewriting it (ownership=scaffold).

### Codex path (`CODEX_WAVE_B_PREAMBLE` + `CODEX_WAVE_B_SUFFIX`)

`src/agent_team_v15/codex_prompts.py:10-157` (preamble) and `:159-177` (suffix). Composition at `:269-274`: `wrapped = preamble + original_prompt + suffix` (where `original_prompt` is the return of `build_wave_b_prompt`). Token registry at `:245-248`.

### Codex dispatch vs Claude-fallback

`src/agent_team_v15/provider_router.py:298-303` wraps `prompt` with `wrap_prompt_for_codex` to produce `codex_prompt`, then the fallback paths at `:273-280, 285-292, 309-316, 336-343, 352-358, 365-371, 387-391, 419-425` (each exception/unavailability case) call `_claude_fallback(prompt=prompt, …)` with the **raw, unwrapped** `prompt` — i.e. the PREAMBLE/SUFFIX are stripped on Claude fallback. `_claude_fallback` definition at `:429-459` confirms: `await _execute_claude_wave(prompt=prompt, …)`.

**Consequence:** a directive placed only in PREAMBLE/SUFFIX will disappear on any Claude fallback (watchdog timeout, orphan-tool, Codex unavailable). A directive placed in the body of `build_wave_b_prompt` survives both paths.

### PREAMBLE vs SUFFIX vs both — placement recommendation

**Recommendation: BOTH Codex-path AND Claude-body.**

- **Body of `build_wave_b_prompt` (required — Claude-path survival).** Because the fallback ignores the Codex wrapper, compose-wiring is a load-bearing invariant: if M1 emits the wrong PORT, the endpoint probe fails structurally, not as a recoverable finding. The directive must be inside the body at the `[MODULE REGISTRATION]`-adjacent slot noted above.
- **Also CODEX_WAVE_B_PREAMBLE (recommended — attention salience on the Codex path).** Codex's agentic loop re-reads the system prompt at each turn; placing the compose-wiring invariant in PREAMBLE elevates its salience for tool-using passes that might re-derive compose shape from partial context.
- **Not SUFFIX alone.** The SUFFIX is a post-work "verification checklist" — fine for a final self-audit bullet ("PORT consistent across main.ts / env.validation.ts / .env.example / docker-compose.yml") but suffix-only placement means the agent sees the rule after it has already written the code. Agents do not reliably self-correct from suffix checklists; we saw this pattern fail in smoke #4 AUD-020 regressions before hardeners moved into PREAMBLE.

Justification grounded in Codex composition semantics: `execute_codex` (`src/agent_team_v15/codex_transport.py:687-760`, called at `_execute_once` `:727`) receives a single flat `prompt` string via stdin (the CLI has no structural distinction between preamble/body/suffix — `wrap_prompt_for_codex` is purely lexical concatenation, `src/agent_team_v15/codex_prompts.py:273` `preamble + original_prompt + suffix`). There is no Codex-native "system prompt wins over user prompt" precedence. Position therefore matters only for attention salience, not semantics. PREAMBLE-first is conventional for hard invariants in this codebase (AUD-009…023 all live in PREAMBLE per `:46-153`) and a new compose-wiring block should follow that convention. SUFFIX adds a terminal double-check bullet; body-placement closes the Claude-fallback gap.

**Concrete Wave 2A patch surface:**
- `src/agent_team_v15/agents.py` — insert `[INFRASTRUCTURE WIRING]` block into the `parts.extend(...)` call starting at `:8554`, slotting between `:8587` (`- Do not create a second 'main.ts'...`) and the `[BARREL EXPORTS]` header at `:8589`.
- `src/agent_team_v15/codex_prompts.py` — append `## Infrastructure Wiring (Compose + env parity)` block inside `CODEX_WAVE_B_PREAMBLE` after AUD-023 at `:152` and before the closing `---` at `:155`.
- Optionally append a one-line `[ ] PORT consistent across main.ts, env.validation.ts, .env.example, docker-compose.yml services.api.{environment.PORT, ports[0]}` bullet to `CODEX_WAVE_B_SUFFIX` at `:176` for the final-self-audit pass.

No HALT on this section.

---

## Section 1B — Scaffold verifier pattern + insertion points

### File

`src/agent_team_v15/scaffold_verifier.py` (end-to-end 299 lines, verified).

### Pattern for adding a structural check

- **Entry point.** `run_scaffold_verifier(workspace, ownership_contract, scaffold_cfg=DEFAULT_SCAFFOLD_CONFIG, *, deprecated_paths=None, milestone_scope=None) -> ScaffoldVerifierReport`, `:64-178`.
- **Violation collection.** Four parallel lists at `:94-97`: `missing`, `malformed` (tuple list of `(Path, diagnostic_str)`), `deprecated_emitted`, and `summary` (human-readable lines prefixed with tokens like `MISSING`, `MALFORMED`, `PORT_INCONSISTENCY`, `SCOPE_FILTER`, `DEPRECATED_EMITTED`).
- **Severity → verdict aggregation.** `:165-170`: `FAIL` if `missing or malformed`, else `WARN` if `deprecated_emitted`, else `PASS`. Verdict is a `Literal["PASS", "WARN", "FAIL"]` at `:36`.
- **Report dataclass.** `ScaffoldVerifierReport` at `:39-56` carries `verdict`, `missing`, `malformed`, `deprecated_emitted`, `summary_lines`. `.summary()` at `:47-56` produces the logged one-liner.
- **How a new check plugs in.** Add a private helper (pattern: `_check_<invariant>(workspace, ...) -> Optional[str]`) that returns `None` on pass or a diagnostic string on fail. Call it near `:160` where `_check_port_consistency` is invoked; append to `malformed` with the offending anchor path and to `summary` with a tokenized line.

### `_check_port_consistency` — current behavior

`src/agent_team_v15/scaffold_verifier.py:252-298`. Canonical port source: `scaffold_cfg.port` (parameter, default `DEFAULT_SCAFFOLD_CONFIG.port`). PORT-collection sites (`observations` list at `:255`):
- `apps/api/src/main.ts` via regex `\.listen(process.env.PORT ?? <N>)` (`_MAIN_TS_PORT_RE` at `:193`), `:257-261`.
- `apps/api/src/config/env.validation.ts` via Joi `.default(<N>)` (`_JOI_PORT_DEFAULT_RE` at `:189-192`), `:263-267`.
- `.env.example` via `^PORT=<N>$` (`_ENV_EXAMPLE_PORT_RE` at `:194`), `:269-273`.
- `apps/api/.env.example`, `:275-279`.
- `docker-compose.yml` under `services.api.environment.PORT`, `:281-292`. **Gap:** it reads `services.api.environment.PORT` but not `services.api.ports[0]` (the host:container mapping — that's where `ports: ["4000:4000"]` lives in `_docker_compose_template():1000`). Smoke #11 exposed this: compose can have `environment.PORT=4000` yet `ports: ["3080:4000"]` which means the probe hits 3080 and the service listens on 4000.
- Handling of missing `services.api`: silently skipped (the `if not isinstance(services, dict)` → fall-through pattern at `:283-292`). No finding is emitted when `api` service is entirely absent.

### REQUIREMENTS.md today

The verifier does **not** read `REQUIREMENTS.md`. `scaffold_cfg.port` comes from `ScaffoldConfig` (see `scaffold_runner.py:94-119` for the dataclass; default port set at module level). The spec-reconciliation path at `wave_executor.py:4139-4150` can override `scaffold_cfg` via `_maybe_run_spec_reconciliation`, but that targets the scaffolder, not the verifier. A DoD-port oracle reading `.agent-team/milestones/<id>/REQUIREMENTS.md` would be a net-new surface for the verifier.

### Insertion points (Wave 2B)

- **DoD-port oracle.** Add a loader `_load_dod_port(workspace: Path, milestone_id: str) -> Optional[int]` that greps the milestone's `REQUIREMENTS.md` under `.agent-team/milestones/<id>/REQUIREMENTS.md` for canonical port strings (see 1G for the observed DoD format — `GET http://localhost:<PORT>/api/health` is the anchor). Thread `milestone_id` through `run_scaffold_verifier`'s signature (`:64-71`) and through the call site at `wave_executor.py:4194-4200`. Cross-check: if `dod_port is not None and dod_port != scaffold_cfg.port`, emit a new `summary` token `DOD_PORT_DRIFT scaffold_cfg.port=<X> dod_port=<Y>` and add a `malformed` entry keyed at `.agent-team/milestones/<id>/REQUIREMENTS.md`. This makes the verifier catch drift between REQUIREMENTS and the resolved `ScaffoldConfig` — smoke #11's "scaffold uses 4000 but REQUIREMENTS says 3080" defect.
- **Compose topology check.** Add `_check_compose_topology(workspace: Path) -> Optional[str]` near the existing `_check_port_consistency` (insert a call at `:160` alongside the port check). Required invariants:
  - `services.api` exists and has `depends_on.postgres.condition == "service_healthy"`.
  - `services.web` exists and has `depends_on.api.condition == "service_healthy"`.
  - `services.postgres` exists and has a `healthcheck` with `pg_isready`.
  - `services.api.ports[0]` host-side matches `services.api.environment.PORT` (extend the existing port-consistency check to cover this specifically).
  - Use `_docker_compose_template()` (imported from `scaffold_runner`) as the structural oracle — diff the loaded compose against the template's service shape for depends-on + healthcheck keys; do NOT diff port literal values (those are allowed to differ per milestone resolution).

---

## Section 1C — Endpoint prober chain + DoD-port guard insertion

### File & function

`src/agent_team_v15/endpoint_prober.py:1064-1096`. `_detect_app_url(project_root: Path, config: Any) -> str`.

### Exact precedence order

Numbered comments at `:1065-1090` match the code exactly:
1. `config.browser_testing.app_port`, `:1066-1068`.
2. `<root>/.env` PORT=, via `_port_from_env_file()` (`:1099-1109`), `:1071-1073`.
3. `<root>/apps/api/.env.example` PORT=, `:1076-1078`.
4. `<root>/apps/api/src/main.ts` app.listen pattern, via `_port_from_main_ts()` (`:1112-1128`), `:1081-1083`.
5. `<root>/docker-compose.yml` `services.api.ports[0]` host-port, via `_port_from_compose()` (`:1131-1163`), `:1086-1088`.
6. Loud-warning fallback to `http://localhost:3080`, `:1091-1096`.

### Mismatch handling today

`_detect_app_url` returns a single URL — it never compares across sources. Downstream, `_poll_health(app_url, timeout)` at `:1166-1183` walks candidate paths `/api/health`, `/health`, `/`, `/api`; on connection refusal it retries with 1s sleep until the deadline. There is no "port mismatch detected" error class — the prober is first-source-wins + retry-til-deadline. A PORT split between compose-published and env-expected silently produces the wrong URL and then fails with a plain timeout.

### DoD-port guard insertion point

**In `_detect_app_url`, insert a DoD oracle check at the TOP of the function**, before the `config.browser_testing.app_port` branch at `:1066`. New sub-call: `dod_port = _port_from_dod_requirements(project_root, milestone_id)`. If `dod_port` is set, compare it to the resolved port from the existing precedence chain and:
- **PASS case:** if they agree, continue.
- **FAIL case:** if they differ, log a `CRITICAL` level message naming both sides, and return `http://localhost:<dod_port>` **with** a new outparam or raise-raise (e.g. write `.agent-team/milestones/<id>/PROBE_PORT_MISMATCH.json`) so callers can surface the drift as a WaveFinding rather than eat a silent health-check timeout.

`milestone_id` plumbing: `_detect_app_url` is called at `endpoint_prober.py:707, 712, 725, 771, 796`. These sites are inside `execute_probes` / `_poll_docker_app`. Thread `milestone_id` in via the caller at `_run_wave_b_probing` (`wave_executor.py:3920-3944`). Alternative (simpler): read the milestone id from the `.agent-team/milestones/<id>/` directory that's already resolved in the caller context, and pass it through as a new kwarg on `_detect_app_url`.

An additional DoD-port `_port_from_dod_requirements` helper should follow the pattern of the existing `_port_from_env_file` (`:1099-1109`) — read a single file, regex-match, return `int | None`.

---

## Section 1D — Runtime verifier output path + tautology guard

### Emitter

`src/agent_team_v15/cli.py:13662-13674` — `print_info(f"Runtime verification: {rv_report.services_healthy}/{rv_report.services_total} services healthy ({rv_report.total_duration_s:.0f}s)")`. Inputs: `rv_report` (a `RuntimeReport` produced by `runtime_verification.py`), specifically `services_healthy` (int), `services_total` (int), `total_duration_s` (float), `services_status` (list of `ServiceStatus` with `.service`, `.healthy`, `.error`).

Adjacent `Overall health: GREEN/YELLOW/RED` banner at `display.py:457-458` (called from `cli.py:14598-14603`) — this is the verification panel, computed by `verification._health_from_results` (`verification.py:395-409`) which flips to RED on `any fail`, YELLOW on `any partial`, else GREEN. The default state when no tasks recorded is GREEN (`:404-405`). This is the tautology smoke #11 called out: an empty/unpopulated progressive-verification state reports GREEN.

### How `M` (`services_total`) is computed today

In `runtime_verification.py` (`:1015-1210`), `services_total` is set from the compose-file service list that was parsed at the start of verification. The "expected service count" for the tautology guard is the same source — it's just an earlier assertion about that value.

### Tautology guard insertion point

**Primary insertion:** `cli.py:13662-13674`. Split the current single-line `print_info` into a conditional:
- Compute `expected_total = _count_expected_services(compose_path)` (new helper; reuse `_port_from_compose`'s yaml load path from `endpoint_prober.py:1131-1163`).
- If `rv_report.services_total < expected_total`: emit a `WaveFinding`-equivalent and print `Runtime verification INCOMPLETE: expected <expected_total> services (api, web, postgres), verified <rv_report.services_total>. Skipped: <list>.` and mark health downgrade.
- If `rv_report.services_total == 0 and expected_total > 0`: emit the stronger `Runtime verification did NOT run on any service — BLOCKING` variant (today this path emits only a `print_warning` at `:13674`, which is exactly the tautology).

**Secondary insertion:** `cli.py:14598-14603` (`print_verification_summary` call). The caller passes `overall_health` from `state.overall_health`. If `state.completed_tasks` is empty, the current default is "green" (`verification.py:395-409`). Replace with: if empty and the compose exists, set health to `unknown` (new terminal state) and render "Overall health: UNKNOWN — no verification tasks recorded". This closes the "empty GREEN" tautology by refusing to claim success when nothing was checked.

**Tertiary:** add the `expected_services_count` field into the `RuntimeReport` dataclass in `runtime_verification.py` so it's persisted to `RUNTIME_VERIFICATION.md` (written at `cli.py:13649-13652`), not just the console.

---

## Section 1E — BUILD_LOG summary emitter + TRUTH/gate injection

### Summary emitter today

BUILD_LOG.txt is written incrementally throughout the run (no single emitter). The observable trailing lines from smoke run `v18 test runs/build-final-smoke-20260419-043133/BUILD_LOG.txt` tail confirm: the summary is the concatenated console output including: "Contract compliance E2E complete — cost: $X", recovery panel, `[TRUTH] Score: 0.548 (gate: escalate)`, and the `VERIFICATION SUMMARY` panel with `Overall health: GREEN`.

Pre-summary stamping: `confidence_banners.stamp_build_log(path, label, reasoning)` at `src/agent_team_v15/confidence_banners.py:179-219` prepends a `[CONFIDENCE=...]` header line. Orchestration call at `stamp_all_reports` `:257-291`, BUILD_LOG glob at `:288-291`.

The `[TRUTH] Score: ...` emission is at `cli.py:13725-13751`:
- `_post_truth_scorer.score()` produces `_post_truth_score` with `.overall`, `.gate`, `.dimensions`, `.passed`.
- `TRUTH_SCORES.json` written at `cli.py:13742-13751` under `<cwd>/<requirements_dir>/TRUTH_SCORES.json`.
- Consumer: `gate_enforcer.py:316-336`, reads `.agent-team/TRUTH_SCORES.json` and raises on missing/malformed.

### TRUTH block injection point

**Insert at `cli.py` after the block that writes `TRUTH_SCORES.json` (after `:13751`) and before the `_truth_threshold` check at `:13754`.** Emit a new console block via `print_info` that follows the existing panel style (use `display.py` helpers):

```
[TRUTH] Score: <overall> (gate: <gate>, passed: <bool>)
[TRUTH] Dimensions: requirements=<x.xx> contracts=<x.xx> evidence=<x.xx> ...
[TRUTH] Gate verdict: <PASS|ESCALATE|FAIL> — threshold <truth_threshold>
[TRUTH] Exit criteria matrix: <N> checks, <K> PASS, <F> FAIL
```

The `Exit criteria matrix` is the new deliverable — it cross-references `MASTER_IMPLEMENTATION_PLAN_v2.md:1086-1105` exit criteria against the run's observed state (e.g. `summary.success` vs `failed_milestones` consistency per NEW-7). A new helper `_format_exit_criteria_matrix(config, cwd, state, truth_score) -> list[str]` should live in a new or existing module — consider `verification.py` since it already owns progressive-verification state. The matrix is appended to BUILD_LOG via the existing print pipeline (BUILD_LOG captures everything that reaches stdout).

**Format note:** the TRUTH block should be rendered INSIDE a Rich `Panel` (see `display.py:463-464` for the pattern) so it visually pops in the BUILD_LOG and so future log-scrapers can anchor on the panel border.

---

## Section 1F — Ownership enforcer — three hook sites

### Ownership contract source

`docs/SCAFFOLD_OWNERSHIP.md` (495 lines). Owner enumeration at the totals table `:464-471`: 44 `scaffold`, 12 `wave-b`, 1 `wave-d`, 3 `wave-c-generator`. The `owner=scaffold` paths are the 44 rows marked `owner: scaffold` across Root (9), apps/api (28), apps/web (14), packages/shared (6), minus the entries with different owner. (Counts align with the breakdown at `:464-478` including the 11 scaffold-stub rows.)

### Wave A ordering vs Scaffold (CRITICAL plan verification)

`src/agent_team_v15/wave_executor.py:311-315` — `WAVE_SEQUENCES`:
- `full_stack`: `["A", "A5", "Scaffold", "B", "C", "D", "T", "T5", "E"]`
- `backend_only`: `["A", "A5", "Scaffold", "B", "C", "T", "T5", "E"]`
- `frontend_only`: `["A", "Scaffold", "D", "T", "T5", "E"]`

Wave A **does** run BEFORE Scaffold in every template. Confirmed at h1a HEAD.

### `_write_if_missing` — Wave A collision behavior

`src/agent_team_v15/scaffold_runner.py:739-751`. At `:740-741`: `if path.exists(): return None`. So when Wave A already wrote files into the tree, the scaffolder silently skips re-writing them. **Consequence for ownership enforcement:** if Wave A produces a `docker-compose.yml` or `src/database/prisma.service.ts` before Scaffold runs, the scaffolder will not overwrite — Wave A's (potentially wrong) content wins. This is the exact defect class Phase H1a is closing.

### `_docker_compose_template()` external importability

`src/agent_team_v15/scaffold_runner.py:973-1031`. Module-level function with no leading underscore in the name prefix that'd suggest module-privacy contract (the single leading `_` is Python convention but it IS importable from outside the module). Verified externally importable: `from agent_team_v15.scaffold_runner import _docker_compose_template` returns the template bytes (test-executed during this discovery; no HALT).

### Post-Wave-E scanner pattern (the pattern the enforcer should copy)

`src/agent_team_v15/wave_executor.py:2024-2075` — `_run_post_wave_e_scans(cwd: str) -> list[WaveFinding]`. Pattern:
1. Best-effort try/except around each scanner with `logger.warning` on failure.
2. Each scanner yields `Violation` objects; adapter `_violation_to_finding` (`:2078-2089`) maps them to `WaveFinding` (severity_map = `error→HIGH`, `warning→MEDIUM`, `info→LOW`, `critical→HIGH`).
3. Called at `:3951, :4759` — inside the per-wave loop, guarded by `if wave_letter == "E"`.

The ownership enforcer should follow the exact same convention: a `_run_ownership_enforcer(cwd, *, phase: str, contract: OwnershipContract) -> list[WaveFinding]` that emits `WaveFinding` objects with codes like `OWN-WAVE-A-OVERRUN`, `OWN-SCAFFOLD-SHADOW`, `OWN-WAVE-B-SHADOW`.

### Three hook sites (exact line numbers at h1a HEAD)

1. **Wave A completion hook.** `src/agent_team_v15/wave_executor.py:4620-4627` — this is the existing `if wave_letter == "A" and wave_result.success:` block that reads `WAVE_A_CONTRACT_CONFLICT.md`. **Extend this block** with a call to the new ownership enforcer AFTER the conflict-file check. The enforcer should check: did Wave A write any file whose ownership contract says `owner != "wave-a"` (i.e. any `owner: scaffold`, `wave-b`, `wave-d`, `wave-c-generator` row)? If yes, findings with code `OWN-WAVE-A-OVERRUN`. Findings are HIGH severity and should flip `wave_result.success = False` (mirroring the existing contract-conflict pattern at `:4622-4627`).

2. **Scaffold completion hook.** `src/agent_team_v15/wave_executor.py:4158-4167` — immediately after `_save_wave_artifact(scaffold_artifact, cwd, result.milestone_id, "SCAFFOLD")`. The verifier already fires here at `:4193-4212`. **Add the ownership enforcer call between `:4167` and `:4180`** (before the `_install_workspace_deps_if_needed` call) — OR fold into `_maybe_run_scaffold_verifier` as a new kind of check. The enforcer should check: did the scaffolder skip a `owner: scaffold, optional: false` path because Wave A already wrote it (the `_write_if_missing` skip)? Compare `milestone_scaffolded_files` against the scaffold-owned rows; any skipped row that exists on disk but wasn't in the emit list is a `OWN-SCAFFOLD-SHADOW` finding.

3. **Post-each-non-A wave hook.** The `on_wave_complete` callback site at `src/agent_team_v15/wave_executor.py:4821-4827` — this fires after every wave. **Do NOT edit that block;** instead, hook alongside the compile-fix result block at `:3881-3913` (the "if wave_result.success and wave_letter not in {C, A5, T5}" branch) OR at the sibling `:4695-4700` (the second dispatch path). Both branches run the extract-artifacts + artifact-save sequence. **Add the enforcer after artifact save and before any probe block**, specifically at `:3913` (after the `wave_artifacts[wave_letter] = artifact` line) and at `:4700` (same place on the second dispatch). The enforcer checks: did this wave write any file outside its owner rows? `wave_result.files_created + wave_result.files_modified` is the audit surface. Findings are `OWN-WAVE-<letter>-SHADOW`.

### HALT check: pre-scaffold ownership-enforcer hook

The plan mentions "ownership_enforcer's pre-scaffold hook point". There IS a pre-scaffold-completion slot (post-Wave-A, pre-scaffold-start), but it is EFFECTIVELY the "Wave A completion hook" above (site #1) — the pre-scaffold boundary and the Wave A completion boundary are the same point in time because `WAVE_SEQUENCES` puts A immediately before Scaffold. **No new hook point needs to be created.** No HALT.

---

## Section 1G — DoD feasibility inputs + hook site

### REQUIREMENTS.md shape (from preserved smoke runs)

From `v18 test runs/build-final-smoke-20260419-043133/.agent-team/milestones/milestone-1/REQUIREMENTS.md:131-138`:

```
## Definition of Done

- `pnpm install && pnpm typecheck && pnpm lint && pnpm build` succeeds.
- `docker compose up -d postgres && pnpm db:migrate && pnpm dev` boots; `GET http://localhost:3080/api/health` returns `{ data: { status: 'ok', db: 'up' } }`.
- `pnpm --filter api openapi:export && pnpm --filter @taskflow/api-client generate` produces a client with at least the `/api/health` method and no uncommitted diff.
```

M2 (`milestones/milestone-2/REQUIREMENTS.md:142`) uses the identical `## Definition of Done` heading followed by bullet-list items.

### Format observed

- Heading: always `## Definition of Done` (exact string, h2).
- Body: markdown bullet list. Each bullet is a single sentence, may contain backticked inline commands and/or URLs. Multi-line commands are rare; when present they're `&&`-chained on a single bullet line.
- Port anchor pattern: `http://localhost:<PORT>/...` inline-quoted, typically with `GET /api/health`.

### Three-to-five concrete command-line examples seen

1. `pnpm install && pnpm typecheck && pnpm lint && pnpm build`
2. `docker compose up -d postgres && pnpm db:migrate && pnpm dev`
3. `GET http://localhost:3080/api/health` (not a shell command but a probe-spec; regex target for DoD-port oracle)
4. `pnpm --filter api openapi:export && pnpm --filter @taskflow/api-client generate`
5. `pnpm test:unit`, `pnpm test:e2e`, `pnpm test:smoke` (line 112 of M1)

**NOTE (smoke #11 drift):** the preserved M1 REQUIREMENTS says `3080` while the scaffold's `_docker_compose_template` publishes `4000:4000` and `env_validation` defaults to `4000` (verified at `scaffold_runner.py:999-1000`). This is exactly the drift the DoD-port oracle (Section 1B) should catch.

### package.json candidates for script lookup

Three sites to scan for DoD-cited `pnpm` scripts:
1. `<root>/package.json` — top-level workspace manifest; holds aggregate commands like `typecheck`, `lint`, `build`, `dev`, `test:unit`, `test:e2e`.
2. `<root>/apps/api/package.json` — holds `build`, `start`, `start:dev`, `test`, `openapi`, `openapi:export` (per `scaffold_runner.py:1044-1050`).
3. `<root>/apps/web/package.json` — holds Next.js `dev`, `build`, `start`, and `@taskflow/api-client generate` via workspace filter.

### Hook site for DoD feasibility verifier (CRITICAL: must fire on failed milestones)

**Target:** `src/agent_team_v15/wave_executor.py:4834-4861` (the milestone-teardown block after the wave loop exits). Specifically:
- The `persist_wave_findings_for_audit(...)` call at `:4834-4840` **always fires** after the wave loop (the `break` at `:4832` exits the `for wave_letter in waves[start_index:]` loop but falls through to the teardown).
- The architecture-writer block at `:4842-4861` also always fires.
- **Insert the DoD feasibility verifier between `:4840` (after `persist_wave_findings_for_audit`) and `:4842` (before the architecture append).** This guarantees:
  - Fires on all milestones regardless of Wave outcome.
  - Not Wave-E-gated (even Wave-B-failed milestones like smoke #11 M1 get DoD feasibility output).
  - Has access to `result.waves`, `result.milestone_id`, `wave_artifacts`, `cwd`, `config` — the full set needed to compare DoD bullets to observed artifact state.

Flag-gate the new verifier with a `v18.dod_feasibility_enabled` config knob per Phase B convention (see `_get_v18_value` usage at `:4193`, `:4844`). Default OFF; Phase FINAL smoke flips ON.

No HALT on this section.

---

## Section 1H — Historical Wave B prompt evolution

`git log --oneline -n 10 src/agent_team_v15/agents.py` returns the last ~10 Phase touches:

```
6069e1f Exhaustive walker sweep + pattern-audit fixes (agent-team dispatch)
f57d9f6 Close the A-09 selector-scope class — endpoints + ACs + business_rules
3bb7c47 Wave B selector scope: apply MilestoneScope to state_machines + events
3ec96ba Fix Wave A entity-scope contradiction for foundation milestones
4f1270a Phase G: Pipeline Restructure + Prompt Engineering
466c3b9 Phase F: Final Review, Fix, Test & Closure Sprint
05fea20 Phase E: NEW-10 Claude Bidirectional Migration + Bug #20 Codex App-Server
a7db3e8 Phase C: Truthfulness + Audit Loop — N-08/09/10/17 + D-02/09/14 + C-CF-1/2/3 + N-14
a0a053c Phase B: Scaffold + Spec Alignment — N-02/03/04/05/06/07/11/12/13 + NEW-1/NEW-2
fbc8902 Integration: merge PR #8 (provider-neutral Wave B/D prompts)
```

Most compose-adjacent change: **Phase B (`a0a053c`)** introduced the scaffold ownership + spec-alignment work (docker-compose topology emission via `_docker_compose_template`, PORT reconciliation via `ScaffoldConfig`). The Wave B prompt was not updated at that time to carry a mirror directive — scaffolding was treated as deterministic enough that Wave B didn't need to be told not to touch it. Smoke #11 shows this assumption holds only when Wave A respects ownership — which it does not structurally enforce today.

Phase C (`a7db3e8`) added the AUD-009..023 hardener blocks to both `build_wave_b_prompt` (`:8444-8493`) and `CODEX_WAVE_B_PREAMBLE` (`:46-153`). That is the template Phase H1a's compose-wiring directive should follow: parallel Claude-path and Codex-path placement.

`git log --oneline src/agent_team_v15/codex_prompts.py`: the last 4 commits (a7db3e8, d6a2020, dc66069, 66f1717) form the complete evolution from v18.1's original Codex wrappers through Phase C's hardeners. No commit has touched compose-wiring from this file; the directive will be net-new.

---

## Section 1I — Test patterns to follow

### Scaffold verifier (Wave 2B must copy)

- `tests/test_scaffold_verifier_post_scaffold.py:23` — `test_verifier_call_appears_after_save_wave_artifact_scaffold` — AST-inspects `wave_executor.py` to assert call-site ordering; pattern for guarding "this hook must be AFTER that hook".
- `tests/test_scaffold_verifier_post_scaffold.py:68` — `test_scaffold_verifier_fail_uses_scaffold_error_wave` — asserts `result.error_wave == "SCAFFOLD"` when verifier fails; pattern for the `OWN-*` findings that flip `result.success`.
- `tests/test_scaffold_verifier_scope.py:60` — `test_scope_aware_filters_m2_m5_rows` — fixture pattern for building a minimal `OwnershipContract` in-test via `_contract([(path, owner, optional), ...])` (helper at `:34-41`); copy this shape verbatim for ownership-enforcer unit tests.
- `tests/test_scaffold_verifier_scope.py:117` — `test_scope_aware_still_flags_in_scope_missing` — fixture pattern for writing a minimal foundation workspace (`_m1_foundation_files` at `:44-52`) and asserting report verdict + summary-line substring.

### Endpoint prober (Wave 2B / 2C must copy)

- `tests/test_endpoint_prober.py:25` — `test_detect_from_config_browser_testing_app_port_still_wins` — precedence chain assertion pattern; copy for DoD-port guard tests.
- `tests/test_endpoint_prober.py:72` — `test_precedence_env_example_beats_main_ts` — regression pattern for "new source must slot in at the right precedence level without breaking existing sources".
- `tests/test_endpoint_prober.py:90` — `test_fallback_warning_when_all_sources_fail` — caplog assertion pattern; use for DoD-drift WARNING emission tests.
- Fixture shape: `tmp_path` directly, minimal `_cfg(app_port=N)` helper at `:17-22`, `.write_text` on a fabricated project tree.

### Integration tests exercising the post-wave hook chain

- `tests/test_v18_wave_executor_extended.py:394` — `test_on_wave_complete_called_for_each_wave` — builds a full `execute_milestone_waves` invocation with minimal callback shims. Use this as the integration-test harness template for ownership-enforcer wiring tests. Fixture shape: `_run_waves(tmp_path, on_wave_complete=...)` helper near `:42-114` exposes all the callable stubs (`run_compile_check`, `execute_sdk_call`, `extract_artifacts`, `save_wave_state`, etc.).
- `tests/test_v18_wave_executor_extended.py:405` — `test_on_wave_complete_receives_wave_result` — asserts callback receives a real `WaveResult`; use this shape to assert the ownership-enforcer emits `WaveFinding`s with the right codes into `wave_result.findings`.
- `tests/test_scaffold_verifier_ordering.py:87` — `test_wave_a_verifier_does_not_fire_before_scaffolder` — AST pattern already in the repo for "this call-site must not appear in this block"; adapt for ownership-enforcer placement assertions.

---

## HALT items

**None.** All referenced files and functions exist at h1a HEAD. All line numbers independently verified by direct read in this discovery session (not copied from smoke #11 notes). `_docker_compose_template()` is externally importable (verified by executing a Python import). Ownership-enforcer pre-scaffold hook point = Wave A completion hook (`:4620-4627`); no new hook point needs to be created — no HALT on scope.

The only caveat worth surfacing (non-blocking): DoD-port oracle plumbing will require threading `milestone_id` through `_detect_app_url`'s callers at `endpoint_prober.py:707, 712, 725, 771, 796`. That's a non-trivial signature change — Wave 2C should plan for it explicitly rather than discovering it mid-implementation. Not a HALT; just a scope call-out.
