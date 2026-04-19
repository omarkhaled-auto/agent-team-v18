# Post-Gate-A Investigation Report

**Generated:** 2026-04-16, synthesized from verified code reads of `integration-2026-04-15-closeout` HEAD `8ed55a4` + pending `session-6-fixes-d02-d03` HEAD with commits `c1030bb` + `61dd64d`.
**Inputs:** `docs/plans/2026-04-16-handoff-post-gate-a-deep-investigation.md` + build-l preservation + Sessions 1–5 code.
**Mandate:** investigation only — no code changes, no builds, no PR merges, no memory updates.
**Scope:** verify every handoff claim, map 16 N-items to code, surface new issues.

---

## Executive Summary

- **Total issues investigated:** 17 N-items + 4 latent wirings + 10 new findings + 28 build-l findings + 10 root-cause claims + 5 feature flags.
- **Handoff claims verified TRUE:** 23/25 specific claims.
- **Handoff claims REFINED (partially correct):** 5 claims. Most important — **N-08 is not a new primitive**; the audit-fix loop (`_run_audit_loop`, `_run_audit_fix_unified`) is fully implemented at `cli.py:5843-6037` and IS wired at `cli.py:4782` (major correction in Appendix B).
- **Handoff claims REJECTED / corrected:** 2 claims. The 3-way port conflict framing is wrong (M1 REQUIREMENTS.md says `:4000`, not `:3001`); the "PRD expects `src/database`" claim is wrong (M1 REQUIREMENTS does, not the PRD).
- **New issues surfaced (not in handoff):** 10 — headlined by:
  - **NEW-9 Wave sub-agents have no direct MCP access** (structural — verified at `agents.py:5287-5290`). Root cause of ~8 Wave B LLM-bug findings. Addressed by **N-17** (orchestrator-side context7 pre-fetch) + **NEW-10 full Claude bidirectional migration**. Full analysis in **Appendix C**; SDK specs verified against Context7 docs in **Appendix D**.
  - **NEW-10 `ClaudeSDKClient` bidirectional features unused — COMMITTED to full migration** (3 sessions, ~490 LOC): (a) kill one-shot `query()` at `audit_agent.py:81, 294`, (b) eliminate `Task("sub-agent")` dispatch from enterprise-mode prompts — replace with Python-orchestrated multi-`ClaudeSDKClient` sessions each with full MCP access and `fork_session=True` for history inheritance, (c) wire `client.interrupt()` into wave watchdog for wedge recovery, (d) subscribe to streaming events for Claude-path orphan-tool detection. Mirrors codex Bug #20 on the Claude path. Every Claude agent gets MCP access after migration. See Appendix D for per-agent migration table.
  - Duplicate Prisma modules (`src/prisma/` + `src/database/` both populated in build-l).
  - Scaffold-vs-current-spec drift (scaffold emits `PORT=3001`; current M1 REQUIREMENTS says `:4000`).
  - Latent wirings in Wave T / Wave D.5 / post-Wave-E scanners / Codex transport.
- **Recommended priority:** close N-01 (port resolution) + validate N-08 (existing audit-fix loop via observability) + N-17 (MCP-informed dispatches) + N-02 ownership contract + PR #25 merge to unblock Gate A re-smoke. THEN complete the NEW-10 three-session Claude bidirectional migration so every agent uses ClaudeSDKClient with full MCP access. Bug #20 (codex app-server) runs in parallel for the codex path.

---

## Part 1: Closeout Verification

### 1A. Session 1 — Scope Enforcement (A-09 + C-01)

| Claim | Verified | Evidence |
|---|---|---|
| `files_outside_scope()` called in production | **YES** | `milestone_scope.py:375-385` (function); `wave_executor.py:3322` (production caller) |
| A-09 scope preamble fires for Wave B/D | **YES** | `milestone_scope.py:393-425` preamble; `apply_scope_if_enabled()` at `:487-504` checks `v18.milestone_scope_enforcement` (default True) |
| C-01 scope preamble in auditor prompts | **YES** | `audit_team.py:317-332` wraps prompts with `get_scoped_auditor_prompt()`; template at `audit_scope.py:109-140` |
| `AuditReport.scope: dict` field exists | **YES** | `audit_models.py:252` (field); `:278` (serialized in `to_json()`) |
| Commit `f23ddad` merged (A-09) | **YES** | 6 files, 1172 insertions (including `milestone_scope.py` new 515 LOC, `scope_filter.py` new 155 LOC) |
| Commit `73a9997` merged (C-01) | **YES** | 8 files, 920 insertions |
| **§3.4 latent bug — scope field absent from build-l AUDIT_REPORT.json** | **YES (confirmed)** | Direct read of `AUDIT_REPORT.json` shows NO `scope` key at top level; keys go straight from `summary` to `score_breakdown`. `AUDIT_REPORT_INTEGRATION.json` has `scope: {}` (empty). Prompt-level scoping still works (no M2-M6 over-scope findings in build-l) — only persistence is broken. |

**Scope-persistence write-path trace** (the latent bug):
1. Scorer LLM writes AUDIT_REPORT.json directly via SDK tool (no `scope` field).
2. `_run_milestone_audit` at `cli.py:5393-5405` reads the file via `AuditReport.from_json()` (scope=empty dict).
3. `_apply_evidence_gating_to_audit_report` at `cli.py:530-651` rebuilds via `build_report(..., scope=scope_payload)` — this populates scope IN MEMORY only.
4. The final write at `cli.py:6033` uses `current_report.to_json()` which serializes the scope field.
5. **Observed:** build-l's AUDIT_REPORT.json does NOT contain the scope field.
6. **Hypothesis:** either (a) build-l hit an exception path at `cli.py:607` or `:634` that silently set `scope_payload={}`, (b) the pipeline killed at Wave B meant step 3 never ran (evidence-gating skipped when wave failed before audit completed normally), or (c) a subsequent scorer write overwrote the patched file. **Given that build-l's audit DID run to completion with 28 findings**, (a) and (c) are more likely than (b).

### 1B. Session 2 — Scaffold + Infrastructure

All items in `scaffold_runner.py` emit the claimed template content. Verified per `run_scaffolding()` → `_scaffold_m1_foundation()`:

| Item | Claim | Verified | Location |
|---|---|---|---|
| A-01 docker-compose | postgres + healthcheck | **YES — but postgres-only, no api/web** | `scaffold_runner.py:559-583` |
| A-02 port 3001 | Joi.default(3001) | **YES — but spec drift: current M1 REQUIREMENTS says 4000** | `:698, :527` |
| A-03 Prisma shutdown | `enableShutdownHooks(app)` pattern, no `$on('beforeExit')` | **YES** | `:707-729` |
| A-04 i18n locales | en+ar, no `id` | **YES** | `:230, :244-246` |
| A-07 vitest devDeps | vitest 2.1, testing-library 16.1, jsdom 25 | **YES** | `:769-780, :787` |
| A-08 .gitignore + no .env | standard ignores, no `.env` emitted | **YES** | `:489-520` |
| D-18 npm audit pins | next 15.1, etc. | **YES** | `:746-784` |
| A-05 validation pipe | baseline (no custom) | **YES (investigation-only)** | `:804-831` |
| A-06 RTL baseline | no scaffold change | **YES (investigation-only)** | no template change |

**Scaffold gap map** (files the scaffold does NOT emit, matched to build-l AUDIT findings):
- `packages/shared/*` — none emitted (AUD-001 root cause)
- `apps/api/prisma/migrations/` — none emitted (AUD-005 root cause)
- `apps/api/.env.example` — only root `.env.example` emitted (AUD-006 root cause)
- `apps/web/.env.example` — only root `.env.example` emitted (AUD-006 root cause)
- docker-compose api + web services — only postgres emitted (AUD-007/008 root cause)
- `apps/web/src/app/layout.tsx`, `page.tsx`, `middleware.ts`, `test/setup.ts` — none emitted (AUD-002/022 root cause for the non-cascade portion)
- `turbo.json` — not emitted (AUD-025 root cause)
- `.editorconfig`, `.nvmrc` — not emitted (AUD-024 root cause)
- root `package.json` prisma scripts (`db:migrate`, `db:seed`) — not emitted (AUD-027 root cause)

### 1C. Session 3 — Audit Schema + State Finalization

| Claim | Verified | Evidence |
|---|---|---|
| D-07 permissive `from_json` | **YES** | `audit_models.py:283-381` with field aliasing |
| D-07 fix-up: `fix_candidates` string→int coercion | **YES** | `audit_models.py:344-361`; **silent drop confirmed** (list comprehension `if fid in id_to_idx`, no warning logged) |
| D-13 `State.finalize()` reconciles summary.success | **YES** | `state.py:97-210`; `summary.success = not interrupted and len(failed_milestones)==0` at `:135-137` |
| D-13 called reactively, not proactively | **YES (confirmed)** | Only ONE call site at `cli.py:13491` — final pass before save. **State mutations elsewhere do not validate invariants at write time.** |
| D-20 M1 startup-AC probe | **YES** | `m1_startup_probe.py:194-235` (5 probes); call site `cli.py:5414`; flag default True at `config.py:827` |

**§7.7 handoff claim confirmed:** D-13 would not have caught build-l's `summary.success=true / failed_milestones=["milestone-1"]` inconsistency at the write site. The kill-at-Wave-B scenario means finalize never ran. A proactive, write-time invariant check is absent.

### 1D. Session 4 — Orchestration + Recovery

| Claim | Verified | Evidence |
|---|---|---|
| D-04 review-fleet invariant (raise vs warn) | **YES** | `cli.py:8641-8685`; raises `ReviewFleetNotDeployedError` at `:8682` when flag True + invariant violated |
| D-05 recovery prompt role isolation | **YES** | `cli.py:8688-8800`; system channel carries framing, user channel carries task only |
| D-06 recovery taxonomy | **YES (scale refined)** | `display.py:625-657`; **28 recovery types total** (not "8 beyond debug_fleet" — the handoff's phrasing was ambiguous; verified 28 documented hints) |
| D-08 CONTRACTS.json primary producer deterministic | **YES** | `cli.py:8522-8627`; orchestrator-produced path takes precedence (`:8559-8567`), then static-analysis (`:8568-8580`), then LLM recovery (`:8588-8626`) |
| D-11 WAVE_FINDINGS.json unconditional | **YES** | `wave_executor.py:576-648` (writer); call sites `:3033` and `:3548` — no `if wave_t_ran` guards |

### 1E. Session 5 — Runtime Toolchain + PR #25

| Claim | Verified | Evidence |
|---|---|---|
| D-02 v1 `blocked` vs `skipped` (distinct strings) | **YES** | `runtime_verification.py:980,989,1008,1017`; consumer at `cli.py:12759` treats any value not in `("passed","skipped")` as failure → appends recovery type |
| D-02 v2 `infra_missing` flag (PR #25) | **YES** | `endpoint_prober.py:119` (field); `:704, :716` (setters); wave_executor branching at `:1640-1648` |
| D-02 v2 host-port diagnostic | **YES** | `endpoint_prober.py:891-1000` (`_detect_unbound_host_ports()`) |
| **§3.1 claim: no explicit RuntimeBlockedError at consumer** | **CONFIRMED** | Blocking is implicit — the skip-vs-block DECISION is explicit (`:1640-1648`), but the consumer at `cli.py:12759` treats "blocked" via the same generic recovery-append pattern. No legible halt diagnostic. |
| D-03 v1 (Windows launcher) | **YES** | merged in PR #23 |
| D-03 v2 workspace-walk local-bin | **YES** | `openapi_generator.py:268-307` (`_resolve_local_bin()`); 23 regression tests |
| **§3.2 claim: D-09 helpers zero production callers** | **CONFIRMED** | `run_mcp_preflight` (`mcp_servers.py:429-482`) and `ensure_contract_e2e_fidelity_header` (`:485-523`) — both have test-only callers. Full grep: only `tests/test_mcp_preflight.py` imports them. |
| PR #25 merged | **NO** | Branch `session-6-fixes-d02-d03` ahead of master by commits `c1030bb` + `61dd64d`. Master at `89f460b`. Not yet reviewed/merged. |

---

## Part 2: Build-L Findings Catalogue

All 28 findings verified against `.agent-team/AUDIT_REPORT.json`. Severity counts match handoff exactly (5C/12H/8M/3L). `fix_candidates` is populated with string IDs (25 entries — excludes AUD-015, AUD-024, AUD-025, the three LOW). `scope` field absent from primary JSON.

### 2A. Critical (5) — all verified

| ID | Category | Root-cause (handoff) | Agreement | N-item |
|---|---|---|---|---|
| AUD-001 | interface | Scaffold gap (packages/) | **AGREE** | N-03 |
| AUD-002 | interface | Cascade (Wave D never ran) | **REFINE** — part-cascade, part-scaffold-gap: Wave D didn't run but scaffold also doesn't emit layout/page/middleware stubs | N-01 + N-06 |
| AUD-005 | completeness | Scaffold gap (no migrations dir) | **AGREE** | N-05 |
| AUD-021 | infrastructure | Primary — port mismatch | **AGREE, framing refined** — not "3-way mismatch" but prober hardcoded :3080 vs spec+Wave-B :4000 | N-01 |
| AUD-028 | completeness | Meta-finding | **AGREE** | resolved by N-01+02+03+05+06+07 stack |

### 2B. High (12) — all verified

Per-ID attribution: AUD-003/004 (cascade — Wave D), AUD-006 (scaffold gap + ownership question), AUD-007/008 (scaffold gap docker-compose services), AUD-009/010/012/020 (Wave B LLM bugs), AUD-011 (**new: DUPLICATE** — see Part 7), AUD-022 (scaffold gap + cascade), AUD-026 (cascade — Wave T blocked).

### 2C. Medium/Low (11) — all verified

All match handoff attribution. AUD-017 (Joi defaults) is a spec drift between scaffold's `.default(3001)` and current M1 REQUIREMENTS' port 4000 DoD — **AUD-017 is actually about port 4000 NOT being declared in scaffold**, because Wave B regenerated env.validation.ts to `.default(4000)` but used `.default` instead of `.required()`.

### 2D. Handoff Taxonomy Collapse — Refined

The handoff's 28→17 actionable-distinct collapse is broadly correct but misattributes AUD-011 and under-counts AUD-002.

| Class | Handoff count | Refined count | Notes |
|---|---|---|---|
| Cascade | 5 | 4 | AUD-002 is half-cascade/half-scaffold; AUD-003 / AUD-004 / AUD-022 / AUD-026 are pure cascade |
| Scaffold gap | 9 | 10 | Add AUD-002 web scaffold minimum stubs |
| Wave B LLM bug | 8 | 7 | AUD-011 reframed as DUPLICATE (both locations exist), not pure Wave B |
| Primary infra | 1 | 1 | AUD-021 |
| Spec conflict | 2 | 3 | AUD-011 (src/prisma vs src/database — ambiguity from scaffold 3001-era baking), AUD-017 (Joi default vs required) — third is the **AUD-002/AUD-005 scaffold-vs-M1-REQUIREMENTS drift** |
| Meta | 1 | 1 | AUD-028 |
| Ownership | 1 | 2 | Add AUD-019 Dockerfile |

**Actionable-distinct count:** ~18 (not 17). The additional one is the AUD-011 duplicate-module finding (see Part 7.A).

### 2E. Findings the Handoff Missed (patterns)

1. **AUD-011 framing is wrong — it's not "moved to wrong location," it's a DUPLICATE.** Build-l has BOTH `apps/api/src/prisma/` AND `apps/api/src/database/` populated with full `prisma.module.ts` + `prisma.service.ts`. The `app.module.ts` imports from `./database/`, but `test/health.e2e-spec.ts` imports from `../src/prisma/`. Wave B or scaffold left orphaned duplicate files. This is a Wave-B output-sanitization gap.
2. **Scaffold-vs-spec drift cluster.** Scaffold emits PORT=3001, M1 REQUIREMENTS now specifies PORT=4000 (DoD line 568). Scaffold's `src/prisma` was the old spec; current M1 REQUIREMENTS says `src/database`. These drifts predate build-l; the tracker A-02's 3001 target was based on a stale M1 REQUIREMENTS.
3. **Web scaffold is below minimum viable.** AUD-022 is catalogued as scaffold gap for `vitest.setup.ts` only, but AUD-002 lists `next.config.mjs, tsconfig.json, postcss.config.mjs, layout.tsx, page.tsx, middleware.ts, src/lib/api/client.ts, src/test/setup.ts` — none of which scaffold emits. This is a larger scaffold gap than "web vitest setup."
4. **i18n / UI_DESIGN_TOKENS / stack_contract conspicuously absent from findings.** M1 REQUIREMENTS lists i18n/RTL as Day-1 requirements; UI_DESIGN_TOKENS.json is generated. No finding audits token usage or i18n wiring. This may be M1-scope-correct (deferred to M6) but worth flagging — the auditor could silently pass incorrect content if it's out of scope.
5. **Wave T cascade captured, Wave D cascade not.** AUD-026 surfaces Wave T-skipped as a distinct finding; no corresponding "Wave D skipped → packages/api-client absent" finding. Cascade detection is partial.

---

## Part 3: Root-Cause Analysis Verification (§5)

### 3A. §5.1 Three-Layer Ownership — **AGREE, scope bigger than handoff suggests**

- Scaffold emits ~20 files for M1.
- M1 REQUIREMENTS lists **62 files** under "Files to Create."
- Wave B produced ~43 new files in build-l (per handoff).
- Wave D produced 0 (never ran).
- Auditor's expectation set = all 62 from REQUIREMENTS.
- **Gaps:** ~19 files are in REQUIREMENTS but emitted by NEITHER scaffold nor Wave B (web app pages, middleware, openapi-ts config, packages/shared/*, packages/api-client/*, prisma/migrations/, per-app .env.example, root config files).

See Part 6.A for the full ownership table.

### 3B. §5.2 Spec Ambiguity — **REJECT the 3-way framing; reframe as spec drift + prober isolation**

Handoff framing: "M1 REQUIREMENTS.md `:3001` + Session 2 A-02 scaffold `:3001`; PRD `:4000`; prober `:3080`."

**Corrections:**
- Build-l's M1 REQUIREMENTS.md **explicitly says port 4000** (DoD line 568: `http://localhost:4000/api/health`). Docker-compose template line 411 also says 4000.
- Tracker item A-02 target was 3001, citing an older M1 REQUIREMENTS.md — spec has drifted; scaffold bakes the older target.
- PRD doesn't explicitly declare a port; it only says "NestJS backend" (implicit 4000 from M1 REQUIREMENTS's DoD).
- Wave B regenerated env.validation.ts with `.default(4000)` to match the current M1 REQUIREMENTS (correctly).
- Prober's `:3080` hardcoded default is unrelated to any spec — it's a legacy from an even earlier TaskFlow version.

**Real conflict classes:**
1. **Scaffold baked a stale target** (PORT=3001, Prisma `src/prisma`) — scaffold predates the current M1 REQUIREMENTS.
2. **Prober has no awareness of any spec** — hardcoded `:3080`.
3. **Spec-wide consistency is non-determinstic** — M1 REQUIREMENTS is regenerated per run from PRD; the scaffold templates are frozen.

This is a BIGGER problem than spec ambiguity: it's **spec-template desynchronization**. The scaffold is not a spec consumer; it's a template that codifies assumptions that were true at scaffold-authoring time.

### 3C. §5.3 No Audit-Fix Iteration Loop — **REFINE: the loop IS implemented, but NOT wired**

**Critical finding:** the handoff says "a new pipeline phase `audit_fix_iteration` is needed." Actually:
- `_run_audit_loop` at `cli.py:5843-6037` — full cycle logic: run audit → compute reaudit scope → call `_run_audit_fix_unified` → re-audit → plateau/regression/max-cycles check.
- `_run_audit_fix_unified` at `cli.py:5605-5700+` — converts audit findings to `Finding` objects, calls `execute_unified_fix_async`.
- `execute_unified_fix_async` at `fix_executor.py:312-389` — coordinates patch-vs-full dispatch.
- `group_findings_into_fix_tasks` at `audit_models.py:762-806` — primary file grouping + 5-findings-per-task chunks.

**BUT:** `_run_audit_loop` is NOT called from the main milestone orchestration path. Build-l's `FIX_CYCLE_LOG.md` is empty (header only). No "fix_cycle" keyword in BUILD_LOG.txt.

**The real N-08 is wiring, not construction.** Estimated ~50 LOC to wire the existing loop into the milestone audit sequence with a feature flag + per-cycle budget guard.

### 3D. §5.4 No Content-Level Scope Enforcement — **AGREE**

`files_outside_scope()` at `milestone_scope.py:375-385` operates on file paths only (glob matching). Content-level checks are absent. M1 REQUIREMENTS does NOT contain explicit `forbidden_content` directives in a structured format (it has prose like "no feature business logic" but no regex/AST patterns).

Build-l evidence: Wave B's output for M1 is narrowly scoped (no feature pages, no task/comment business logic leaked into files). So the theoretical concern did not materialize in build-l. The risk is real for future milestones.

### 3E. §5.5 Scaffold Doesn't Self-Verify — **AGREE**

Trace: `scaffold_runner.run_scaffolding()` → no validation step → Wave B dispatched. If scaffold emits invalid `package.json` workspace globs or broken `docker-compose.yml`, it surfaces only at Wave B compile-fix or probing. No prior fail-fast gate.

Build-l evidence: the PORT=3001 scaffold vs PORT=4000 spec would have been caught by a simple "scaffold output matches `.agent-team/milestones/milestone-1/REQUIREMENTS.md` key values" gate.

### 3F. §5.6 `endpoint_prober._detect_app_url` Hardcoded — **AGREE, verified in detail**

`endpoint_prober.py:1023-1036`:
```python
def _detect_app_url(project_root: Path, config: Any) -> str:
    port = getattr(getattr(config, "browser_testing", None), "app_port", 0) if config else 0
    if port:
        return f"http://localhost:{int(port)}"
    env_path = project_root / ".env"
    if env_path.is_file():
        ...regex match PORT=<n>...
    return "http://localhost:3080"  # hardcoded
```

Reads: `config.browser_testing.app_port`, then root `.env`, then returns `:3080`. Does NOT read: `apps/api/.env.example`, `apps/api/package.json` scripts, `apps/api/src/main.ts` AST, `docker-compose.yml` port mappings. Build-l had a correct `apps/api/.env.example` with `PORT=4000` — prober ignored it.

### 3G. §5.7 Partial Wiring — **AGREE, list extended**

The handoff names 4 partial-wiring instances (§3.1 D-02 v2 consumer, §3.2 D-09 MCP preflight, §3.3 D-14 fidelity labels, §3.4 C-01 scope persistence). Verified all 4 plus found MORE:
- **Wave T** — mechanism exists (`wave_executor.py:1747`), has never successfully executed in any build artifact.
- **Post-Wave-E scanners** (WIRING-CLIENT-001, I18N-HARDCODED-001, DTO-PROP-001, DTO-CASE-001, CONTRACT-FIELD-001/002) — wired at `wave_executor.py:2957-2960`, never triggered in production because no build has reached Wave E.
- **Wave D.5 design-tokens consumption** — `agents.py:8581-8591` loads tokens, never executed in production.
- **Codex transport** (`codex_transport.py`, 760 LOC) — zero successful production executions.
- **`_run_audit_loop` / `_run_audit_fix_unified`** — full audit-fix iteration implemented, not invoked by main orchestration.

**Systemic pattern:** Sessions 1–5 added mechanisms with unit tests; the production-caller-proof artifact (Session 1's practice) was dropped in later sessions. The handoff's §5.7 identifies this exactly.

### 3H. §5.8 `fix_candidates` Flows Nowhere — **AGREE, with correction from §5.3**

The infrastructure exists; the dispatch ENTRY POINT from the main orchestration is missing. Build-l's AUDIT_REPORT.json has 25 IDs in `fix_candidates` (all CRITICAL/HIGH/MEDIUM). If the loop were wired, those 25 would be dispatchable.

### 3H-BIS. §5.10 MCP-blind wave execution (NEW root cause) — **SURFACED**

Structural root cause behind the 7–8 Wave B LLM-bug findings not named in the handoff. Verified at `agents.py:5287-5290`: "MCP servers are only available at the orchestrator level and are not propagated to sub-agents." Wave B's code-writer sub-agent has no direct `mcp__context7__*` access; the Wave B top-level prompt at `agents.py:7879-8049` never invokes context7 at prompt-build time to fetch current NestJS 11 / Prisma 5 / Next.js 15 idioms. Model generates code from training-data approximations. See **Appendix C** for full analysis and the new tracker item **N-17**.

### 3I. §5.9 Stock PRD Mismatch — **REFINE: PRD doesn't conflict; M1 REQUIREMENTS has drifted from scaffold templates**

The stock PRD (TASKFLOW_MINI_PRD.md) is multi-milestone and does NOT specify `:4000` or `src/database` explicitly. The conflicts the handoff lists are between **build-l's regenerated M1 REQUIREMENTS.md** and **scaffold_runner.py's frozen templates**. The PRD is a spec consumer, not a source of the conflict.

True statement: the scaffold `PORT=3001` and `src/prisma` predate the current M1 REQUIREMENTS; the regenerator has drifted.

---

## Part 4: N-Item Detailed Cards

### N-01 — `endpoint_prober._detect_app_url` (CRITICAL, Gate A blocker)

- **File:** `endpoint_prober.py:1023-1036`
- **Current behavior:** reads `config.browser_testing.app_port`, root `.env`, falls back `:3080`.
- **Fix:** add reads for `apps/api/.env.example` (PORT=<n>), `apps/api/src/main.ts` regex `app\.listen\s*\(\s*(\d+)`, `docker-compose.yml` `services.api.ports` mapping. ~35 LOC. Simple regex sufficient; AST parsing not needed.
- **Dependencies:** none. Standalone. Unit-testable by writing tmpdir fixtures.
- **Risk:** LOW. Narrow file, read-only detection. Legacy `:3080` fallback can remain as last resort with loud warning.
- **Tests exist?** One test at `tests/test_endpoint_prober.py` covers config.app_port. Need to add 4 new tests for the additional sources.

### N-02 — Three-Layer Ownership Contract (HIGH)

- **Current state:** no existing ownership doc; no single canonical list. Ownership is implicit.
- **`ownership_validator.py`** exists in src but is about runtime ownership validation of contract-engine outputs, not file-layer ownership.
- **Fix:** create `docs/SCAFFOLD_OWNERSHIP.md` (YAML-ish table): for every file in REQUIREMENTS, explicit owner (scaffold | wave-b | wave-d | wave-c-generator | audit-optional). Then:
  - Scaffold reads this table and emits its assigned files.
  - Wave B/D prompt builder reads assigned subset and prompt-injects "your files to create."
  - Auditor reads the table and suppresses "missing file" findings for files marked `optional` or `deferred-to-M2+`.
- **Scope:** L. ~150 LOC (new parser + 3 consumer updates) + ~50-line ownership doc + schema validation test.
- **Dependencies:** touches scaffold_runner.py, wave_executor.py/codex_prompts.py, audit_prompts.py. Three consumers.
- **Risk:** MEDIUM — cross-layer change. Introduces a new source-of-truth document.

### N-03 — `packages/shared` Scaffold Emission (HIGH)

- **Current state:** scaffold emits zero packages/ content. Wave B overbuilt some types into `apps/api/src/common/dto/pagination.dto.ts`.
- **M1 REQUIREMENTS lines 546-552:** `packages/shared/{package.json, tsconfig.json, src/{enums,error-codes,pagination,index}.ts}`.
- **Fix:** extend `_scaffold_m1_foundation` with a new `_scaffold_packages_shared()` method emitting package.json, tsconfig.json, and baseline `src/enums.ts`, `src/error-codes.ts`, `src/pagination.ts` with the exact constants from M1 REQUIREMENTS (UserRole, ProjectStatus, TaskStatus, TaskPriority, ErrorCodes map of 11 keys, PaginationMeta, PaginatedResult<T>).
- **Scope:** S–M. ~120 LOC + test.
- **Dependencies:** none. Also add to tsconfig.base.json paths + pnpm-workspace.yaml include.
- **Risk:** LOW. Scaffold-only.

### N-04 — Prisma Location Reconciliation (HIGH)

- **Current state:** scaffold emits `apps/api/src/prisma/prisma.{module,service}.ts`. M1 REQUIREMENTS lines 516-517 say `src/database/`. Wave B ended up writing to BOTH locations in build-l (see Part 7.A).
- **Fix:** change scaffold template path from `src/prisma/` to `src/database/`. Update Wave B prompt reminder if needed.
- **Scope:** S. ~20 LOC + spec file path update + test.
- **Dependencies:** none, but depends on spec decision (database is M1 REQUIREMENTS' canonical choice).
- **Risk:** LOW.

### N-05 — Prisma Initial Migration Scaffold (HIGH)

- **Current state:** scaffold emits `schema.prisma` (in Wave A). No `apps/api/prisma/migrations/` directory, no `migration_lock.toml`, no `<timestamp>_init/migration.sql`.
- **M1 REQUIREMENTS line 266-269** requires initial migration.
- **Fix:** either (a) scaffold template emits a canned `migrations/20260101000000_init/migration.sql` + `migration_lock.toml`, or (b) scaffold invokes `prisma migrate dev --name init` via subprocess against a temporary local postgres.
- **Recommendation:** (a) — canned stub avoids runtime dependency on postgres at scaffold time.
- **Scope:** S. ~40 LOC + test.
- **Dependencies:** schema.prisma must exist before migration emission; sequencing in scaffold already correct.

### N-06 — Web Scaffold Completeness (HIGH)

- **Current state:** scaffold emits `package.json`, `vitest.config.ts`, `tailwind.config.ts`, `styles/globals.css`, `eslint.config.js` for `apps/web/`. Missing: `next.config.mjs`, `tsconfig.json`, `postcss.config.mjs`, `openapi-ts.config.ts`, `.env.example`, `Dockerfile`, `src/app/layout.tsx`, `src/app/page.tsx`, `src/middleware.ts`, `src/lib/api/client.ts`, `src/test/setup.ts`.
- **M1 REQUIREMENTS lines 530-544** expects all 11.
- **Fix:** extend `_scaffold_web_foundation` with 11 new template emissions.
- **Scope:** M. ~200 LOC + tests (one per emitted file).
- **Dependencies:** overlaps with N-02 (ownership assigns each explicitly to scaffold).
- **Risk:** LOW.

### N-07 — Full Docker-Compose Scaffold (HIGH)

- **Current state:** `_docker_compose_template` (scaffold_runner.py:559-583) emits postgres only.
- **Fix:** add `api` service (build context apps/api, ports 4000:4000, env bindings, volumes `./apps/api/src:/app/src` + `/app/node_modules`, `depends_on: postgres`, healthcheck `curl -f http://localhost:4000/api/health || exit 1`) and `web` service (build context apps/web, ports 3000:3000, env NEXT_PUBLIC_API_URL + INTERNAL_API_URL, `depends_on: api`).
- **Scope:** M. ~120 LOC (template) + ~50 LOC test.
- **Dependencies:** depends on N-02 ownership decision (scaffold owns all three services vs. scaffold emits postgres only + Wave B extends).
- **Risk:** LOW.

### N-08 — Audit-Fix Iteration Loop (CRITICAL)

- **Critical reframe:** the loop EXISTS at `cli.py:5843-6037` (`_run_audit_loop`). It's NOT called from the main milestone orchestration path. Build-l's `FIX_CYCLE_LOG.md` is empty.
- **Existing pieces:**
  - `_run_audit_loop(self, ...)` at `cli.py:5843` — full cycle: run audit → compute scope → dispatch fixes → re-audit → plateau/regression check.
  - `_run_audit_fix_unified` at `cli.py:5605` — dispatcher.
  - `execute_unified_fix_async` at `fix_executor.py:312`.
  - `group_findings_into_fix_tasks` at `audit_models.py:762`.
  - `FixTask` dataclass at `audit_models.py:533-544`.
- **Fix shape:** add call site in the milestone completion path (search for `_run_milestone_audit` completion in coordinated_builder.py or cli.py) that enters `_run_audit_loop` when `v18.audit_fix_iteration: bool = False` is flipped True. Already-implemented budget guard at `cli.py:5931-5937` (30% audit budget cap).
- **Scope:** S–M (wiring, not construction). ~50 LOC wiring + new flag + end-to-end test.
- **Dependencies:** none. (`_run_audit_loop` is self-contained with budget guard.)
- **Risk:** MEDIUM — spawns sub-agents, touches budget accounting. Starting flag-off avoids regressing current behavior.
- **Huge ROI:** immediately closes ~8-10 of build-l's Wave B LLM bug findings per cycle. Real iteration was an engineering oversight, not an architectural gap.

### N-09 — Wave B Prompt Quality Uplift (MEDIUM)

- **Current state:** Wave B prompt is constructed in `codex_prompts.py` (codex) and / or `wave_executor.py` prompt builders (Claude). It includes the A-09 milestone scope preamble. The 8 build-l Wave B LLM bugs (AUD-009, -010, -012, -013, -014 partial, -016, -018, -020) indicate specific gaps.
- **Per-bug analysis (to inform fix):**
  - AUD-009 duplicate `AllExceptionsFilter` — prompt allows ambiguity: does not explicitly say "register globally OR via APP_FILTER, not both."
  - AUD-010 `getOrThrow` vs `.get` — spec stresses `.get`, model chose stricter variant; prompt weakness.
  - AUD-012 bcrypt missing — spec stresses "JWT module shell, no strategies," auditor expects bcrypt anyway (audit-spec drift).
  - AUD-013 bare strings vs ErrorCodes — prompt doesn't require ErrorCodes import.
  - AUD-016 Swagger Object typing — pattern not idiomatic NestJS; model used generic.
  - AUD-018 generate-openapi.ts globals — prompt doesn't stress reusing global wiring.
  - AUD-020 URL-prefix skip vs decorator — model chose simpler pattern.
  - AUD-023 PrismaService mock in e2e — prompt doesn't require real DB integration.
- **Context7 integration:** `mcp_clients.py` has context7 client; `codex_context7_enabled` flag default True. But the prompt builder doesn't actively query context7 at prompt-build time.
- **Fix:** add ~8 prompt hardeners for the above patterns; optionally add context7-query-at-prompt-build for NestJS 11 idioms.
- **Scope:** M. ~100 LOC prompt edits + investigation notes.
- **Risk:** MEDIUM — prompt changes affect every wave in every build.

### N-10 — Post-Wave Content Auditor (MEDIUM)

- **Current deterministic scanners** in `quality_checks.py`: WIRING-CLIENT-001, I18N-HARDCODED-001, DTO-PROP-001, DTO-CASE-001, CONTRACT-FIELD-001/002 (all post-Wave-E).
- **M1 REQUIREMENTS content directives:** prose-only ("no feature business logic"). No structured `forbidden_content` section.
- **Fix:** add `forbidden_content: list[regex_pattern]` to milestone REQUIREMENTS generator; extend post-wave validator at `wave_executor.py` (near line 3318 where A-09 scope check fires) to also run content-scan. Scope violations become warnings on WaveResult.
- **Scope:** M. ~150 LOC + REQUIREMENTS generator update + tests.
- **Risk:** LOW — read-only scan.

### N-11 — Cascade Finding Suppression (LOW)

- **Current state:** auditor reads `.agent-team/AUDIT_REPORT.json` evidence; it has access to `state.wave_progress` via `STATE.json` but doesn't use it. The auditor flags "Wave T skipped" as a distinct finding (AUD-026) rather than rolling up to a single upstream-cascade meta-finding.
- **Fix:** in `_apply_evidence_gating_to_audit_report` at `cli.py:530-651`, inject wave_progress state into scope_payload; filter findings whose "location" targets a skipped-wave's expected output. Emit single meta-finding "Upstream Wave B failure cascaded to downstream waves."
- **Scope:** S. ~40 LOC + test.
- **Risk:** LOW.

### N-12 — Unified Milestone SPEC.md Reconciliation (MEDIUM)

- **Current state:** M1 REQUIREMENTS.md is regenerated per run from PRD. Scaffold uses frozen templates (baked assumptions from an older REQUIREMENTS era). No reconciliation phase.
- **Fix:** at milestone entry, deterministic merger produces `.agent-team/milestones/<id>/SPEC.md` combining M1 REQUIREMENTS.md + relevant PRD excerpts + stack-contract derivations. Scaffold + Wave prompts + auditor all read from this.
- **Scope:** L. ~200 LOC new reconciliation agent + consumer updates in 3+ places.
- **Risk:** MEDIUM — new pipeline phase.

### N-13 — Scaffold Self-Verification Gate (MEDIUM)

- **Current state:** no gate between `run_scaffolding()` and Wave B dispatch. `json.loads`, `yaml.safe_load` already available (imports in scaffold_runner.py). Prisma parser not obvious.
- **Fix:** after scaffold emission, validate:
  - `package.json` valid JSON; `workspaces` globs resolve to emitted dirs.
  - `tsconfig.base.json` paths resolve.
  - `docker-compose.yml` valid YAML; services reference buildable contexts.
  - `prisma/schema.prisma` parseable (can invoke `pnpm prisma validate` as subprocess).
  - Port consistency across scaffold emissions (env.validation.ts PORT == docker-compose api PORT == .env.example PORT == M1 REQUIREMENTS DoD port).
- **Scope:** M. ~120 LOC + tests.
- **Risk:** LOW — read-only validation.

### N-14 — Production-Caller Proof Per Session (LOW, process)

- **Current state:** `v18 test runs/session-01-validation/` has a "M1 Wave D prompt capture" — the Session 1 practice. `session-02-validation/` onwards dropped it.
- **Fix:** per-session execute file requires a small script that mocks the SDK, walks the production call chain, asserts the feature fires. Add as a template.
- **Scope:** XS (process).
- **Risk:** NONE.

### N-15 — C-01 Scope Persistence in AUDIT_REPORT.json (MEDIUM)

- **Current state:** `cli.py:530-651` builds scope_payload and calls `build_report(scope=scope_payload)`. `audit_models.py:252` stores the field. `:278` serializes it. **Build-l's AUDIT_REPORT.json does not contain the field.**
- **Diagnosis candidates:**
  1. Exception silenced at `cli.py:607` (MASTER_PLAN.json or REQUIREMENTS.md read fail) → scope_payload stays `{}`.
  2. Exception silenced at `cli.py:634` (partitioning fail) → scope_payload stays `{}`.
  3. Final `to_json()` write is never reached because pipeline killed before audit persistence.
- **Fix:** investigate by adding log statements around `cli.py:607, :634, :6033`; OR re-run audit path against build-l's preserved state (offline replay) to localize. Then patch.
- **Scope:** S. ~40 LOC fix + test that unit-validates AUDIT_REPORT.json has scope field after `_apply_evidence_gating_to_audit_report`.
- **Risk:** LOW.

### N-17 — MCP-Informed Wave Dispatches (MEDIUM, structural)

- **Problem:** Wave B/D generate code blind to current-framework idioms. Orchestrator has `context7` MCP access; sub-agents dispatched via `Task()` do not (per `agents.py:5287-5290`). Wave B prompt at `agents.py:7879` never injects context7 responses.
- **Evidence:** 7–8 of build-l's 28 findings (AUD-009 duplicate filter, AUD-010 getOrThrow vs .get, AUD-012 bcrypt dep, AUD-013 bare strings vs ErrorCodes, AUD-016 Object @ApiProperty, AUD-018 generate-openapi globals, AUD-020 URL-prefix skip) are exactly the patterns context7 would correct.
- **Fix shape A (recommended):** at orchestrator layer, before `_execute_single_wave_sdk` is called for Wave B/D, call `mcp__context7__query-docs` for NestJS 11 + Prisma 5 + Next.js 15 idioms (milestone-template-aware query set). Inject returned docs into the Wave B/D prompt as `[CURRENT FRAMEWORK IDIOMS]` section BEFORE the task manifest.
- **Fix shape B (structural, COMMITTED via NEW-10 migration):** verified via Context7 SDK docs (see Appendix D §D.2) — Claude Agent SDK supports `query(resume=session_id, fork_session=True, options=ClaudeAgentOptions(mcp_servers=...))`. Forked sessions inherit parent conversation history but take FRESH options including MCP servers. This is exactly the primitive needed. Now folded into NEW-10 Step 2 (Session 17): eliminate `Task("sub-agent")` dispatch; spawn per-agent `ClaudeSDKClient` sessions via `fork_session=True` with full MCP.
- **Fix shape C (not viable):** per-sub-agent `mcp_servers` configured on the agents-dict entries — SDK doesn't support this shape.
- **Scope:** M. ~100 LOC (Fix A orchestrator pre-fetch + prompt injection + tests). Cache responses for reproducibility.
- **Dependencies:** none for Fix A. Bridges to N-09 (prompt quality uplift) — together they close the 8-finding Wave B LLM-bug cluster.
- **Risk:** LOW (pre-dispatch data injection, doesn't touch wave execution semantics).
- **Full analysis:** Appendix C.

### N-16 — Stock PRD Alignment (LOW, doc-only)

- **Current state:** stock `v18 test runs/TASKFLOW_MINI_PRD.md` is multi-milestone. Handoff's §5.9 claim that PRD conflicts with M1 REQUIREMENTS is **REJECTED** — the PRD doesn't explicitly specify port/Prisma location. The conflict is scaffold-template vs regenerated REQUIREMENTS.
- **Fix:** either (a) create `M1_ONLY_SMOKE_PRD.md` with explicit port=4000 and scope restricted to infrastructure, or (b) leave stock PRD as is and fix the upstream spec-drift (N-04, N-12).
- **Recommendation:** (b) — don't proliferate PRDs; fix the drift.
- **Scope:** XS (doc).

---

## Part 5: One-Shot Enterprise Gaps (§7)

### §7.1 Closed-Loop Verification → N-08

- Overlaps exactly with N-08.
- Calibration data available from build-l + build-j: 28 + 41 findings, 8 Wave B LLM bugs per run, average fix success rate unknown (no iteration has been run).
- **Next step:** once N-08 is wired, the first flagged-on smoke will produce calibration numbers.

### §7.2 Spec Reconciliation → N-12 + additional

- N-12 covers the reconciliation phase.
- Additional: human-arbitration path for ambiguous cases. Could be simple: emit a RECONCILIATION_CONFLICTS.md, halt pipeline with `reconciliation_arbitration_required` recovery type, wait for reviewer input.

### §7.3 File Ownership Contract → N-02

- N-02 = doc + enforcement.
- Enforcement mechanism: auditor reads ownership table; scaffold reads; Wave prompts read. Single source.

### §7.4 Content-Level Scope → N-10

- N-10 with `forbidden_content` regex/decorator lists in REQUIREMENTS.
- Keep scope narrow (start with forbidden regex list; no AST needed initially).

### §7.5 Runtime Infrastructure Auto-Detection → N-01 + broader

- N-01 is port-specific. Broader: extend to CORS origins, JWT audience, DATABASE_URL, API prefix.
- **Inventory of "config values consumed by downstream tools":**
  - Port (N-01)
  - API prefix (`app.setGlobalPrefix('api')` — currently stable at 'api')
  - CORS origin (CORS_ORIGIN env var — read by main.ts)
  - JWT audience (not currently used in M1)
  - DATABASE_URL (postgres+scaffold agree)
- Most are stable; port is the primary drift target.

### §7.6 Prompt Quality Baseline → N-09 + **N-17**

- N-09 with context7 lookups at prompt-build time → **now split into two tracker items:**
  - **N-17 (structural data source):** orchestrator-side context7 pre-fetch + prompt injection. Handles the MCP-blindness architectural constraint (see Appendix C). This is the structural root cause handoff §5.6 hinted at but didn't trace.
  - **N-09 (prompt hardeners):** text-level patches for patterns context7 doesn't resolve directly (e.g., audit-vs-spec disagreements about bcrypt scope at AUD-012).
- Place to inject: N-17 at orchestrator (`_run_milestone_waves` or wrapper before `_execute_single_wave_sdk` at `cli.py:3350`); N-09 at `build_wave_b_prompt` (`agents.py:7879`).

### §7.7 Truthful State

- Beyond D-13 reactive finalize: proactive write-side invariants.
- Fix: `State.update_milestone_status` and sibling setters validate invariants before save. `state.summary.success = True` must recompute from `failed_milestones` at write time, not just at finalize.
- **New tracker item N-17 recommended:** State write-side invariant validation. S, ~60 LOC.

### §7.8 Per-Family Budget Protection

- Current: global `max_budget_usd` + 30% audit budget cap at `cli.py:5899`.
- Gap: per-fix-agent-family cap (e.g., audit_fix_iteration gets max $5 per milestone regardless of finding count).
- Fix shape: budget-tracker bucket per sub-agent family. Per-family soft budget + hard stop.
- **New tracker item N-18 recommended:** Per-family sub-agent budgets. M, ~100 LOC. Dependency on N-08 (first consumer).

### §7.9 Codex Path Reliability (Bug #20)

- Session 11 scope. Per `docs/plans/2026-04-15-bug-20-codex-appserver-migration.md`.
- Explicitly NOT a Gate A blocker per the tracker.
- ROI: turn-level cancellation preserves session; corrective prompt re-entry continues from previous turn.
- Indirect benefit: reduces Claude-fallback frequency → fewer compile-fix exhaustion cascades.
- **Do after Gate A cleared (Sessions 7–10 first).**

### §7.10 User-Facing Truthfulness → D-14 + broader

- D-14 fidelity headers on 4 verification artefacts (Session 8 scope).
- Broader: every report starts with a confidence banner.
- Example: GATE_A_FAIL_REPORT.md at build-l starts with "Result: FAIL" — this is good. Extend pattern.

---

## Part 6: Cross-Cutting Findings

### 6A. Three-Layer Ownership — Full Table

Legend: S = scaffold_runner.py emits; WB = Wave B owns; WD = Wave D owns; G = generated by tool (e.g., openapi-ts); AE = auditor expects.

| File | AE | S | WB | WD | G | Current Gap |
|---|---|---|---|---|---|---|
| `package.json` (root) | YES | YES | — | — | — | scaffold emits, but missing `prisma:migrate`/`prisma:generate` scripts (AUD-027) |
| `pnpm-workspace.yaml` | YES | YES | — | — | — | emitted |
| `turbo.json` | YES | NO | sometimes | — | — | ownership unclear; missing `dependsOn` wiring (AUD-025) |
| `tsconfig.base.json` | YES | YES | — | — | — | emitted |
| `.gitignore` | YES | YES | — | — | — | emitted |
| `.editorconfig` | YES | NO | NO | NO | — | **no owner** (AUD-024) |
| `.nvmrc` | YES | NO | NO | NO | — | **no owner** (AUD-024) |
| `.env.example` (root) | YES | YES | — | — | — | emitted |
| `docker-compose.yml` postgres | YES | YES | — | — | — | emitted |
| `docker-compose.yml` api service | YES | NO | partial | — | — | scaffold doesn't emit; Wave B added partial (AUD-008 — missing volumes) |
| `docker-compose.yml` web service | YES | NO | NO | partial | — | **no owner** (AUD-007) |
| `apps/api/package.json` | YES | YES | — | — | — | emitted; bcrypt missing (AUD-012) |
| `apps/api/nest-cli.json` | YES | — | YES | — | — | Wave B produced |
| `apps/api/tsconfig.json` | YES | — | YES | — | — | Wave B produced |
| `apps/api/.env.example` | YES | NO | YES (in build-l) | — | — | scaffold doesn't; Wave B filled |
| `apps/api/Dockerfile` | YES | NO | YES | — | — | Wave B emitted dev-only (AUD-019) |
| `apps/api/src/main.ts` | YES | stub | YES (final) | — | — | scaffold stub, Wave B rewrites |
| `apps/api/src/app.module.ts` | YES | — | YES | — | — | Wave B |
| `apps/api/src/generate-openapi.ts` | YES | — | YES | — | — | Wave B (missing globals — AUD-018) |
| `apps/api/src/common/filters/all-exceptions.filter.ts` | YES | — | YES | — | — | AUD-009/013 |
| `apps/api/src/common/interceptors/transform-response.interceptor.ts` | YES | — | YES | — | — | AUD-020 |
| `apps/api/src/common/decorators/public.decorator.ts` | YES | — | YES | — | — | Wave B |
| `apps/api/src/common/decorators/skip-response-transform.decorator.ts` | YES | — | YES | — | — | Wave B |
| `apps/api/src/common/dto/pagination.dto.ts` | YES | — | YES (wrong loc) | — | — | should be in packages/shared (AUD-014/016) |
| `apps/api/src/common/dto/uuid-param.dto.ts` | YES | — | YES | — | — | Wave B |
| `apps/api/src/config/env.validation.ts` | YES | YES (3001) | overwrites (4000) | — | — | scaffold-spec drift (AUD-015/017) |
| `apps/api/src/database/prisma.service.ts` | YES | NO | YES | — | — | but scaffold also emits at `src/prisma/` (duplicate — AUD-011) |
| `apps/api/src/database/prisma.module.ts` | YES | NO | YES | — | — | ditto |
| `apps/api/src/health/health.controller.ts` | YES | — | YES | — | — | Wave B (passes) |
| `apps/api/src/health/health.module.ts` | YES | — | YES | — | — | Wave B |
| `apps/api/src/modules/*/**` (5 empty shells) | YES | — | YES | — | — | Wave B |
| `apps/api/prisma/schema.prisma` | YES | — | YES (Wave A) | — | — | passes (PASS-001) |
| `apps/api/prisma/seed.ts` (empty) | YES | — | YES | — | — | Wave B |
| **`apps/api/prisma/migrations/` init** | YES | **NO** | **NO** | — | — | **no owner (AUD-005)** |
| `apps/api/test/health.e2e-spec.ts` | YES | — | YES | — | — | uses mock (AUD-023) |
| `apps/api/test/jest-e2e.json` | YES | — | YES | — | — | Wave B |
| `apps/web/package.json` | YES | YES | — | extends | — | scaffold emits but missing @hey-api deps (AUD-003/004) |
| **`apps/web/next.config.mjs`** | YES | **NO** | — | **NO** | — | **no owner (AUD-002)** |
| **`apps/web/tsconfig.json`** | YES | **NO** | — | **NO** | — | **no owner (AUD-002)** |
| `apps/web/tailwind.config.ts` | YES | YES (stub) | — | — | — | emitted |
| **`apps/web/postcss.config.mjs`** | YES | **NO** | — | **NO** | — | **no owner (AUD-002)** |
| **`apps/web/.env.example`** | YES | **NO** | — | **NO** | — | **no owner (AUD-006)** |
| **`apps/web/Dockerfile`** | YES | **NO** | — | **NO** | — | **no owner (AUD-002)** |
| **`apps/web/openapi-ts.config.ts`** | YES | **NO** | — | **NO** | — | **no owner (AUD-002/003)** |
| **`apps/web/src/app/layout.tsx`** | YES | **NO** | — | **NO (didn't run)** | — | cascade from Wave B fail |
| **`apps/web/src/app/page.tsx`** | YES | **NO** | — | **NO (didn't run)** | — | cascade |
| **`apps/web/src/middleware.ts`** | YES | **NO** | — | **NO (didn't run)** | — | cascade |
| `apps/web/src/lib/api/client.ts` | YES | NO | — | NO | — | (also partly from generator) |
| **`apps/web/src/test/setup.ts`** | YES | **NO** | — | — | — | **no owner (AUD-022)** |
| `apps/web/vitest.config.ts` | YES | YES | — | — | — | emitted (missing setupFiles — AUD-022) |
| `apps/web/src/styles/globals.css` | YES | YES | — | — | — | emitted |
| `apps/web/eslint.config.js` | (no) | YES | — | — | — | emitted (extra) |
| **`packages/shared/*`** (5 files) | YES | **NO** | **NO** | — | — | **no owner (AUD-001)** |
| **`packages/api-client/*`** (3 files) | YES | **NO** | — | **NO** | YES (by openapi-ts) | generator runs after deps (never did in build-l) |

**Gap summary:**
- **Files with ZERO owner (assumption mismatch):** 13. These fail by design every time.
- **Files with CONFLICTING ownership (scaffold emits + Wave B rewrites):** 2 (env.validation.ts, main.ts). Scaffold-baked values need to survive Wave B or Wave B needs to preserve them.
- **Files with AUDIT-ONLY presence:** same 13 no-owner files — always FAIL until owner assigned.

### 6B. Feature Flag Audit — Complete

| Flag | Default | File:Line | Production-Safe? | In stock config.yaml? | In build-l config.yaml? |
|---|---|---|---|---|---|
| `v18.milestone_scope_enforcement` | TRUE | `config.py:821` | YES | not overridden | not overridden (=True) |
| `v18.audit_milestone_scoping` | TRUE | `config.py:823` | YES | not overridden | not overridden (=True) |
| `v18.review_fleet_enforcement` | TRUE | `config.py:834` | YES (raises on invariant) | not overridden | not overridden (=True) |
| `v18.recovery_prompt_isolation` | TRUE | `config.py:841` | YES | not overridden | not overridden (=True) |
| `v18.m1_startup_probe` | TRUE | `config.py:827` | YES | not overridden | not overridden (=True) |
| `v18.live_endpoint_check` | TRUE | `config.py:787` | YES | not overridden | explicit (=True) |
| `v18.scaffold_enabled` | FALSE | `config.py:789` | safe default | not set | overridden True |
| `v18.openapi_generation` | FALSE | `config.py:788` | safe default | not set | overridden True |
| `v18.provider_routing` | FALSE | `config.py:806` | safe default | not set | overridden True (Codex on Waves B/D) |
| `v18.wave_t_enabled` | TRUE | `config.py:802` | (latent — never successfully run) | not overridden | not overridden (=True) |
| `v18.wave_d5_enabled` | TRUE | `config.py:791` | (latent) | not overridden | not overridden (=True) |
| `v18.ui_design_tokens_enabled` | TRUE | `config.py:817` | YES | not overridden | not overridden (=True) |
| `v18.codex_context7_enabled` | TRUE | `config.py:812` | YES | not overridden | not overridden (=True) |

**Key observation:** the stock `config.yaml` has NO `v18` section at all. All stock-pipeline use follows in-code defaults, which gives a pure-Claude pipeline with scaffold_enabled=False, openapi_generation=False, provider_routing=False. Build-l was a **maximal feature-validation run**; stock smoke would not have hit the same failure mode because scaffold wouldn't have run.

### 6C. Memory Calibrations (noted for future sessions)

1. **`feedback_structural_vs_containment.md`** — don't wrap watchdogs as a substitute for root-cause fixes. Bug #12 series showed six containment layers were dead code.
2. **`feedback_verification_before_completion.md`** — end-to-end smoke must actually fire the fix before claiming "validated." Unit tests alone do not prove production wiring.
3. **`feedback_inflight_fixes_need_authorization.md`** — the branch+commit+PR gate is load-bearing. Even obvious fixes during smoke prep need explicit reviewer authorization. D-02 v2 + D-03 v2 bypassed this; retroactively corrected via PR #25.
4. **`feedback_verify_editable_install_before_smoke.md`** — four pre-flight checks: `pip show` (editable path), `docker ps` (ports 5432/5433/3080), `which agent-team-v15` (CLI entrypoint), `docker ps -a` (stale containers). Build-k burned 90 min on these.

### 6D. Cross-Build Patterns

| Dimension | build-j | build-k | build-l |
|---|---|---|---|
| Pre-flight | passed | FAILED ×3 (install/CLI/ports) | passed |
| Wave A | pass | N/A | pass |
| Wave B | pass | N/A | FAIL (probe port mismatch) |
| Wave C/D | D hung on codex | N/A | skipped |
| Findings | 41 | 0 | 28 |
| Cost | $10.55 | $0 (FAIL-LAUNCH) | $8.37 |
| Truth | Codex watchdog surfaced hang, FAIL correctly | N/A | D-02 v2 surfaced port mismatch, FAIL truthfully |
| False green? | NO | N/A | NO |
| New defect class | Codex orphan-tool | pre-flight cascade | prober port hardcode |

**Pattern:** each paid smoke has surfaced a distinct defect class. Build-l's D-02 v2 fire is the key deliverable — the machinery is now truthful.

---

## Part 7: New Issues Surfaced

### NEW-1 — Duplicate Prisma modules in build-l (HIGH)

**Evidence:** build-l's `apps/api/src/prisma/prisma.module.ts`, `prisma.service.ts`, `prisma.service.spec.ts` exist AND `apps/api/src/database/prisma.module.ts`, `prisma.service.ts` exist (with identical content). `app.module.ts` imports from `./database/`. `test/health.e2e-spec.ts` imports from `../src/prisma/`.

**Root cause:** scaffold emits to `src/prisma/`; Wave B (following M1 REQUIREMENTS) emits to `src/database/`. Nothing removes the scaffold's obsolete emission.

**Severity:** HIGH — broken test imports (AUD-023 masks this with `jest.fn()` stub); dual-location confusion; AUD-011 misframed.

**Fix:** N-04 (scaffold location correction) + Wave B should detect and clean up stale scaffold output.

**Relation to N-items:** N-04 + possible new N-19 (Wave B output sanitization / orphan file cleanup).

### NEW-2 — Scaffold-template spec drift (HIGH)

**Evidence:** scaffold emits `PORT=3001` (tracker A-02 target); current M1 REQUIREMENTS DoD says `:4000`. Scaffold emits Prisma at `src/prisma/`; current M1 REQUIREMENTS says `src/database/`. Other scaffolded values (turbo, tsconfig paths) may have similar drift.

**Root cause:** scaffold templates were authored when an older M1 REQUIREMENTS was canonical; M1 REQUIREMENTS is regenerated per run from PRD; templates are frozen.

**Fix:** N-12 (spec reconciliation) + scaffold templates read from reconciled SPEC.md, not hardcoded values.

**Relation:** N-12 parent, N-04 child, plus add "scaffold template freshness audit" as sub-item.

### NEW-3 — Wave T never successfully run in production (HIGH latent)

**Evidence:** 36 unit tests for Wave T; `wave_executor.py:1747` (`_execute_wave_t`); wave_t_enabled default True. Zero production runs reached Wave T across build-h, build-i, build-j, build-k, build-l.

**Severity:** HIGH (latent) — entire `_execute_wave_t` code path (rollback snapshot at :1781, fix iteration at :1847-1920) is untested in live orchestration.

**Fix:** runs as N-14 corollary + requires a successful Wave B + C + D build first.

### NEW-4 — Codex transport untested in production (HIGH latent)

**Evidence:** `codex_transport.py` 760 LOC; authentication inheritance from `~/.codex/`, CODEX_HOME temp cleanup, turn-level cancellation — zero successful production executions. Build-l used provider_map_b=codex but failed at Wave B probe (after Wave A pass) before the Codex-routed Wave B could fully validate downstream paths.

**Severity:** HIGH — Bug #20 (Session 11) depends on this working.

**Fix:** out of scope for post-Gate-A; handled by Session 11.

### NEW-5 — Post-Wave-E scanners untested (MEDIUM latent)

**Evidence:** 6 post-Wave-E scanners wired at `wave_executor.py:2957-2960`. No build has reached Wave E since they landed.

**Fix:** covered by N-14 (production-caller proof) + requires a successful all-wave run.

### NEW-6 — Wave D.5 design-tokens consumption untested (MEDIUM latent)

**Evidence:** `agents.py:8581-8591` loads UI_DESIGN_TOKENS.json for Wave D/D.5. `ui_design_tokens_enabled` default True. UI_DESIGN_TOKENS.json generated correctly in build-l (1375 bytes). Wave D never ran.

**Fix:** as above — requires successful Wave B to reach.

### NEW-7 — State mutation sites don't validate invariants at write time (MEDIUM)

**Evidence:** `state.summary.success` is computed lazily in `State.finalize()` at `cli.py:13491`. Individual mutation sites like `state.update_milestone_status()` at `state.py:408` append to `failed_milestones` without triggering a recompute of `summary.success`. Build-l demonstrates this: `failed_milestones=["milestone-1"]` + `summary.success=True` coexisted.

**Fix:** new tracker item **N-17** — State write-side invariant validation. ~60 LOC. Matches handoff §7.7.

### NEW-8 — `fix_candidates` coercion drops string IDs silently (MEDIUM)

**Evidence:** `audit_models.py:352-356` coerces string IDs to int indices via `id_to_idx` map; list comprehension `if fid in id_to_idx` silently excludes unresolvable IDs. No log emitted. Build-l didn't exhibit this (all 25 IDs resolvable), but the silent-drop risk remains.

**Fix:** add log.warning when `len(dropped_ids) > 0`. ~3 LOC.

### NEW-9 — Wave sub-agents have no direct MCP access (structural)

**Evidence (verbatim source comment):** `agents.py:5287-5290`:
> "Firecrawl and Context7 MCP tools are NOT included here because MCP servers are only available at the orchestrator level and are not propagated to sub-agents. The orchestrator calls MCP tools directly and passes results to researchers in their task context."

Each agent definition in the `agents` dict (passed to `ClaudeAgentOptions`) has its own `tools` allowlist. Examples: researcher (`["Read", "Write", "Edit", "WebSearch", "WebFetch"]`), code-writer (`["Read", "Write", "Edit", "Bash", "Glob", "Grep"]`), audit agents (Read/Glob/Grep only). No sub-agent has `mcp__*` tools. Wave B/D's heavy lifting is delegated via `Task("code-writer", ...)` from within the wave session; the sub-agent therefore cannot call context7/firecrawl even though the parent session can.

**Fix:** structurally address via N-17 (orchestrator pre-fetch injection). Long-term: investigate ClaudeSDKClient session-forking (Fix B in N-17; NEW-10) for MCP inheritance.

**Severity:** HIGH (structural). Root cause of ~8 Wave B LLM-bug findings in build-l. Full analysis: Appendix C.

### NEW-10 — `ClaudeSDKClient` bidirectional features unused on waves (COMMITTED to full migration)

**Evidence:** builder uses `ClaudeSDKClient` in 6 files (orchestrator, milestone, wave sessions; interviewer; design-reference; runtime_verification; prd_agent) but leaves key capabilities unused:
- **`client.interrupt()`** — zero call sites anywhere in `src/agent_team_v15/` (grep-verified).
- **One-shot `query()` still used** at `audit_agent.py:81, 294` — audit scorer is one of the last holdouts not yet migrated.
- **Per-tool streaming subscription** — orphan-tool detection not wired for Claude path (only for codex transport).
- **Session forking** (`fork_session=True`) — not leveraged. This is the SDK feature that would let sub-agent sessions inherit orchestrator conversation history while getting FRESH MCP access.
- **`Task("sub-agent-name", ...)` dispatch still in agent prompts** at `agents.py:1818-1895` (enterprise mode) — produces sub-agents without MCP.

**Mirror of Bug #20:** codex app-server migration closes the session-preservation + orphan-detection gap for the codex path. NEW-10 closes the same gap on the Claude path via already-available SDK primitives. All verified against upstream docs — see **Appendix D**.

**COMMITTED FIX (3 sessions, ~490 LOC total):**
- **Session 16.5** — migrate `audit_agent.py:81, 294` `query()` → `ClaudeSDKClient` (~60 LOC).
- **Session 17** — eliminate `Task("architecture-lead"/"coding-lead"/"coding-dept-head"/"review-lead"/"review-dept-head", ...)` dispatch from enterprise-mode prompts; replace with Python-orchestrated multi-`ClaudeSDKClient` sessions, each with full MCP access + session-fork for history inheritance (~250 LOC).
- **Session 18** — wire `client.interrupt()` into wave watchdog; subscribe to streaming events for orphan-tool detection on Claude path (~180 LOC).

Full per-agent migration table, validation checklist, and verified SDK examples in **Appendix D**.

**Severity:** HIGH (structural consistency with Bug #20; every Claude agent gets MCP access; wedge recovery becomes uniform across Claude + codex paths).

---

## Part 8: Blocker Chain Analysis

```
N-01 (port resolution)
   │
   ├─→ Gate A re-smoke reaches Wave B health probe success
   │   │
   │   └─→ Wave C + D + T + E can execute
   │       │
   │       └─→ NEW-3 (Wave T), NEW-4 (Codex downstream), NEW-5 (Wave E scanners),
   │            NEW-6 (Wave D.5) all get production exercise
   │
   └─→ unblocks AUD-021

N-08 (wire existing audit-fix loop)
   │
   ├─→ closes ~8-10 Wave B LLM bug findings per cycle
   │   (AUD-009, -010, -012, -013, -016, -018, -020, -023)
   │
   └─→ TRUTHFULNESS MULTIPLIER for every future smoke

N-02 (ownership contract)
   │
   ├─→ N-03 (packages/shared) — child
   ├─→ N-05 (prisma migrations) — child
   ├─→ N-06 (web scaffold) — child
   ├─→ N-07 (docker-compose full) — child
   └─→ closes ~10 scaffold-gap findings
       (AUD-001, -002, -005, -006, -007, -008, -022, -024, -025, -027)

N-04 (Prisma location) + NEW-1 (duplicate cleanup)
   │
   └─→ closes AUD-011 (currently misframed)

N-12 (spec reconciliation) + NEW-2 (template freshness)
   │
   ├─→ unblocks scaffold-template drift class (N-04 special case)
   └─→ consumed by N-02 ownership contract consumers

N-17 (orchestrator pre-fetch → inject framework idioms)
   │
   ├─→ closes 7-8 Wave B LLM-bug findings (AUD-009/010/012/013/016/018/020)
   │   (current-idiom injection prevents training-data drift)
   │
   └─→ feeds data into N-09; together they compress the Wave B LLM-bug cluster

N-09 (Wave B prompt hardeners) + N-10 (content auditor)
   │
   └─→ prevent future Wave B LLM bugs on patterns context7 doesn't cover directly

NEW-10 (ClaudeSDKClient bidirectional — mirror of Bug #20 on Claude path)
   │
   └─→ reduces Claude-wave wedge cost; enables orphan-tool detection on Claude path.
       Post-Bug-#20 scope. Not a Gate A blocker.

N-13 (scaffold self-verify) + N-15 (scope persistence) + NEW-7 (state invariants) + NEW-8 (fix_candidates log)
   │
   └─→ hygiene / truthfulness

PR #25 merge
   │
   └─→ unblocks integration branch landing; D-02 v2 + D-03 v2 deployable

Session 7 (A-10/D-15/D-16) → compile-fix hot-path quality (build-j seeded; build-l didn't hit)
Session 11 (Bug #20) → Codex app-server → reduces fallback frequency
```

**Dependency graph:**
- **Gate A Critical Path:** PR #25 merge → N-01 → Gate A re-smoke attempt.
- **Audit-clearance path:** N-02 (+ N-03/05/06/07 children) + N-08 + N-15 = full-scaffold + iterative fix + truthful persistence. This is the combination that compresses 28 findings to ≤5.
- **Latent-wiring cleanup:** N-14 (process) + §3.1 D-02 halt + §3.2 D-09 wiring + §3.3 D-14 + N-15 = plug the four latent wirings.
- **Enterprise readiness:** N-09 + N-10 + N-12 + NEW-7 budget protection + Bug #20 = one-shot quality.

---

## Part 9: Recommended Session Plan

Realistic extrapolation from build-l data: $8.37 / 70 min for a Wave B failure. A successful all-wave M1 run is estimated $15–25 / 90–150 min. Full M1–M6 enterprise run is $35–60 / 4–6 hours.

### Session 7 — PR #25 Merge + N-01 + N-15 (pre-Gate-A unlock)

- **Scope:** (a) Reviewer gate on PR #25 (D-02 v2 + D-03 v2). (b) Implement N-01 (endpoint_prober port resolution from scaffold output). (c) Implement N-15 (C-01 scope persistence fix).
- **LOC:** ~40 (N-01) + ~40 (N-15) + 0 (merge) = ~80.
- **Risk:** LOW.
- **Validation:** unit tests only. No paid smoke.
- **Cost:** $0.
- **Exit criteria:** PR #25 on master; N-01 committed; N-15 committed; AUDIT_REPORT.json round-trip test confirms scope field persists.

### Session 8 — Gate A-1 Smoke (validate Session 7, limited)

- **Scope:** paid smoke on stock PRD with v18 features enabled (mirror build-l config). Goal: Wave B probe passes → Wave C starts → kill when Wave C starts or completes.
- **Budget:** $10 max. Kill at 90 min or Wave C start (whichever first).
- **Cost:** $8–12.
- **Exit criteria:** AUDIT_REPORT.json shows ZERO AUD-021-class findings (port mismatch). Any other findings are allowable. Preserve artifacts.

### Session 9 — N-02 + N-03 + N-05 + N-06 + N-07 (scaffold completeness cluster)

- **Scope:** ownership contract + 4 scaffold extensions.
- **LOC:** ~150 (N-02 contract + parser) + ~120 (N-03 shared) + ~40 (N-05 migrations) + ~200 (N-06 web) + ~120 (N-07 docker) = ~630 LOC.
- **Risk:** MEDIUM — cross-layer change.
- **Validation:** unit tests + scaffold-dump diff.
- **Cost:** $0.

### Session 10 — Gate A-2 Smoke (validate Session 9)

- **Scope:** paid smoke. Goal: M1 reaches Wave D (or further) with ≤10 audit findings.
- **Budget:** $20 max. Kill at Wave D completion or 150 min.
- **Cost:** $15–22.
- **Exit criteria:** AUDIT findings reduced from 28 to ≤10. Cascade findings vanish. Scaffold-gap findings vanish.

### Session 11 — N-08 (audit-fix loop wiring) + NEW-7 (state invariants)

- **Scope:** wire existing `_run_audit_loop` into milestone orchestration with feature flag (starts OFF). Add write-side invariant checks in state.py.
- **LOC:** ~50 (N-08 wiring) + ~60 (NEW-7) = ~110.
- **Risk:** MEDIUM — spawns sub-agents under budget.
- **Validation:** unit tests. Optionally run Gate A-2's preserved state through audit-fix offline.
- **Cost:** $0 (no smoke).

### Session 11.5 — N-17 (MCP-informed Wave Dispatches)

- **Scope:** at orchestrator layer, before each Wave B/D dispatch, call `mcp__context7__query-docs` for current NestJS 11 / Prisma 5 / Next.js 15 idioms (query set varies by milestone template). Inject as `[CURRENT FRAMEWORK IDIOMS]` section in Wave B/D prompt. Cache responses for reproducibility.
- **LOC:** ~100.
- **Risk:** LOW (read-only pre-fetch + data injection).
- **Validation:** unit tests + cached-response fixtures. No smoke required for Session 11.5; verified in Session 12.
- **Cost:** $0.
- **Exit criteria:** wave-dispatch codepath confirms context7 queries fire and docs appear in prompt.
- **Depends on:** orchestrator has MCP access (already true). No SDK work. Full details: Appendix C §C.3.

### Session 12 — Gate A-3 Smoke (validate Session 11 audit-fix path + Session 11.5 N-17)

- **Scope:** flag N-08 ON, run paid smoke.
- **Budget:** $25 max.
- **Cost:** $15–25.
- **Exit criteria:** AUDIT findings ≤5 after fix iteration. M1 passes DoD at least partially.

### Session 13 — N-04 + N-09 + N-10 + NEW-1 cleanup + hygiene cluster

- **Scope:** Prisma reconciliation + duplicate cleanup; Wave B prompt hardeners (pattern-level, post-N-17); content auditor.
- **LOC:** ~20 (N-04) + ~100 (N-09 — scoped narrower given N-17 already provides current-idiom data) + ~150 (N-10) + ~40 (NEW-1) + fix for NEW-8 coercion warning.
- **Cost:** $0.
- **Note:** N-09 scope is smaller than original 300–400 LOC estimate because N-17 (Session 11.5) already handles the current-idiom injection. N-09 focuses on pattern-level hardeners for non-doc-resolvable issues (e.g., audit-vs-spec disagreements).

### Session 14 — Sessions 7–9 from original tracker (compile-fix, calibration, hygiene)

- **Scope:** A-10, D-15, D-16 (compile-fix quality); D-12, D-14, D-17 (telemetry + calibration); D-01, D-10 (context7 quota + phantom FP).
- **LOC:** ~400 total.
- **Cost:** $0.

### Session 15 — Bug #20 Codex App-Server (Session 11 in original tracker)

- **Scope:** structural codex transport migration.
- **LOC:** ~800 + 20 tests.
- **Risk:** HIGH.
- **Cost:** $0.

### Session 16 — N-12 (spec reconciliation) + NEW-2 (template freshness) + N-13 (scaffold self-verify) + N-11 (cascade suppression)

- **Scope:** deeper reliability layer.
- **LOC:** ~200 + ~120 + ~40 = ~360.
- **Cost:** $0.

### Session 16.5 — NEW-10 Step 1: `audit_agent.py` `query()` → `ClaudeSDKClient` migration (COMMITTED)

- **Scope:** replace `async for msg in query(prompt=prompt, options=options)` at `audit_agent.py:81, 294` with full `ClaudeSDKClient` bidirectional pattern. Add `client.interrupt()` on watchdog timeout.
- **LOC:** ~60.
- **Risk:** LOW (isolated file; same semantics).
- **Validation:** unit tests + AUDIT_REPORT.json round-trip unchanged.
- **Cost:** $0.
- **Per-agent migration table + validation checklist:** Appendix D §D.4–D.5.

### Session 17 — NEW-10 Step 2: Eliminate `Task("sub-agent")` dispatch in enterprise mode (COMMITTED)

- **Scope:** rewrite enterprise-mode orchestration (agents.py:1818-1895) to remove `Task("architecture-lead"/"coding-lead"/"coding-dept-head"/"review-lead"/"review-dept-head", …)` prompt instructions. Replace with Python orchestrator code that opens separate `ClaudeSDKClient` sessions per sub-agent role — each with full MCP access via `ClaudeAgentOptions.mcp_servers` and session-fork (`fork_session=True`) for context inheritance. Verified against Claude Agent SDK Python docs (see Appendix D §D.2).
- **LOC:** ~250.
- **Risk:** MEDIUM (architectural; touches enterprise-mode flows).
- **Validation:** per-sub-agent flow unit tests + integration test verifies every sub-agent session has `mcp__context7__*` in `allowed_tools`.
- **Cost:** may need $10 paid smoke for full enterprise M1+M2 run.

### Session 18 — NEW-10 Step 3 + Step 4: `client.interrupt()` + streaming orphan detection (COMMITTED)

- **Scope:**
  - Wire `client.interrupt()` into `wave_executor._WaveWatchdogState` for Claude-path waves. On wedge: `await client.interrupt()` then decide retry-with-corrective-turn vs escalate. Mirror of codex `turn/interrupt` (see Appendix D §D.3).
  - Subscribe to per-message events from `client.receive_response()`. Detect orphan tool starts (AssistantMessage with `ToolUseBlock` but no matching `ToolResultBlock` within timeout) — Claude analogue of codex `item/started` without `item/completed`.
- **LOC:** ~180.
- **Risk:** MEDIUM (hot-path change; mirrors Bug #12 lessons — cancellation primary, timeouts as containment only).
- **Validation:** stall injection tests; orphan-tool integration test.
- **Cost:** $0.

### Session 19 — Gate C Integration Smoke (post-NEW-10 validation)

- **Scope:** paid smoke after NEW-10 migration. Validates that every agent now uses `ClaudeSDKClient` with full MCP access, and that `client.interrupt()` + streaming orphan detection work under real stall conditions.
- **Budget:** $20 max.
- **Cost:** $15–20.
- **Exit criteria:** (a) every Claude agent session trace shows `mcp__*` tools in allowed_tools; (b) at least one wedge recovery via `client.interrupt()` observed cleanly; (c) orphan-tool detection fires at least once on a Claude-path wave.

### Session 20 — Gate D Smoke (full M1–M6)

- **Scope:** full exhaustive smoke across all milestones.
- **Budget:** $35–50.
- **Cost:** ~$40.
- **Exit criteria:** all milestones PASS; ≤5 findings total; audit_health=passed.

### Session 21 — Master Merge

- **Scope:** no code. Merge `integration-2026-04-15-closeout` → `master`.
- **Cost:** $0.

**Cumulative estimate:** ~$95–130 paid smoke + ~3400 LOC + ~17 sessions (7 through 21, including sub-sessions 11.5 and 16.5). Added vs. prior plan: Session 11.5 (N-17), Session 16.5 (NEW-10 Step 1), Session 17 (NEW-10 Step 2), Session 18 (NEW-10 Step 3+4), Session 19 (Gate C smoke). Conservative vs. original tracker's $45–75 / 13 sessions because:
- 2 additional smoke gates (A-2, A-3) to de-risk the N-08 truthfulness multiplier.
- N-02 ownership contract was not in the original tracker (biggest new scope item).
- N-08 "new phase" reframed as wiring (save vs original estimate).
- **N-17 (MCP-informed wave dispatches)** added — structural fix for the 7–8 Wave B LLM-bug cluster; shrinks N-09 scope.
- **NEW-10 full Claude bidirectional migration (3 sessions, ~490 LOC, COMMITTED)** — parallels codex Bug #20 on the Claude path; every agent gets MCP access + interrupt + orphan detection. Verified against SDK docs in Appendix D.

**Gate criteria per session explicit.** Scan all session exits against the memory rules:
- `feedback_verification_before_completion.md` — every Session ending with "merged" must have an end-to-end smoke result in the validation artifact.
- `feedback_inflight_fixes_need_authorization.md` — any in-flight fix discovered during Session 8/10/12/17 smokes halts the smoke and enters branch-commit-PR-review before relaunch.
- `feedback_structural_vs_containment.md` — no timeout/retry band-aids; N-01 is a structural fix (read from scaffold output), not a "just bump timeout."

---

## Summary

The pipeline is **truthful** (build-l's FAIL is the closeout deliverable working). The remaining gaps are specific, enumerable, and mostly wiring — not construction:

1. **PR #25 merge + N-01 + N-15** (~80 LOC, $0) unblocks Gate A re-smoke.
2. **N-02 + children (N-03/05/06/07)** (~630 LOC, $0 + one $15 smoke) resolves ~10 of 28 build-l findings.
3. **N-08 observability wiring** (~30 LOC, $0 + one $20 smoke) validates the audit-fix iteration primitive end-to-end (already wired at `cli.py:4782`; needs FIX_CYCLE_LOG integration + a successful cycle 2 run).
4. **N-17 (MCP-informed wave dispatches)** (~100 LOC, $0) injects current NestJS 11 / Prisma 5 / Next.js 15 idioms into Wave B/D prompts via orchestrator-side context7 pre-fetch. Closes ~8 Wave B LLM-bug findings structurally. Full analysis: Appendix C.
5. **N-04 + NEW-1** (cleanup) resolves misframed AUD-011.
6. **N-09 + N-10 + N-13** (hygiene, scoped smaller post-N-17) reduces future Wave B LLM-bug counts.
7. **NEW-7 (state invariants) + NEW-8 (coercion logging)** close the truthful-state gap.
8. **NEW-10 (Claude bidirectional full migration — COMMITTED)** — Sessions 16.5 + 17 + 18 (~490 LOC): migrate `audit_agent.py` one-shot `query()` to `ClaudeSDKClient`; eliminate `Task("sub-agent")` dispatch from enterprise-mode prompts; wire `client.interrupt()` into wave watchdog; subscribe to streaming events for orphan-tool detection. After migration: every Claude agent has full MCP access. Structural mirror of codex Bug #20 on the Claude path. SDK specs verified against context7 docs in Appendix D.

Reference counts:
- Handoff claims verified: 23.
- Handoff claims refined: 5 (N-08 wiring not construction; §5.1 scope bigger; §5.2 framing corrected; §5.9 PRD not conflicting; taxonomy 28→18 not 28→17).
- Handoff claims rejected: 2 (3-way port split; PRD specifies src/database).
- New findings: 10 (NEW-1 through NEW-10).
- New root cause surfaced: §5.10 MCP-blind wave execution — structural cause of the 8-finding Wave B LLM-bug cluster.
- Total tracker items post-investigation: 17 N-items (including N-17) + 2 additional proposals (NEW-7/NEW-10 as tracker items) + 4 Session 7–9 deferred + PR #25 + Bug #20 = 25 active items.

Architectural insight (Appendix C): Wave B/D code generation is blind to current-framework idioms because MCP servers are orchestrator-only (verified verbatim at `agents.py:5287-5290`). The handoff's §5.6 "prompt quality baseline with idiom verification" intuition was right; this investigation supplies the source-level evidence and a concrete fix path (N-17 Fix A).

Next step: deep-investigation session's deliverable is this document. Reviewer disposition determines Session 7 scope.

---

## Appendix A — Late-Arriving Refinements (final agent)

Final detailed code-map agent surfaced specific corrections to LOC estimates and file locations used above. Retained here for traceability; the session-plan LOC totals use the MAX of the two estimates where they differ.

- **N-02 Ownership:** `ownership_validator.py` already exists (312 LOC) but only validates OWNERSHIP_MAP.json structure in enterprise mode. Extension, not greenfield — ~200–250 LOC to add three-layer tracking dataclass and consumer updates.
- **N-06 Web scaffold:** refined estimate ~400 LOC (10 templates × 30–40 LOC each) + `_scaffold_web_foundation` update. Higher than my ~200 LOC because each template is meaningful content (layout.tsx, page.tsx, middleware.ts, etc.).
- **N-07 docker-compose:** estimate ~150 LOC (matches).
- **N-09 Wave B prompt:** located at **`agents.py:7879-8049`** (`build_wave_b_prompt`) — not `codex_prompts.py` (codex variant lives at `codex_prompts.py:10-68` in the CODEX_WAVE_B_PREAMBLE). Total across both paths ~300–400 LOC for the 8 hardener blocks + context7 integration.
- **N-10 Content auditor:** refined ~200–300 LOC. `quality_checks.py` is 9,151 LOC (bigger than I noted) — extension pattern is well-established (Violation dataclass, ScanScope).
- **N-11 Cascade suppression:** refined ~150–200 LOC — two options (prompt-level vs consolidation-level), consolidation preferred for reliability.
- **N-13 Scaffold self-verify:** ~250 LOC (new module `scaffold_verifier.py`); `yaml` not imported (would add dependency or use line-parsing).
- **Additional missing scaffolds:** `pnpm-workspace.yaml` and `tsconfig.base.json` are listed in M1 REQUIREMENTS but NOT emitted by scaffold — adds 2 more entries to the ownership matrix (Part 6.A).

**Revised session-plan LOC:**
- Session 7 (PR #25 + N-01 + N-15): ~80 LOC.
- Session 9 (N-02 + N-03 + N-05 + N-06 + N-07): ~250 + 120 + 40 + 400 + 150 = **~960 LOC** (up from my ~630 estimate).
- Session 11 (N-08 + NEW-7): ~110 LOC (unchanged).
- Session 13 (N-04 + N-09 + N-10 + NEW-1): ~20 + 400 + 300 + 40 = **~760 LOC** (up from my ~310).
- Session 14 (Sessions 7–9 original tracker): ~400 LOC (unchanged).
- Session 15 (Bug #20): ~800 LOC (unchanged).
- Session 16 (N-12 + N-13 + N-11 + NEW-2): ~200 + 250 + 150 + 40 = **~640 LOC** (up from ~360).

**Revised cumulative:** ~3000 LOC across ~12 sessions + ~$70–100 paid smoke. Mid-range of the realistic-cost estimate.

Cost escalation vs. original tracker ($45–75 / 13 sessions) is driven by:
- N-02 + children (new scope not in original tracker).
- N-09 scope-up (8 prompt hardeners, not 1–2).
- Gate A-1, A-2, A-3 smokes (de-risking the truthfulness multiplier of N-08 before full Gate D).

Tradeoff: more LOC + more smoke cost in exchange for demonstrable iterative improvement per smoke rather than one big-bang Gate D bet.

---

## Appendix B — Confirmation Round (Sequential-Thinking Deep Review)

This appendix documents a second-pass verification of every finding. Format: **[CONFIRMED]**, **[DEEPENED]**, or **[CORRECTED]** per item, with direct code-read evidence. Priority on high-risk and high-impact claims.

### B.1 Closeout Session Verifications (Sessions 1–5)

| Claim | Status | Direct Evidence |
|---|---|---|
| A-09 `files_outside_scope()` called in prod | **CONFIRMED** | `milestone_scope.py:375-385` (definition); `wave_executor.py:3322` (caller) |
| A-09 scope preamble fires with flag | **CONFIRMED** | `apply_scope_if_enabled()` at `milestone_scope.py:487-504` gates on `v18.milestone_scope_enforcement` |
| C-01 scope preamble in auditor prompts | **CONFIRMED** | `audit_team.py:317-332` wraps prompt; template at `audit_scope.py:109-140` |
| C-01 AuditReport.scope field exists | **CONFIRMED** | `audit_models.py:252` |
| `v18.milestone_scope_enforcement: bool = True` | **CONFIRMED** | `config.py:821` |
| `v18.audit_milestone_scoping: bool = True` | **CONFIRMED** | `config.py:823` |
| `v18.m1_startup_probe: bool = True` | **CONFIRMED** | `config.py:827` |
| `v18.review_fleet_enforcement: bool = True` | **CONFIRMED** | `config.py:834` |
| `v18.recovery_prompt_isolation: bool = True` | **CONFIRMED** | `config.py:841` |
| `v18.wave_t_enabled: bool = True` | **CONFIRMED** | `config.py:802` |
| Commit f23ddad (A-09) merged | **CONFIRMED** | Present in git log on `session-6-fixes-d02-d03` branch |
| Commit 73a9997 (C-01) merged | **CONFIRMED** | Present in git log on branch |
| D-02 v2 commit c1030bb | **CONFIRMED** | Present on branch head |
| D-03 v2 commit 61dd64d | **CONFIRMED** | Present on branch head |
| Master HEAD = 89f460b (no closeout) | **CONFIRMED** | `git log -1 master` verified |
| PR #25 NOT merged | **CONFIRMED** | Current branch ahead of master by 10+ commits including c1030bb, 61dd64d |
| D-04 `ReviewFleetNotDeployedError` raise | **CONFIRMED** | Class at `cli.py:8629`; raise at `:8682` |
| D-07 permissive `from_json` | **CONFIRMED** | `audit_models.py:283-381` with alias handling |
| D-07 fix-up: string→int coercion silent | **CONFIRMED** | `audit_models.py:344-361`; `if fid in id_to_idx` list comprehension, no warning log |
| D-09 helpers zero production callers | **CONFIRMED** | Grep across repo: only `tests/test_mcp_preflight.py` imports `run_mcp_preflight` and `ensure_contract_e2e_fidelity_header` |
| D-11 unconditional WAVE_FINDINGS.json | **CONFIRMED** | `wave_executor.py:576` (definition); `:3033, :3548` (two unconditional call sites) |
| D-13 State.finalize() reactive only | **CONFIRMED** | Grep: only ONE `.finalize()` call site at `cli.py:13491` — end of pipeline |

### B.2 CRITICAL CORRECTIONS TO MY ORIGINAL REPORT

#### B.2.1 N-08: Audit-Fix Loop — **CORRECTION (major)**

**My original claim:** "_run_audit_loop is implemented but NOT called from the main orchestration path."

**Reality:** `_run_audit_loop` has THREE call sites: `cli.py:1400`, `:4782`, `:10486`. Line 4782 is inside the per-milestone loop — this IS the main orchestration path.

**Code verification:**
- `cli.py:4771` — `if config.audit_team.enabled:` (gate)
- `cli.py:4782` — `audit_report, audit_cost = await _run_audit_loop(...)` (production call)
- `cli.py:5843` — `_run_audit_loop` definition
- `cli.py:5951` — inside the loop, `_run_audit_fix_unified` is called from cycle 2 onward
- `cli.py:5965` — `_run_milestone_audit` (scorer) invoked each cycle
- `cli.py:6033` — final `current_report.to_json()` write

**So why does build-l's FIX_CYCLE_LOG.md appear empty?**

Three distinct causes combine:
1. Build-l's config sets `max_reaudit_cycles: 2` — only ONE fix round possible (cycle 1 = audit-only; cycle 2 = fix + audit).
2. `_run_audit_fix_unified` does NOT write to `FIX_CYCLE_LOG.md`. The FIX_CYCLE_LOG append mechanism is only used by OTHER recovery paths (mock_data_fix, contract_generation, review_recovery at `cli.py:6087, :6254, :6349` etc.).
3. Build-l's BUILD_LOG tail shows "Convergence health check FAILED" → "Launching review-only recovery pass" — the fix agents seen in the log are from **convergence recovery** (a different code path), NOT from the audit-fix loop's cycle 2.

**Revised N-08 scope:**
- **NOT** "wire the unwired loop" (it's wired).
- **IS** "add observability + verify cycle 2 actually completes in a successful smoke":
  - Make `_run_audit_fix_unified` write to `FIX_CYCLE_LOG.md` like other recovery paths.
  - Bump `max_reaudit_cycles` default from 2 to 3 (matches code default; build-l's stock config overrode to 2).
  - Validate end-to-end with a smoke that reaches cycle 2 audit-fix.

**Revised LOC:** ~30 LOC for logging + config tweak. Simpler than my original 50 LOC "wiring" estimate.

#### B.2.2 N-15: C-01 Scope Persistence — **DEEPENED (architecture issue, not simple write)**

**My original claim:** "scope_payload populated in memory but not persisted; add a post-persist scope-injection step."

**Deeper reality (verified by reading audit_models.py:234-280):**

Python's `AuditReport.to_json()` at line 265-280 emits KEYS: `audit_id, timestamp, cycle, auditors_deployed, findings, score, by_severity, by_file, by_requirement, fix_candidates, scope, acceptance_tests`.

Build-l's AUDIT_REPORT.json KEYS (verified by direct read): `schema_version, generated, milestone, audit_cycle, overall_score, max_score, verdict, threshold_pass, auditors_run, raw_finding_count, deduplicated_finding_count, findings, pass_notes, summary, score_breakdown, dod_results, fix_candidates, by_severity, by_category`.

**Overlap:** only 4 keys (findings, fix_candidates, by_severity, weak by_category match).

Build-l's file is the SCORER's output. `fix_candidates` is STRING IDs (pre-coercion) not int indices — proof Python's to_json never wrote.

**Mechanism confirmed:** `AuditReport.extras: dict = field(default_factory=dict)` at `audit_models.py:259` was added in D-07 specifically to preserve scorer-extras on read. Comment says "preserve scorer-produced top-level fields that are not first-class on AuditReport." But `to_json()` does NOT emit extras — so if Python's write fires, scorer-extras are LOST.

**Architectural tension:**
- If Python's to_json fires → scope persists, scorer-extras lost
- If Python's to_json doesn't fire → scope missing, scorer-extras kept
- **Neither path preserves everything.**

**N-15 fix (simple, once diagnosed):** extend `to_json()` at line 267-280 to unpack `**self.extras` alongside canonical fields. `extras` is populated at line 342 with `{k: v for k, v in data.items() if k not in _AUDIT_REPORT_KNOWN_KEYS}` — no aliasing risk.

**Revised LOC:** ~10 LOC in `to_json()`. My original 40 LOC estimate was too high. However the fix still requires an end-to-end smoke reaching final write to validate.

#### B.2.3 State.finalize() silent-swallow — **NEW DEEPER FINDING**

At `cli.py:13491-13495`:
```python
try:
    _current_state.finalize(agent_team_dir=Path(cwd) / ".agent-team")
except Exception:
    pass  # Best-effort; save_state still writes legacy defaults.
```

If `finalize()` raises, `save_state` writes with UNRECONCILED values (summary.success wrong, audit_health empty, etc.). Silent failure.

This is a hidden failure mode not covered in my original report. Should be surfaced alongside NEW-7 (write-side invariants). The `except Exception: pass` should at minimum log a warning.

**Add to session plan:** ~5 LOC to replace bare pass with `log.warning`.

#### B.2.4 M1 REQUIREMENTS File Count — **CORRECTION (minor)**

**My claim:** "62 files in Files to Create."

**Verified:** Actual count 57–60 depending on how section headers are counted. My report's 62 is off by ~3–5. Minor imprecision.

#### B.2.5 Scaffold Emission Count — **CORRECTION (minor)**

**My claim:** "Scaffold emits ~20 files for M1."

**Verified:** Per scaffold_runner.py structure (agent 2's detailed read): 3 root + 1 docker-compose + 6 apps/api + 5 apps/web = 15 files. My "~20" was off by ~5.

### B.3 Handoff Claims — Re-Verified Against Code

#### B.3.1 §3.1 D-02 v2 consumer-side fail-loud — **CONFIRMED (partial wiring)**

Direct read of `wave_executor.py:1640-1648` (in `_run_wave_b_probing`):
- `if docker_ctx.infra_missing == True` → `return (True, "", [])` (SKIP)
- `if docker_ctx.infra_missing == False` → `return (False, reason, [])` (BLOCK)

Skip-vs-block DECISION is EXPLICIT at the wave_executor layer. But the consumer at `cli.py:12759` uses generic pattern `if health not in ("passed", "skipped"): recovery_types.append(...)` — treats "blocked" via generic recovery append. **No explicit `RuntimeBlockedError` raise.** Handoff's partial-wiring claim is correct.

#### B.3.2 §3.2 D-09 zero production callers — **CONFIRMED DEFINITIVELY**

Full-repo grep for `run_mcp_preflight` and `ensure_contract_e2e_fidelity_header`:
- Definitions at `mcp_servers.py:429-482` and `:485-523`
- Docstring references at `mcp_servers.py:336-339`
- Tests at `tests/test_mcp_preflight.py` (17 references)
- Prior agent investigation notes
- **ZERO callers in `cli.py`, `wave_executor.py`, `contract_verifier.py`, or any production flow.**

Dead code confirmed. Wiring fix would be ~20 LOC to call at pipeline startup + CONTRACT_E2E_RESULTS.md writer.

#### B.3.3 §3.4 C-01 scope persistence latent bug — **CONFIRMED + DEEPENED**

Build-l's AUDIT_REPORT.json has no `scope` key. See B.2.2 for the deeper architectural analysis.

#### B.3.4 §5.1 Three-Layer Ownership — **CONFIRMED + scope-refined**

Handoff says 62 expected files. Actual is ~57–60 (minor). But the ownership gap IS verified:
- Scaffold emits ~15 files.
- Wave B produces ~43 files (per handoff).
- Wave D never ran in build-l.
- ~13 files have NO owner (my ownership matrix in Part 6.A).

#### B.3.5 §5.3 No Audit-Fix Loop — **CORRECTED**

See B.2.1. Loop IS implemented and wired. Handoff's claim is incorrect.

#### B.3.6 §5.6 Prober Hardcoded `:3080` — **CONFIRMED EXACTLY**

Direct read of `endpoint_prober.py:1023-1036`:
```python
def _detect_app_url(project_root: Path, config: Any) -> str:
    port = getattr(getattr(config, "browser_testing", None), "app_port", 0) if config else 0
    if port:
        return f"http://localhost:{int(port)}"
    env_path = project_root / ".env"
    if env_path.is_file():
        try:
            text = env_path.read_text(encoding="utf-8", errors="replace")
            match = re.search(r"^\s*PORT\s*=\s*(\d+)\s*$", text, re.MULTILINE)
            if match:
                return f"http://localhost:{int(match.group(1))}"
        except OSError:
            pass
    return "http://localhost:3080"
```

Does NOT read `apps/api/.env.example`, `package.json`, `main.ts`, or `docker-compose.yml`. Hardcoded `:3080` fallback. Confirmed exactly.

### B.4 NEW Findings — Re-Verified

| Finding | Status | Evidence |
|---|---|---|
| NEW-1 Duplicate Prisma modules | **CONFIRMED** | `ls` verified both `src/prisma/` (3 files) and `src/database/` (2 files) exist; `diff` on service.ts returns EMPTY (identical files). Test spec file (`prisma.service.spec.ts`) only exists at orphan `src/prisma/` location. |
| NEW-2 Scaffold port drift (3001 vs 4000) | **CONFIRMED** | `scaffold_runner.py:698` emits `PORT: Joi.number().integer().positive().default(3001)`; M1 REQUIREMENTS has 11 references to port 4000 (lines 77, 112, 407, 411, 422, 423, 473, 480, 481, 568, 569); comment at line 691 says "A-02: PORT default is 3001 (M1 dev-api port baseline)" — baked assumption from older spec. |
| NEW-3 Wave T never successfully run | **CONFIRMED** | WAVE_FINDINGS.json scan across 7 build artifacts (build-c, build-g, build-h, build-i, build-j, build-l, build-h nested): ALL show `findings: []`; only build-l has explicit `wave_t_status: "skipped"` with skip_reason. **ZERO instances of `wave_t_status: "completed"` or populated findings array.** |
| NEW-4 Codex transport untested | **CONFIRMED** (partial exercise only) | Build-l used `provider_map_b: codex`; Codex subprocess initiated; but never completed a wave because Wave B blocked at probe. Full Codex session lifecycle (session-end, tool-events, completion) not verified. |
| NEW-5 Post-Wave-E scanners untested | **CONFIRMED** | Wired at `wave_executor.py:2957-2960`; no build reached Wave E. |
| NEW-6 Wave D.5 tokens consumption untested | **CONFIRMED** | `agents.py:8581-8591` wires tokens into Wave D/D.5 prompt; Wave D never ran in build-l. |
| NEW-7 State write-side invariants missing | **CONFIRMED + DEEPENED** | `state.py:135` computes `summary["success"] = (not self.interrupted) and len(self.failed_milestones) == 0` in `finalize()`. Mutation sites (e.g., `update_milestone_status`) don't trigger recompute. **ADDITIONAL:** `cli.py:13494-13495` wraps finalize in bare `try/except: pass` — silent failure mode. |
| NEW-8 fix_candidates silent coercion drop | **CONFIRMED** | `audit_models.py:354-356` uses `[id_to_idx[fid] for fid in raw if fid in id_to_idx]` — no warning emitted when IDs fail to resolve. |

### B.5 Items NOT Deeply Re-Verified (trusted from agent reports)

I trusted the agent reports for these without direct code re-reading:
- Session 2 scaffold template content details (A-01/02/03/04/07/08/D-18) — spot-checked PORT=3001 directly.
- Session 4 D-05 (recovery prompt role isolation) — trusted agent 3's file:line read.
- Session 4 D-06 (recovery taxonomy 28 types) — trusted agent 3's count.
- Session 4 D-08 (CONTRACTS.json primary producer path) — trusted agent 3.
- Feature flag default values beyond the 5 I directly verified — trusted config.py reads.

All of the above had two independent agent reports agreeing, so confidence is high despite not personally re-reading.

### B.6 Consolidated Changes to Main Report

Apply these corrections to the main report above:

1. **Part 1 §1C (C-01 latent bug):** Add the JSON-shape divergence architectural finding; note Python's to_json() lacks scorer-extras keys.
2. **Part 3 §3C (N-08):** Flip from "not wired" to "wired but unvalidated"; scope is add-logging + bump-cycles + end-to-end verify.
3. **Part 4 N-08 card:** Reduce LOC to ~30; scope change.
4. **Part 4 N-15 card:** Reduce LOC to ~10; mechanism simpler than thought (add `**self.extras` to to_json).
5. **Part 7 NEW-7 card:** Add the finalize() silent-swallow sub-finding (~5 LOC).
6. **Part 9 session plan:** Total LOC drops ~80 (N-08 reduction + N-15 reduction). Still ~12 sessions, ~$70–100 paid smoke.

### B.7 Confidence Summary

| Category | Confidence | Notes |
|---|---|---|
| Sessions 1-5 verifications | VERY HIGH | Direct code read for most items; agent reports cross-verified. |
| Build-l 28 findings | VERY HIGH | Full JSON read directly. |
| Root causes §5.1-§5.9 | HIGH | §5.3 corrected; others verified. |
| N-items mapping | HIGH | Most verified; N-08 and N-15 corrected here. |
| NEW findings | VERY HIGH | Each direct-verified in B.4. |
| Session plan LOC estimates | MEDIUM | Rough ranges; N-09 bigger than I claimed, N-08/N-15 smaller. |
| Session plan cost estimates | MEDIUM-LOW | Extrapolated from a single $8.37 data point (build-l fail). Successful runs may cost more. |

### B.8 Final Status

Investigation completed with multiple corrections. Main report updated via this appendix. Most structural gaps identified in the handoff ARE real; the ones the handoff named slightly wrong have been refined. The single biggest correction is N-08: the audit-fix loop is WIRED, not unwired — a much smaller gap (observability + validation) than the handoff suggested.

Next step: reviewer disposition on whether to apply the corrections in-place to Parts 1–9 of the main report (Appendix B already serves as an addendum that preserves both views).

---

## Appendix C — Wave Architecture: Structural Constraints (Late-Added)

This appendix surfaces a structural class of findings not present in the handoff or in Parts 1–9 of this report. It documents how waves actually execute inside the SDK, and names a new tracker item (N-17) that addresses the single biggest contributor to the Wave B LLM-bug cluster.

### C.1 What Wave Agents Actually Are

Wave agents are **NOT independent Claude Code sessions with full capabilities**. They are either (a) fresh `ClaudeSDKClient` sessions with a SHARED set of options cloned from the top-level orchestrator, or (b) restricted sub-agents invoked via the SDK's `Task(agent_name, prompt)` tool from inside a session — with a per-sub-agent `tools` allowlist that excludes MCP tools.

**Single-session plumbing (verified):**

- `cli.py:449` builds ONE `ClaudeAgentOptions(**opts_kwargs)` carrying `mcp_servers={context7, firecrawl, nano_banana, sequential_thinking, …}`, `agents={planner, researcher, architect, code-writer, code-reviewer, …}`, `allowed_tools=[…]`, `system_prompt=…`.
- `cli.py:458-460` (`_clone_agent_options`) clones this object per wave/milestone, preserving the `mcp_servers` and `agents` dicts.
- `cli.py:3350-3379` and `cli.py:3969-3986` (`_execute_single_wave_sdk`) open a fresh `ClaudeSDKClient(options=wave_options)` PER WAVE and submit the wave prompt via `client.query(prompt)`. So waves are distinct SDK sessions, NOT Task() sub-agents of the orchestrator. Each wave inherits the same cloned options.
- `mcp_servers.py:149-171` (`recompute_allowed_tools`) adds MCP tool names (`mcp__context7__query-docs`, `mcp__firecrawl__*`, `mcp__playwright__*`) to the session's `allowed_tools` only when those servers are present in the session's `mcp_servers` dict.
- `_prepare_wave_sdk_options` at `cli.py:467-488` only materially modifies MCP for Wave E (adds Playwright). It inherits the base `mcp_servers` dict otherwise.

**The MCP-propagation gap (verified verbatim):**

At `agents.py:5287-5290` there is an EXPLICIT source comment (on the `researcher` sub-agent definition):

> "Firecrawl and Context7 MCP tools are NOT included here because MCP servers are only available at the orchestrator level and are not propagated to sub-agents. The orchestrator calls MCP tools directly and passes results to researchers in their task context."

Each sub-agent in the agents dict has its own `tools` allowlist. Examples verified directly:
- `researcher` (`agents.py:5294-5296`): `["Read", "Write", "Edit", "WebSearch", "WebFetch"]` — no MCP tools.
- Other sub-agents (planner, architect, code-writer, code-reviewer) follow the same pattern: curated tool lists without `mcp__*` entries.

When the orchestrator's session — or a wave's session — invokes `Task("code-writer", prompt)` or `Task("architecture-lead", prompt)` (see `agents.py:1818-1821` for the enterprise-mode Task dispatch pattern), the nested sub-agent runs under its own restricted tool list. Even if the PARENT session has `context7` in its `mcp_servers`, the SUB-AGENT cannot call MCP tools because `mcp__context7__*` is not in the sub-agent's `tools` allowlist.

**Capability matrix (verified):**

| Layer | Tool surface | MCP access |
|---|---|---|
| Orchestrator session (top-level `ClaudeSDKClient`) | Read, Write, Edit, Bash, Glob, Grep, Task, WebSearch, WebFetch, all configured MCPs | YES — context7, firecrawl, nano-banana, sequential_thinking per config |
| Wave B / Wave D session (fresh `ClaudeSDKClient`, base prompt = `build_wave_b_prompt` / `build_wave_d_prompt` output) | Inherits base `allowed_tools` including MCP names when present | THEORETICALLY YES at top of wave session, but wave prompt does not instruct the top-level actor to call context7; actual wave work is delegated via Task() to code-writer → MCP stripped |
| Code-writer sub-agent (invoked by wave session via Task) | Read, Write, Edit, Bash, Glob, Grep | **NO** |
| Audit agents (requirements, technical, interface, test, etc.) | Read, Glob, Grep (+ Bash for test auditor) | **NO** |
| Researcher sub-agent | Read, Write, Edit, WebSearch, WebFetch | **NO** — relies on orchestrator pre-fetch injection |
| Code-reviewer sub-agent | Read, Glob, Grep, Edit | **NO** |

**Contrast:** this investigation session itself runs with full Claude Code capability — Bash, Read, Edit, Write, Glob, Grep, Task, ToolSearch, plus live MCP access to context7, nanobanana, notebooklm, sequential-thinking. Wave B/D sub-agents effectively have ~40% of that surface; audit sub-agents <20%.

### C.2 ClaudeSDKClient: Partial Use, Full Opportunity

**What Bug #20 (codex app-server) targets** (per `docs/plans/2026-04-15-bug-20-codex-appserver-migration.md` §2a): replace the one-shot `codex exec` subprocess pattern with the app-server's `thread/start` + `turn/start` + `turn/interrupt` + streaming `item/started/item/completed` + `tokenUsage/updated` + `turn/diff/updated` events. Session stays alive across interrupts; graceful cancellation; rich lifecycle telemetry.

**Claude-side current state:**
- `cli.py` uses `ClaudeSDKClient` in MANY places (lines 33, 684, 692, 774, 791, 822, 1698, 1994, 2292, 2332, 2485, 2701, 3359, 3980, etc.) — orchestrator session, milestone sessions, wave sessions, interviewer (`interviewer.py:682`), design-reference extraction (`design_reference.py:208`).
- `audit_agent.py:81` uses the one-shot `async for msg in query(prompt=prompt, options=options)` pattern — the Claude analogue of `codex exec`.
- **The builder DOES use bidirectional `ClaudeSDKClient`** for wave/orchestrator sessions. The gap is that it doesn't leverage the bidirectional FEATURES: no `client.interrupt()` on wedge, no streaming tool-event subscription for orphan-tool detection, no session-forking for sub-agent MCP inheritance.

**Mirror opportunity for Bug #20:**

| Concern | Codex Bug #20 target | Claude mirror (currently un-scoped) |
|---|---|---|
| Transport | `codex exec` → `codex app-server --listen stdio://` | `query()` one-shot (audit_agent.py:81) → bidirectional `ClaudeSDKClient` already in use for waves, but control-protocol features unused |
| Graceful cancel | `turn/interrupt` RPC | `ClaudeSDKClient.interrupt()` control-protocol call (unused in current code) |
| Session preservation on wedge | Session stays alive, send corrective `turn/start` | Same semantics if we adopt `client.interrupt()` + follow-up `client.query()` |
| Rich lifecycle telemetry | `item/started` / `item/completed` streamed | SDK streams per-message / per-tool-use events; not subscribed for orphan detection |
| Orphan-tool detection | `item.started` without matching `item.completed` | Same shape via SDK message stream (unexploited) |

**New tracker item (implicit):** a Bug #20 mirror — "Claude-path turn-level interrupt + streaming-telemetry migration." Scope: audit `client.interrupt()` usage, add orphan-tool detection on Claude-wave message streams, consider session-forking for MCP-inheriting sub-agents. Not a near-term Gate A blocker; but closing the cost-avoidance and reliability gap that Bug #20 closes for codex.

### C.3 N-17: MCP-Informed Wave Dispatches (NEW tracker item)

**Problem (structural root cause):** the 7–8 Wave B LLM-bug findings in build-l (AUD-009 duplicate filter registration, AUD-010 getOrThrow vs .get, AUD-012 bcrypt dep missing, AUD-013 bare strings vs ErrorCodes, AUD-016 Object @ApiProperty, AUD-018 generate-openapi globals, AUD-020 URL-prefix skip) share a common root cause: **Wave B is generating NestJS 11 code blind to current-framework idioms.** The Wave B top-level agent CAN technically call MCP tools if `allowed_tools` includes them, but the Wave B prompt at `agents.py:7879-8049` does NOT instruct the agent to call context7 for current idioms. And when Wave B delegates implementation work to `code-writer` via Task(), MCP access is stripped per C.1.

**Evidence:**
- `agents.py:7879` Wave B prompt is a static string construction; no context7 query injection.
- `agents.py:5287-5290` explicit comment: orchestrator-pre-fetch is the intended pattern for research agents. Never applied to Wave B/D.
- The 8 build-l Wave B LLM bugs all match patterns that context7 would resolve correctly (NestJS 11 `@Catch` registration, Prisma 5 shutdown hook, current Swagger decorators, ConfigService idioms). These are exactly the kind of drift that up-to-date docs would prevent.

**Three fix shapes:**

**Fix A (cheap, within-session) — RECOMMENDED:**
At orchestrator layer, before dispatching each Wave B/D, call the relevant context7 tool(s) directly:
- `mcp__context7__resolve-library-id("nestjs")` → `/nestjs/nest`
- `mcp__context7__query-docs("/nestjs/nest", "filter registration APP_FILTER vs useGlobalFilters")`
- `mcp__context7__query-docs("/prisma/prisma", "Prisma 5 beforeExit shutdown hook")`
- `mcp__context7__query-docs("/vercel/next.js", "Next.js 15 app-router middleware")`

Inject the returned documentation into the Wave B/D prompt as a `[CURRENT FRAMEWORK IDIOMS]` section BEFORE the task manifest. One-time per-milestone cost; amortizes across wave retries.

LOC: ~80 for orchestrator-side context7 calls + prompt injection hooks + tests. Depends on which framework queries matter per milestone type (full_stack/backend_only/frontend_only).

**Fix B (structural) — SCOPE-OUT FIRST:**
Investigate whether the Claude SDK supports "session forking" with MCP inheritance. Per Context7 docs (general SDK messaging), `ClaudeSDKClient` supports "programmatic features for subagents and session forking [...] enabling more sophisticated multi-agent workflows." If session forks inherit `mcp_servers`, migrate the Wave B/D dispatch to fork the orchestrator session rather than spawn a fresh `ClaudeSDKClient`. Sub-agents would then have direct MCP access.

This is contingent on SDK capability that needs verification. Flag for a follow-up investigation session; not implementable today without SDK spelunking.

**Fix C (not viable without SDK changes):**
Inject `mcp_servers` into the agent-definition dict (per-sub-agent MCP config). SDK doesn't support this today per C.1. Would require SDK changes or a custom agent-definition extension.

**Recommendation:** Fix A as the near-term lever. It closes the 7–8 Wave B LLM bug class without architectural work. Flag Fix B for a deep-investigation session to scope SDK capability.

**N-17 scope estimate:** M. ~80 LOC (orchestrator-side) + ~20 LOC (prompt-builder injection) + 4–6 tests. **Risk:** LOW (pre-dispatch data injection; doesn't touch wave execution semantics).

**N-17 dependency graph position:**
- Feeds into N-09 (Wave B prompt quality uplift). N-17 is the data source; N-09 is the prompt edit.
- N-17 is a structural complement to N-09: N-09 hardens prompt text around known patterns; N-17 ensures the model sees CURRENT framework docs.
- Together, N-17 + N-09 are expected to close the 7–8 Wave B LLM-bug cluster in one smoke cycle.

### C.4 New Findings Added to Part 7

**NEW-9 — Wave sub-agents have no direct MCP access (structural).** MCP servers live on `ClaudeAgentOptions.mcp_servers` at the top-level session; sub-agents dispatched via `Task(agent_name, ...)` have per-sub-agent `tools` allowlists that do NOT include `mcp__*` tool names. Verified via explicit source comment at `agents.py:5287-5290`. This is the structural mechanism behind N-17's existence.

**NEW-10 — `ClaudeSDKClient` bidirectional features unused (COMMITTED to full migration).** Builder opens `ClaudeSDKClient` sessions for orchestrator and waves but never calls `client.interrupt()`, never subscribes to per-tool streaming events for orphan detection. The `query()` one-shot pattern is still used in `audit_agent.py:81, 294`. Additionally, `Task("sub-agent-name", ...)` dispatch (agents.py:1818-1895 enterprise-mode instructions) spawns nested sub-agents with restricted tool allowlists that EXCLUDE MCP (per the verbatim source comment at `agents.py:5287-5290`). Those sub-agents are structurally unable to call context7/firecrawl/any MCP — effectively useless for current-idiom-aware code generation.

**COMMITMENT (was scope-out; now IMPLEMENT):** migrate EVERY Claude agent touchpoint to `ClaudeSDKClient` bidirectional mode with full MCP access. No more one-shot `query()`. No more `Task("...")` sub-agent dispatch. Each agent runs as a TOP-LEVEL actor in its own `ClaudeSDKClient` session with `ClaudeAgentOptions.mcp_servers` configured (context7, firecrawl, nano-banana, sequential-thinking, playwright as relevant) and the appropriate `allowed_tools` including `mcp__*` entries. See **Appendix D** for the verified SDK specification and **Appendix C.6** for the per-session plan.

### C.5 Blocker Chain Update (Part 8 addition)

```
N-17 (orchestrator context7 pre-fetch → inject into Wave B prompt)
   │
   ├─→ Closes 7–8 Wave B LLM bug findings (AUD-009, -010, -012, -013, -016, -018, -020)
   │
   └─→ Feeds into N-09 (Wave B prompt hardeners still needed for patterns
                        context7 doesn't explicitly cover, e.g., audit-spec
                        disagreements like AUD-012 bcrypt)

NEW-10 (ClaudeSDKClient full migration — COMMITTED)
   │
   ├─→ Step 1: replace query() one-shot in audit_agent.py:81, 294 → ClaudeSDKClient
   ├─→ Step 2: delete Task("architecture-lead"/etc) dispatch (agents.py:1818-1895);
   │           replace with Python-orchestrated multi-session pattern —
   │           each "sub-agent" role becomes its own ClaudeSDKClient session
   │           with full MCP access
   ├─→ Step 3: wire client.interrupt() into wave watchdog for wedge recovery
   ├─→ Step 4: subscribe to ClaudeSDKClient streaming events for orphan-tool
   │           detection on Claude-path waves (mirror of codex item/started
   │           item/completed lifecycle)
   │
   └─→ Outcomes: every Claude agent has MCP access; structural elimination of
                 the MCP-propagation gap that created N-17; wave/agent wedges
                 become recoverable via interrupt+retry instead of kill.
                 Parallels codex Bug #20 on Claude path.

Bug #20 (codex app-server migration — COMMITTED, already in tracker)
   │
   └─→ thread/start + turn/start + turn/interrupt + streaming item events.
       See Appendix D for verified spec.
```

### C.6 Session Plan Update (Part 9 addition — COMMITTED MIGRATION)

**Session 11.5 — N-17 Fix A (orchestrator MCP pre-fetch → Wave B/D prompt injection)**
- Scope: add `mcp__context7__query-docs` queries at wave-dispatch time (NestJS 11, Prisma 5, Next.js 15 idioms per milestone template). Inject as `[CURRENT FRAMEWORK IDIOMS]` section in Wave B/D prompt.
- LOC: ~100.
- Risk: LOW.
- Validation: unit tests on injection + cache the context7 responses for reproducibility.
- Cost: $0.

**Session 16.5 — NEW-10 Step 1: `audit_agent.py` query() → ClaudeSDKClient migration**
- Scope: replace `async for msg in query(prompt=prompt, options=options)` at `audit_agent.py:81, 294` with `async with ClaudeSDKClient(options=options) as client: await client.query(prompt); async for msg in client.receive_response():` pattern. Add `client.interrupt()` on watchdog timeout.
- LOC: ~60 (two call sites + watchdog integration + tests).
- Risk: LOW (isolated file; retains same semantics for audit scoring).
- Validation: unit tests + check that AUDIT_REPORT.json shape is preserved.
- Cost: $0.

**Session 17 — NEW-10 Step 2: Eliminate Task("sub-agent") dispatch in enterprise-mode prompts**
- Scope: rewrite enterprise-mode orchestration (agents.py:1818-1895) to NOT instruct the orchestrator to `Task("architecture-lead"/"coding-lead"/"coding-dept-head"/"review-lead"/"review-dept-head", …)`. Instead, Python orchestrator code opens separate `ClaudeSDKClient` sessions for each sub-agent role, each with full MCP access via `ClaudeAgentOptions.mcp_servers`. Use session forking (`fork_session=True`) to preserve orchestrator conversation context in each sub-agent session.
- LOC: ~250 (rewrite 4–5 enterprise-mode flows to Python-orchestrated multi-session + remove Task() prompts + wire session-fork propagation of context).
- Risk: MEDIUM (architectural change; touches enterprise-mode orchestration).
- Validation: unit tests per sub-agent flow + enterprise-mode smoke (M1+M2 run).
- Cost: enterprise-mode test may need ~$10 paid smoke if full-pipeline.

**Session 18 — NEW-10 Step 3 + Step 4: `client.interrupt()` integration + streaming orphan detection**
- Scope:
  - Wire `client.interrupt()` into `wave_executor._WaveWatchdogState` for Claude-path waves. On wedge: `await client.interrupt()` then decide retry vs escalate.
  - Subscribe to per-message events from `client.receive_response()`. Detect orphan tool starts (AssistantMessage with ToolUseBlock but no matching ToolResultBlock within timeout) — Claude analogue of codex `item/started` without `item/completed`.
- LOC: ~180 (watchdog integration + orphan detector + orphan-tool schema alignment with existing codex orphan logic + tests).
- Risk: MEDIUM (hot-path change; mirrors Bug #12 lessons — use real cancellation, not containment).
- Validation: unit tests with stall injection; integration test with an orphan-tool scenario.
- Cost: $0.

**Migration sequence rationale:**
- Session 16.5 first (isolated, LOW risk): de-risk the pattern by migrating one file.
- Session 17 after 16.5 succeeds: apply the pattern to enterprise-mode orchestration.
- Session 18 after 17: add the reliability features (interrupt + orphan detection) now that all agents use ClaudeSDKClient uniformly.

**Revised cumulative:** ~3400 LOC across ~16 sessions + ~$80–110 paid smoke. The NEW-10 migration adds ~490 LOC split across 3 sessions; gives every Claude agent full MCP access and structural wedge recovery.

### C.7 Why This Matters (revised)

**Before NEW-10 migration:**
- Sub-agents dispatched via Task() operate in a restricted tool shell with no MCP. Useless for queries against current-framework docs. Forces the workaround pattern (orchestrator pre-fetch + prompt injection) that N-17 implements.
- One-shot `query()` in `audit_agent.py` has no interrupt-on-wedge. Audit sub-agent hangs = kill-the-pipeline recovery.
- No Claude-path orphan-tool detection. Bug #12 lessons apply: we need real cancellation, not just timeouts.

**After NEW-10 migration:**
- Every Claude agent is a top-level `ClaudeSDKClient` with MCP access. Orchestrator pre-fetch (N-17) becomes OPTIONAL rather than MANDATORY — agents can call context7 directly in-line. N-17 remains valuable for pre-seeding common patterns, but agents CAN self-serve.
- `client.interrupt()` on wedge: session survives, recovery via corrective turn.
- Orphan-tool detection on Claude path: mirror of codex Bug #20 streaming-event subscription.
- Consistent behavior across Claude + codex paths: fewer special cases in wave watchdog / recovery.

This is the STRUCTURAL complement to Bug #20 on the Claude side. Both migrations close the session-preservation + streaming-telemetry gap that makes wedge recovery expensive today.

### C.8 Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Single `ClaudeAgentOptions` object | VERY HIGH | `cli.py:449` direct read |
| MCP-propagation gap to sub-agents | VERY HIGH | `agents.py:5287-5290` verbatim source comment |
| Sub-agent `tools` lists exclude MCP | VERY HIGH | Multiple sub-agent definitions read |
| Wave sessions are fresh `ClaudeSDKClient` | VERY HIGH | `cli.py:3359, 3980` direct read |
| Wave B prompt doesn't call context7 | HIGH | `agents.py:7879-8049` structure is static string construction; no MCP tool invocations in the prompt body |
| `ClaudeSDKClient.interrupt()` not used on Claude waves | VERY HIGH | Grep confirmed: zero `client.interrupt()` calls anywhere in `src/agent_team_v15/` |
| Fix A is cheap and within-session | HIGH | Orchestrator already has MCP access; just adds pre-fetch + prompt-inject plumbing |
| NEW-10 Step 1: `query()` migration feasible | VERY HIGH | Two call sites at `audit_agent.py:81, 294`; `ClaudeSDKClient` pattern already used in 6 files; see Appendix D |
| NEW-10 Step 2: session-forking preserves history, NEW mcp_servers | VERY HIGH | Verified from Claude Agent SDK Python docs (see Appendix D §D.2) — fork_session creates new session ID; options at fork-time are the NEW options |
| NEW-10 Step 3: `client.interrupt()` Python API | VERY HIGH | Verified from SDK docs — `async def interrupt(self) -> None`; works in streaming mode (see Appendix D §D.1) |
| NEW-10 Step 4: streaming events accessible | VERY HIGH | Verified — `client.receive_response()` yields messages; AssistantMessage contains content blocks including ToolUseBlock (see Appendix D §D.1) |
| Codex app-server Bug #20 spec | VERY HIGH | All RPC methods + notification shapes verified against upstream docs (see Appendix D §D.3) |

End of Appendix C.

---

## Appendix D — Verified SDK Specifications (context7-sourced)

This appendix captures verified documentation for the Claude Agent SDK and Codex app-server protocols. Every API shape below was confirmed via `context7.query-docs` against upstream sources before being written into the plan. Quotes are verbatim from the Context7 documentation index as of 2026-04-16.

### D.1 Claude Agent SDK — ClaudeSDKClient Bidirectional Mode

**Source:** `/anthropics/claude-agent-sdk-python` (official, High reputation).

**Core bidirectional pattern (verified example):**

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

options = ClaudeAgentOptions(
    mcp_servers={"tools": server},       # full MCP access
    allowed_tools=["mcp__tools__greet"], # pre-approved tools
    permission_mode="acceptEdits",
)

async with ClaudeSDKClient(options=options) as client:
    await client.query("Greet Alice")
    async for msg in client.receive_response():
        print(msg)
```

- **`client.query(prompt)`** — send a prompt to Claude. Multiple `query()` calls reuse the same session.
- **`client.receive_response()`** — async iterator yielding `AssistantMessage`, `SystemMessage`, etc. Each `AssistantMessage` has `.content: list[TextBlock|ToolUseBlock|ToolResultBlock]`.

**Interrupt API (verified from docs):**

> Shows how to send an interrupt signal to Claude during execution using the `interrupt` method of the `ClaudeSDKClient`. This functionality is primarily effective in streaming mode.

```python
async def interrupt(self) -> None
```

Example:
```python
async with ClaudeSDKClient(options=options) as client:
    await client.query("Count from 1 to 100 slowly")
    await asyncio.sleep(2)
    await client.interrupt()
    print("Task interrupted!")
    await client.query("Just say hello instead")
    async for message in client.receive_response():
        ...
```

**Hooks API (verified):**

```python
from claude_agent_sdk import HookMatcher

async def check_bash_command(input_data, tool_use_id, context):
    if input_data["tool_name"] != "Bash": return {}
    # inspect input_data["tool_input"] — deny/allow decision
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "..."
        }
    }

options = ClaudeAgentOptions(
    hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[check_bash_command])]}
)
```

Hooks are Python functions invoked at specific points in the agent loop (e.g., `PreToolUse`). Enables deterministic control over agent behavior without prompt engineering.

**Custom tools via in-process MCP (verified):**

```python
from claude_agent_sdk import tool, create_sdk_mcp_server

@tool("greet", "Greet a user", {"name": str})
async def greet_user(args):
    return {"content": [{"type": "text", "text": f"Hello, {args['name']}!"}]}

server = create_sdk_mcp_server(name="my-tools", version="1.0.0", tools=[greet_user])
options = ClaudeAgentOptions(mcp_servers={"tools": server}, allowed_tools=["mcp__tools__greet"])
```

Custom tools run **in-process** (no subprocess) — Python functions exposed as MCP tools. Useful for deterministic feedback loops without the cost of an external MCP server.

**Migration docs (verified — confirms the programmatic-subagent feature):**

> When upgrading from the Claude Code SDK (versions < 0.1.0) to the Claude Agent SDK, several breaking changes and new features have been introduced. [...] New programmatic features for subagents and session forking have been added, enabling more sophisticated multi-agent workflows.

### D.2 Claude Agent SDK — Session Forking

**Source:** `/nothflare/claude-agent-sdk-docs` (docs mirror, High reputation) and official SDK migration notes.

**Fork semantics (verified Python example):**

```python
from claude_agent_sdk import query, ClaudeAgentOptions

# Original session
session_id = None
async for message in query(
    prompt="Help me design a REST API",
    options=ClaudeAgentOptions(model="claude-sonnet-4-5")
):
    if hasattr(message, 'subtype') and message.subtype == 'init':
        session_id = message.data.get('session_id')

# Fork with NEW options (MCP servers, agents, tools configured FRESH)
async for message in query(
    prompt="Now let's redesign this as a GraphQL API instead",
    options=ClaudeAgentOptions(
        resume=session_id,
        fork_session=True,                        # creates NEW session ID
        model="claude-sonnet-4-5",
        # mcp_servers=..., allowed_tools=...     # CAN be different from parent
    )
):
    ...

# Original session remains unchanged and resumable
async for message in query(
    prompt="Add authentication to the REST API",
    options=ClaudeAgentOptions(
        resume=session_id,
        fork_session=False,                       # default: continue original
    )
):
    ...
```

**Key implications for this migration:**
1. **History is inherited** on fork — the forked agent sees the full parent conversation.
2. **Options are FRESH at fork time** — the caller supplies new `mcp_servers`, `allowed_tools`, `permission_mode`, etc. This is exactly what NEW-10 Step 2 needs: a "sub-agent" session that inherits orchestrator context PLUS has its own MCP access.
3. **Multiple parallel branches** possible from a single parent session.
4. **Original session is not mutated** — safe to fork repeatedly.

This is the structural replacement for `Task("sub-agent-name", ...)` dispatch. Instead of letting the SDK spawn an internal restricted sub-agent, Python code opens a new `ClaudeSDKClient` (or uses `query()` with fork options) with full MCP + appropriate prompt.

### D.3 Codex App-Server — Verified JSON-RPC Specification

**Source:** `/openai/codex` (High reputation, 870 snippets, official).

**Transport:** JSON-RPC over stdio. Spawn the server with `codex-app-server` binary or via Python bindings (`codex_app_server` package).

**Required initialization sequence:**

```json
// Request (always first, required)
{
  "method": "initialize",
  "id": 0,
  "params": {
    "clientInfo": {
      "name": "v18_builder",
      "title": "V18 Builder",
      "version": "1.0.0"
    },
    "capabilities": {
      "experimentalApi": true,
      "optOutNotificationMethods": ["item/agentMessage/delta"]
    }
  }
}
```

Subsequent requests before initialization return "Not initialized" error.

**Thread lifecycle:**

```json
// thread/start — create persistent thread
{
  "id": "1",
  "method": "thread/start",
  "params": {
    "model": "gpt-5.4",
    "cwd": "/path/to/project",
    "sandbox": "macos",
    "config": { "model_reasoning_effort": "high" }
  }
}
// Response: { "result": { "thread": { "id": "thread_abc123", "createdAt": ..., "updatedAt": ... } } }

// turn/start — send message, begins turn
{
  "id": "2",
  "method": "turn/start",
  "params": {
    "threadId": "thread_abc123",
    "input": [{"type": "text", "text": "Explain async/await in Python"}]
  }
}
// Response: { "result": { "turn": { "id": "turn_xyz789", "status": "inProgress" } } }

// turn/interrupt — cancel running turn (preserves session)
{
  "id": 31,
  "method": "turn/interrupt",
  "params": { "threadId": "thr_123", "turnId": "turn_456" }
}
// Response: { "id": 31, "result": {} }
// Then emits: turn/completed with status: "interrupted"
```

**Streaming notifications during a turn (verified):**

| Event | Payload | Use |
|---|---|---|
| `turn/started` | `{ turn }` with `turn.status = "inProgress"` | Turn begins running |
| `item/started` | per-item | Per-tool lifecycle — **used for orphan-tool detection** |
| `item/completed` | per-item | Matches a prior `item/started`; absence = orphan |
| `item/agentMessage/delta` | `{ turnId, delta }` | Streaming text chunks |
| `turn/diff/updated` | `{ threadId, turnId, diff }` | After every FileChange — aggregated unified diff |
| `turn/plan/updated` | `{ turnId, explanation?, plan }` | Plan revisions |
| `thread/tokenUsage/updated` | per thread | Token accounting |
| `model/rerouted` | `{ threadId, turnId, fromModel, toModel, reason }` | Backend rerouting (e.g., high-risk cyber safety) |
| `turn/completed` | `{ turn }` with `turn.status ∈ {completed, interrupted, failed}`, optional `turn.error` | Final |

**Python bindings (verified, from codex_app_server package):**

```python
from codex_app_server import Codex, AppServerClient, AppServerConfig

# High-level (simpler)
with Codex() as codex:
    thread = codex.thread_start(model="gpt-5.4", config={"model_reasoning_effort": "high"})
    result = thread.run("Say hello in one sentence.")
    print(result.final_response)

# Low-level (for orphan-tool detection, manual event handling)
config = AppServerConfig(
    codex_bin="/usr/local/bin/codex",
    config_overrides=("model=gpt-5.4", "sandbox=macos"),
    cwd="/path/to/project",
    env={"OPENAI_API_KEY": "sk-..."},
    client_name="v18_builder",
    experimental_api=True,
)
with AppServerClient(config=config) as client:
    client.start()
    init = client.initialize()
    thread = client.thread_start({"model": "gpt-5.4"})
    turn = client.turn_start(thread.thread.id, [{"type": "text", "text": "Hello!"}])
    completed = client.wait_for_turn_completed(turn.turn.id)
    # OR stream:
    for delta in client.stream_text(thread.thread.id, "What is 2+2?"):
        print(delta.delta, end="")
```

**Bug #20 plan §2a verification:** every API surface the Bug #20 plan relies on is present in the upstream spec — `thread/start`, `turn/start`, `turn/interrupt`, `item/started`, `item/completed`, `item/agentMessage/delta`, `turn/completed`, `turn/diff/updated`, `thread/tokenUsage/updated`. No changes required to the Bug #20 plan scope; Python bindings via `codex_app_server` package may reduce the implementation LOC from the original ~800 estimate.

### D.4 Implementation Map — Every Claude Agent Touchpoint

Complete enumeration of Claude-SDK usage in the builder, with current state and post-migration state:

| # | File:Line | Current | Target | Session |
|---|---|---|---|---|
| 1 | `cli.py:1698, 1994` (orchestrator) | ClaudeSDKClient | Keep — add `client.interrupt()` in wedge recovery | Session 18 |
| 2 | `cli.py:2292, 2332, 2485, 2701` (milestone sessions) | ClaudeSDKClient | Keep — add `client.interrupt()` | Session 18 |
| 3 | `cli.py:3359, 3980` (wave sessions `_execute_single_wave_sdk`) | ClaudeSDKClient | Keep — subscribe to streaming events for orphan-tool detection | Session 18 |
| 4 | `interviewer.py:682` (user interview) | ClaudeSDKClient | Keep — already correct pattern | — |
| 5 | `design_reference.py:208` (Firecrawl-only extraction) | ClaudeSDKClient | Keep — already correct pattern | — |
| 6 | `prd_agent.py` (PRD refinement) | ClaudeSDKClient | Keep — verify interrupt integration | Session 18 |
| 7 | `runtime_verification.py` | ClaudeSDKClient | Keep | — |
| 8 | **`audit_agent.py:81` (audit scorer)** | **`query()` one-shot** | **`ClaudeSDKClient` + `client.interrupt()` on timeout** | **Session 16.5** |
| 9 | **`audit_agent.py:294` (second audit path)** | **`query()` one-shot** | **`ClaudeSDKClient` + `client.interrupt()` on timeout** | **Session 16.5** |
| 10 | **`agents.py:1818-1821` (enterprise: architecture-lead Task() dispatch ×4)** | **`Task("architecture-lead", ...)` sub-agent** | **Python-orchestrated 4× separate `ClaudeSDKClient` sessions with full MCP via session-fork** | **Session 17** |
| 11 | **`agents.py:1832` (enterprise: coding-lead Task() per wave)** | **`Task("coding-lead", ...)`** | **Python-orchestrated per-wave `ClaudeSDKClient` session with full MCP (already true via `_execute_single_wave_sdk`; just drop the prompt instruction)** | **Session 17** |
| 12 | **`agents.py:1838` (enterprise: review-lead Task() dispatch)** | **`Task("review-lead", ...)`** | **Python-orchestrated review-lead session with full MCP** | **Session 17** |
| 13 | **`agents.py:1872-1875, 1882, 1889, 1895` (dept-head variants)** | **`Task("...-dept-head", ...)`** | **Python-orchestrated per-role session** | **Session 17** |

**After migration:** every Claude agent touchpoint uses `ClaudeSDKClient` bidirectionally with `mcp_servers` populated. No `query()` one-shot. No `Task()` sub-agent dispatch. Orphan-tool detection uniform across Claude and codex paths. Session forking provides history inheritance where multi-session workflows need conversation continuity.

### D.5 Migration Validation Checklist

Per-session exit criteria before moving to the next session:

**Session 16.5 exit (audit_agent.py migration):**
- [ ] `grep "async for msg in query\|async for message in query" src/` returns zero hits.
- [ ] AUDIT_REPORT.json unit tests pass (round-trip unchanged).
- [ ] `client.interrupt()` test fires and audit re-runs cleanly.

**Session 17 exit (Task() dispatch elimination):**
- [ ] `grep "Task(\"architecture-lead\|coding-lead\|coding-dept-head\|review-lead\|review-dept-head" src/` returns zero hits.
- [ ] Enterprise-mode unit tests pass with Python-orchestrated multi-session pattern.
- [ ] All sub-agent sessions verified via integration test to have `mcp__context7__*` in their allowed_tools.

**Session 18 exit (interrupt + orphan detection):**
- [ ] `client.interrupt()` called from wave watchdog on timeout (test with stall injection).
- [ ] Claude-path orphan-tool detector fires on AssistantMessage with ToolUseBlock not matched by ToolResultBlock within configured timeout.
- [ ] Bug #12 lesson respected: interrupt is the PRIMARY recovery, outer timeout is containment only.

**Session 15 exit (codex Bug #20):**
- [ ] `thread/start`, `turn/start`, `turn/interrupt` all exercised in unit tests.
- [ ] `item/started` / `item/completed` streaming subscription fires per-tool.
- [ ] `turn/completed` with `status: "interrupted"` observed after `turn/interrupt`.

### D.6 References

- Claude Agent SDK Python: `https://github.com/anthropics/claude-agent-sdk-python` (via context7 `/anthropics/claude-agent-sdk-python`, 12 snippets, High reputation).
- Claude Agent SDK docs mirror: `https://github.com/nothflare/claude-agent-sdk-docs` (via context7 `/nothflare/claude-agent-sdk-docs`, 821 snippets, Medium reputation — used for interrupt+session-fork examples).
- Codex CLI: `https://github.com/openai/codex` (via context7 `/openai/codex`, 870 snippets, High reputation).
- Codex app-server README: `https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md` (subsection of above).

All specifications above were verified via `context7.query-docs` calls during this investigation round. Re-verify via the same tool if SDK versions change.

End of Appendix D.
