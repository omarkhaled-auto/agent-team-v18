# MASTER IMPLEMENTATION PLAN v2 — No Interim Smokes, Context7 + Sequential-Thinking Mandatory

**Source of truth:** `docs/plans/2026-04-16-deep-investigation-report.md` (1,745 lines, reviewed + perfected).
**Secondary reference:** `docs/plans/2026-04-16-handoff-post-gate-a-deep-investigation.md` (972 lines).
**Repository:** `C:\Projects\agent-team-v18-codex`.
**Current baseline:** integration-2026-04-15-closeout HEAD `8ed55a4`; session-6-fixes-d02-d03 branch ahead by `c1030bb` + `61dd64d`; master at `89f460b` (PR #25 pending merge).
**Test baseline:** 9900 passed — no regressions allowed.

---

## THE MANDATE

Close EVERY finding in the deep investigation report:
- **17 N-items** (N-01 through N-17)
- **10 NEW-items** (NEW-1 through NEW-10)
- **4 latent wirings** (§3.1 D-02 consumer, §3.2 D-09 MCP preflight, §3.3 D-14 fidelity labels, §3.4 C-01 scope persistence)
- **PR #25 merge** (D-02 v2 + D-03 v2)
- **Original tracker Sessions 7-9 deferred items** (A-10/D-15/D-16/D-12/D-14/D-17/D-01/D-10)
- **Bug #20** codex app-server migration

**Nothing breaks. Nothing is missed. Report followed exactly.**

**Strategy change from v1:** No interim smoke gates. Implement everything carefully with context7 + sequential-thinking MCPs and exhaustive agent teams. Validate correctness through unit tests, offline replay against build-l's preserved state, and agent-driven cross-verification at each session. **One comprehensive smoke at the end (Session FINAL) validates the full pipeline.**

---

## INVIOLABLE RULES (memory calibrations — apply on EVERY session)

1. **Context7 + Sequential-Thinking MCPs are MANDATORY on every session.** Every agent team definition MUST include `context7` and `sequential-thinking` in the MCP servers. Every agent prompt MUST instruct use of these tools:
   - **Context7** for verifying current framework idioms, SDK specs, library APIs (NestJS 11, Prisma 5, Next.js 15, Claude Agent SDK, Codex app-server protocol, etc.). **No assumptions about framework behavior from training data** — verify with context7 before writing or reviewing code.
   - **Sequential-thinking** for multi-step investigation, root-cause analysis, complex refactors, and verification planning. Every architect/discovery agent uses it. Every implementation agent uses it when facing decisions with >2 viable paths.

2. **No containment patches** (`feedback_structural_vs_containment.md`) — never wrap a root cause in a timeout/retry. Every fix is structural.

3. **No "validated" without end-to-end proof** (`feedback_verification_before_completion.md`) — unit tests pass is necessary but NOT sufficient. Every session lands a production-caller-proof artifact at `v18 test runs/session-N-validation/` showing the feature actually fires on the hot path (via mock SDK, offline replay against preserved build state, or deterministic instrumentation).

4. **No in-flight fixes without authorization** (`feedback_inflight_fixes_need_authorization.md`) — if a defect is discovered mid-session, HALT. Branch + commit + PR + reviewer gate BEFORE continuing.

5. **Verify editable install before smoke** (`feedback_verify_editable_install_before_smoke.md`) — four pre-flight checks before the FINAL smoke: `pip show agent-team-v15`, `docker ps`, `which agent-team-v15`, `docker ps -a`.

6. **Investigation before implementation** — read actual code, find root causes, never assume. If a report says "X is broken at file:line," read that line first.

7. **Agents cannot be relied on to call tools voluntarily** — compliance-critical behavior is enforced deterministically by the orchestrator, not requested of agents.

8. **LLM-generated artifacts risk corruption** — prefer deterministic extraction (tree-sitter, regex parsing, explicit code reads) over LLM-generated equivalents.

9. **New features default OFF except where report specifies ON** — backward compatibility is a hard requirement.

10. **Persistence failures never crash the main pipeline** — all persistence-layer additions wrapped in try/except with logged warnings.

11. **The EXHAUSTIVE agent team pattern is mandatory for every session.** Discovery → parallel implementation → test engineering + wiring verification → final report. No session uses ad-hoc implementation.

12. **Every session starts with a sequential-thinking-driven architecture read.** The discovery agent uses sequential-thinking to walk the code systematically before producing the architecture report. No guessing, no skimming.

13. **Every session ends with the question:** "Would another instance of Claude or a senior Anthropic employee believe we honored the report exactly?" If no, fix it.

---

## CORRECTIONS FROM APPENDIX B THAT CHANGE THE WORK

These corrections from the report's confirmation round are NON-NEGOTIABLE:

1. **N-08 is NOT new primitive construction.** The audit-fix loop exists at `cli.py:5843-6037` (`_run_audit_loop`) AND is wired at `cli.py:4782` (production call site, gated by `config.audit_team.enabled` at `:4771`). Build-l's empty FIX_CYCLE_LOG.md is because (a) stock config sets `max_reaudit_cycles: 2` (only cycle 1 = audit-only possible), (b) `_run_audit_fix_unified` does NOT write to FIX_CYCLE_LOG.md (only other recovery paths do), (c) convergence recovery fires separately. **Revised N-08 scope: ~30 LOC observability + config tweak, not ~50 LOC wiring.**

2. **N-15 is NOT a simple persistence fix.** The scorer's raw JSON write has keys `schema_version, generated, milestone, audit_cycle, overall_score, max_score, verdict, threshold_pass, auditors_run, raw_finding_count, deduplicated_finding_count, findings, pass_notes, summary, score_breakdown, dod_results, fix_candidates, by_severity, by_category`. Python's `to_json()` emits different keys: `audit_id, timestamp, cycle, auditors_deployed, findings, score, by_severity, by_file, by_requirement, fix_candidates, scope, acceptance_tests`. **Only 4 keys overlap.** Fix: extend `to_json()` at `audit_models.py:267-280` to unpack `**self.extras` alongside canonical fields. **Revised LOC: ~10 LOC.**

3. **The 3-way port conflict is REJECTED.** M1 REQUIREMENTS.md says `:4000`. The scaffold frozen template says `:3001`. The endpoint_prober legacy default is `:3080`. The PRD doesn't explicitly specify a port.

4. **§5.9 PRD-conflict claim REJECTED.** The stock PRD doesn't explicitly specify `:4000` or `src/database`. Conflicts are between regenerated M1 REQUIREMENTS and frozen scaffold templates.

5. **§5.10 NEW root cause: MCP-blind wave execution.** Verified at `agents.py:5287-5290`: sub-agents dispatched via `Task()` have NO MCP access. Root cause of 8-finding Wave B LLM-bug cluster (AUD-009, -010, -012, -013, -016, -018, -020, -023). Addressed by N-17 + NEW-10.

6. **State.finalize silent-swallow** at `cli.py:13491-13495` has a bare `except Exception: pass`. Replace with `log.warning` (5 LOC added to NEW-7 scope).

7. **Taxonomy collapse: 28 findings → 18 actionable-distinct** (not 17 as handoff said).

8. **AUD-011 framing is wrong — it's a DUPLICATE module problem.** Build-l has BOTH `src/prisma/` AND `src/database/` populated. Addressed by N-04 (scaffold location correction) + NEW-1 (Wave B output sanitization for orphan files).

9. **Web scaffold gap is BIGGER than handoff said.** AUD-022 was framed as vitest.setup.ts only. Actually AUD-002 names 8+ missing files: `next.config.mjs`, `tsconfig.json`, `postcss.config.mjs`, `layout.tsx`, `page.tsx`, `middleware.ts`, `src/lib/api/client.ts`, `src/test/setup.ts`. N-06 scope is ~400 LOC (10 templates), not ~200 LOC.

10. **M1 REQUIREMENTS lists 62 files** under "Files to Create" (Appendix A corrects to 57-60 depending on section-header count — use MAX estimate).

---

## NEW STRUCTURE: 5 IMPLEMENTATION PHASES + 1 FINAL SMOKE

Instead of 15 sessions with 5 interim smokes, this is 5 implementation phases (each an atomic EXHAUSTIVE agent-team sprint using context7 + sequential-thinking) followed by one comprehensive smoke:

| Phase | Name | Scope | LOC | Cost |
|-------|------|-------|-----|------|
| **Phase A** | Foundation unlock | PR #25 merge + N-01 + N-15 + NEW-7 + NEW-8 + State.finalize warning | ~150 | $0 |
| **Phase B** | Scaffold + spec alignment | N-02 + N-03 + N-04 + N-05 + N-06 + N-07 + N-11 + N-12 + N-13 + NEW-1 + NEW-2 | ~1,800 | $0 |
| **Phase C** | Truthfulness + audit loop | N-08 + N-09 + N-10 + N-14 + N-17 + all latent wirings (§3.1/3.2/3.3/3.4) + D-14 fidelity labels | ~800 | $0 |
| **Phase D** | Original tracker cleanup | A-10 + D-15 + D-16 + D-12 + D-17 + D-01 + D-10 | ~400 | $0 |
| **Phase E** | NEW-10 full migration + Bug #20 | Session 16.5 + 17 + 18 (NEW-10) + Bug #20 codex app-server | ~1,290 | $0 |
| **Phase FINAL** | Single comprehensive smoke | Full M1-M6 enterprise smoke (Gate D) | 0 | $35-50 |

**Total:** ~4,440 LOC across 5 implementation phases + 1 smoke. Single paid validation at the end. Estimated **$35-50 total paid cost** (down from $125-130 with 5 interim smokes).

---

## PHASE A — FOUNDATION UNLOCK

**Goal:** merge PR #25, fix the bottleneck blockers (N-01 port resolution, N-15 scope persistence), and close the state truthfulness gaps (NEW-7 invariants, NEW-8 coercion logging, State.finalize warning).

**Total LOC:** ~150
- PR #25 merge: 0 (reviewer gate)
- N-01: ~35 LOC
- N-15: ~10 LOC
- NEW-7: ~60 LOC
- NEW-8: ~3 LOC
- State.finalize warning: ~5 LOC
- Tests + validation artifacts: ~35 LOC

**Risk:** LOW

### Agent Team (EXHAUSTIVE pattern)

```
Wave 1 (solo): architecture-discoverer
    MCPs: context7, sequential-thinking
    
    Reads (use sequential-thinking to walk systematically):
      - cli.py:530-651 (_apply_evidence_gating_to_audit_report)
      - cli.py:13491-13495 (State.finalize silent-swallow)
      - audit_models.py:234-380 (AuditReport + to_json + from_json + extras)
      - endpoint_prober.py:1023-1036 (_detect_app_url)
      - state.py (full) — every mutation site
      - build-l's preserved AUDIT_REPORT.json (confirm scope field absence)
      - build-l's preserved STATE.json (confirm summary.success=True + failed_milestones inconsistency)
    
    Uses context7:
      - Verify Python's json module behavior for extras merging
      - Verify any regex patterns needed for PORT detection
    
    Produces: PHASE_A_ARCHITECTURE_REPORT.md with:
      - Exact write-path trace for AUDIT_REPORT.json
      - All state mutation sites enumerated
      - Port detection source precedence table
      - Invariant validation points

Wave 2 (parallel, 3 agents):
  n01-n15-implementer: 
    Files: endpoint_prober.py, audit_models.py, tests/test_endpoint_prober.py, tests/test_audit_models.py
    MCPs: context7, sequential-thinking
  
  state-invariants-implementer:
    Files: state.py, cli.py:13491-13495, tests/test_state.py
    MCPs: sequential-thinking
  
  coercion-logging-implementer:
    Files: audit_models.py:352-356, tests/test_audit_models.py
    MCPs: sequential-thinking
    NOTE: Coordinate with n01-n15-implementer on audit_models.py edits (different sections — n01-n15 edits :267-280 to_json; coercion-logging edits :352-356 from_json). Non-conflicting via str_replace.

Wave 3 (parallel):
  test-engineer: writes all tests, runs pytest, iterates
  wiring-verifier: traces production call paths for each change
    MCPs: sequential-thinking (for multi-step trace)

Wave 4: test-engineer runs full suite pytest tests/ -v --tb=short
Wave 5: team lead writes PHASE_A_REPORT.md + validation artifact at session-A-validation/
```

### Implementation Details

**N-01 — endpoint_prober._detect_app_url port resolution**

File: `src/agent_team_v15/endpoint_prober.py:1023-1036`

Current behavior (per Appendix A §3F):
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

Add reads (IN PRECEDENCE ORDER, BEFORE fallback):
1. `apps/api/.env.example` → `PORT=<n>`
2. `apps/api/src/main.ts` → regex `app\.listen\s*\(\s*(\d+)`
3. `docker-compose.yml` → parse `services.api.ports` mapping

Simple regex only. NO AST parsing (report explicit). Each source wrapped in try/except with debug log on failure. Loud `log.warning` only when all sources fail and `:3080` is used.

Tests (add to `tests/test_endpoint_prober.py`):
- test_detect_from_apps_api_env_example
- test_detect_from_main_ts_listen_call
- test_detect_from_docker_compose_api_ports
- test_fallback_warning_when_all_sources_fail
- test_precedence_order

**N-15 — C-01 scope persistence via extras unpacking**

File: `src/agent_team_v15/audit_models.py:267-280` (`to_json` method)

Extend to unpack `**self.extras` alongside canonical fields. Per Appendix B.2.2: `extras` populated at `audit_models.py:342` with filtered scorer-extras — no aliasing risk.

Tests:
- test_to_json_preserves_extras (roundtrip)
- test_to_json_scope_field_present_after_gating (end-to-end with _apply_evidence_gating_to_audit_report mock)
- test_audit_report_roundtrip_buildl (load build-l's actual AUDIT_REPORT.json → from_json → to_json → confirm no key loss)

**NEW-7 — State write-side invariants**

Files: `src/agent_team_v15/state.py`

Invariants enforced at write time (before save):
- `summary.success == (not interrupted and len(failed_milestones) == 0)`
- `audit_health in {"", "passed", "failed", "partial", "unverified"}`
- `audit_score >= 0.0`
- `completed_waves` and `failed_wave` are mutually exclusive per milestone

Mutations to audit:
- `State.update_milestone_status()` 
- `State.mark_wave_completed()`
- `State.mark_wave_failed()`
- `State.save()`

On invariant violation: log ERROR + raise `StateInvariantError` (new exception class).

**State.finalize silent-swallow fix (Appendix B.2.3):**

File: `src/agent_team_v15/cli.py:13491-13495`

```python
# Before
try:
    _current_state.finalize(...)
except Exception:
    pass  # Best-effort

# After
try:
    _current_state.finalize(...)
except Exception as e:
    log.warning(f"State.finalize failed: {e}", exc_info=True)
```

Tests:
- test_summary_success_recomputed_on_failure
- test_invariant_error_raised_on_inconsistent_write
- test_state_finalize_logs_warning_on_failure
- test_save_validates_invariants_before_write
- test_state_invariant_error_does_not_crash_pipeline

**NEW-8 — fix_candidates coercion logging**

File: `src/agent_team_v15/audit_models.py:352-356`

Current:
```python
[id_to_idx[fid] for fid in data.get('fix_candidates', []) if fid in id_to_idx]
```

Before list comprehension: compute `dropped = [fid for fid in raw if fid not in id_to_idx]`. If `len(dropped) > 0`: `log.warning(f"Dropped {len(dropped)} unresolvable fix_candidate IDs: {dropped}")`.

Test: test_fix_candidates_warns_on_dropped_ids

### PR #25 Merge

Branch: `session-6-fixes-d02-d03`
Commits: `c1030bb` (D-02 v2), `61dd64d` (D-03 v2)
**Reviewer gate required. Do not self-approve.**

### Phase A Exit Criteria

- [ ] PR #25 merged to `integration-2026-04-15-closeout`
- [ ] N-01 implemented with tests + roundtrip test against build-l preserved fixtures
- [ ] N-15 implemented with roundtrip test against build-l's actual AUDIT_REPORT.json
- [ ] State invariants enforced at write time
- [ ] State.finalize warning replacing bare pass
- [ ] fix_candidates coercion logs dropped IDs
- [ ] Full test suite passes (9900 → ~9930)
- [ ] PHASE_A_ARCHITECTURE_REPORT.md captured
- [ ] Production-caller-proof artifact at `v18 test runs/session-A-validation/` (mock SDK walks write path for AUDIT_REPORT.json; proves extras merged; proves invariants raise)
- [ ] PHASE_A_REPORT.md written

---

## PHASE B — SCAFFOLD + SPEC ALIGNMENT

**Goal:** close the three-layer ownership ambiguity (biggest structural gap per §5.1). Close 10+ scaffold-gap findings. Align scaffold templates with current M1 REQUIREMENTS. Add scaffold self-verification gate. Suppress cascade findings.

**Total LOC:** ~1,800
- N-02 ownership contract + parser + 3 consumer updates: ~250 LOC
- N-03 packages/shared emission: ~120 LOC
- N-04 Prisma location reconciliation: ~20 LOC
- N-05 Prisma initial migration: ~40 LOC
- N-06 web scaffold completeness (10 templates): ~400 LOC
- N-07 full docker-compose: ~150 LOC
- N-11 cascade finding suppression: ~150 LOC
- N-12 unified milestone SPEC.md reconciliation: ~200 LOC
- N-13 scaffold self-verification gate: ~250 LOC
- NEW-1 duplicate Prisma cleanup: ~40 LOC
- NEW-2 scaffold template freshness: ~40 LOC
- Tests: ~140 LOC

**Risk:** MEDIUM (cross-layer change touching scaffold + wave prompts + audit expectations)

### Agent Team (EXHAUSTIVE pattern)

```
Wave 1 (solo): architecture-discoverer
    MCPs: context7, sequential-thinking
    
    Sequential-thinking task: walk scaffold_runner.py end-to-end. 
    For every file the scaffold emits, document its source (hardcoded vs derived vs config-driven).
    For every file M1 REQUIREMENTS expects, document who currently owns it.
    
    Reads:
      - scaffold_runner.py (full — 900+ LOC)
      - ownership_validator.py (existing 312 LOC — NOT greenfield, we extend)
      - build-l's preserved REQUIREMENTS.md
      - audit_team.py:317-332 (auditor scope wrapper)
      - audit_scope.py:109-140 (scope template)
      - cli.py:530-651 (_apply_evidence_gating_to_audit_report for cascade suppression)
      - agents.py:7879-8049 (build_wave_b_prompt)
      - Build-l's preserved scaffold output and actual file tree
    
    Uses context7:
      - NestJS 11 workspace/monorepo conventions
      - Prisma 5 migration file format specs
      - Next.js 15 app-router minimum file structure
      - pnpm workspace YAML schema
      - Docker Compose healthcheck syntax
    
    Produces: PHASE_B_ARCHITECTURE_REPORT.md with:
      - Complete file-by-file ownership table (extends Part 6A of investigation report)
      - 13 no-owner files identified (per report)
      - 2 conflicting-owner files identified
      - Scaffold template drift list (all baked-stale values)
      - Cascade finding detection mechanism
      - Scaffold self-verification check list

Wave 2 (parallel, 6 implementation agents — NO FILE OVERLAP):

  n02-ownership-impl:
    Files: docs/SCAFFOLD_OWNERSHIP.md (NEW), scaffold_runner.py (parser ADD only), 
           ownership_validator.py (EXTEND), audit_team.py (add optional-file check), 
           agents.py (add "files you own" injection in wave prompts)
    MCPs: context7, sequential-thinking
    
  n03-shared-impl:
    Files: scaffold_runner.py (new method _scaffold_packages_shared), 
           pnpm-workspace.yaml template update, tsconfig.base.json path mapping
    MCPs: context7, sequential-thinking
    
  n04-n05-prisma-impl:
    Files: scaffold_runner.py (path change src/prisma→src/database, 
           new method _scaffold_prisma_migrations)
    MCPs: context7 (for Prisma 5 migration format), sequential-thinking
    
  n06-web-scaffold-impl:
    Files: scaffold_runner.py (extend _scaffold_web_foundation with 10 new templates)
    MCPs: context7 (for Next.js 15 app-router), sequential-thinking
    
  n07-docker-impl:
    Files: scaffold_runner.py (extend _docker_compose_template with api+web services)
    MCPs: context7 (Docker Compose healthcheck syntax), sequential-thinking
    
  n12-n13-reconciliation-impl:
    Files: milestone_spec_reconciler.py (NEW), scaffold_verifier.py (NEW),
           cli.py (wire reconciliation + verification into pipeline flow)
    MCPs: context7, sequential-thinking
    
  ALL FILE EDITS coordinated via team lead — every scaffold_runner.py edit
  targets a DIFFERENT method or extends _scaffold_m1_foundation at a different 
  extension point. n02's parser is standalone new code.

Wave 3 (parallel):
  n11-cascade-impl + NEW-1-cleanup-impl + NEW-2-drift-impl:
    Files: cli.py:530-651 (n11 cascade suppression),
           wave_executor.py post-Wave-B hook (NEW-1 duplicate cleanup),
           scaffold_runner.py (NEW-2 template version-stamping)
    MCPs: sequential-thinking
  
  test-engineer: writes ALL tests for N-02/03/04/05/06/07/11/12/13 + NEW-1 + NEW-2
  wiring-verifier: traces scaffold → wave B prompt → audit expectations
    MCPs: sequential-thinking

Wave 4: test-engineer runs pytest
Wave 5: team lead writes PHASE_B_REPORT.md
```

### Implementation Details

**N-02 — Three-Layer Ownership Contract**

Deliverable 1: `docs/SCAFFOLD_OWNERSHIP.md` — canonical YAML table per Part 6A of investigation report. 57-60 entries.

Deliverable 2: Parser in `scaffold_runner.py`:
```python
@dataclass
class OwnershipContract:
    files: list[FileOwnership]
    def files_for_owner(self, owner: str) -> list[FileOwnership]
    def is_optional(self, path: str) -> bool

def load_ownership_contract() -> OwnershipContract
```

Deliverable 3: Consumer updates (3 sites):
1. Scaffold: verifies it emits exactly the files assigned to `scaffold` owner
2. Wave B/D prompt builder: injects "files you own" section
3. Auditor: suppresses "missing file" finding when `contract.is_optional(path)` or deferred-to-M2+

Feature flag: `v18.ownership_contract_enabled: bool = False` (default OFF until Phase FINAL smoke validates).

**N-03 — packages/shared emission**

New method: `_scaffold_packages_shared()`. Files (per M1 REQUIREMENTS lines 546-552):
- `packages/shared/package.json`
- `packages/shared/tsconfig.json`
- `packages/shared/src/enums.ts` (UserRole, ProjectStatus, TaskStatus, TaskPriority)
- `packages/shared/src/error-codes.ts` (ErrorCodes map of 11 keys)
- `packages/shared/src/pagination.ts` (PaginationMeta, PaginatedResult<T>)
- `packages/shared/src/index.ts` (barrel)

Also update: root `pnpm-workspace.yaml` include + `tsconfig.base.json` path mapping `@org/shared`.

Exact constants from M1 REQUIREMENTS — do NOT invent.

**N-04 — Prisma location**

Scaffold template: `src/prisma/` → `src/database/`. Wave B prompt reminder updated. Use M1 REQUIREMENTS canonical choice.

**N-05 — Prisma initial migration**

Canned stub (NOT `prisma migrate dev` subprocess — avoids postgres runtime dependency):
- `apps/api/prisma/migrations/20260101000000_init/migration.sql`
- `apps/api/prisma/migrations/migration_lock.toml`

Sequencing: AFTER schema.prisma emission.

**N-06 — Web scaffold completeness**

10 new templates (~40 LOC each):
1. `apps/web/next.config.mjs`
2. `apps/web/tsconfig.json`
3. `apps/web/postcss.config.mjs`
4. `apps/web/openapi-ts.config.ts`
5. `apps/web/.env.example`
6. `apps/web/Dockerfile`
7. `apps/web/src/app/layout.tsx` (stub — Wave D finalizes)
8. `apps/web/src/app/page.tsx` (stub)
9. `apps/web/src/middleware.ts` (stub)
10. `apps/web/src/test/setup.ts`

Also: fix `apps/web/vitest.config.ts` missing `setupFiles` reference (closes AUD-022).

Stub files marked `emits_stub: true` in ownership contract so Wave D knows to finalize (not re-create).

**N-07 — Full docker-compose**

Extend `_docker_compose_template` to add `api` + `web` services. Healthchecks per Docker Compose spec (verify with context7). Port 4000 for api (matches M1 REQUIREMENTS).

**N-11 — Cascade finding suppression**

File: `cli.py:530-651` (`_apply_evidence_gating_to_audit_report`)

Inject `state.wave_progress` into scope_payload. Filter findings whose "location" targets skipped-wave output. Emit single meta-finding "Upstream Wave B failure cascaded to downstream waves" instead of 5 separate AUD-002-class findings.

Per Appendix A: consolidation-level preferred over prompt-level (~150 LOC).

**N-12 — Unified milestone SPEC.md reconciliation**

New phase at milestone entry: deterministic merger produces `.agent-team/milestones/<id>/SPEC.md` combining:
- M1 REQUIREMENTS.md (regenerated from PRD)
- Relevant PRD excerpts (per-milestone scope)
- Stack-contract derivations
- Ownership contract assignments (N-02)

Consumers read from SPEC.md: scaffold, Wave prompts, auditor — single source of truth.

Conflicts → emit `RECONCILIATION_CONFLICTS.md`, halt with `reconciliation_arbitration_required` recovery type.

**N-13 — Scaffold self-verification gate**

New module: `scaffold_verifier.py` (~250 LOC per Appendix A).

Validates after scaffold emission, BEFORE Wave B dispatch:
- `package.json` valid JSON; workspaces globs resolve to emitted dirs
- `tsconfig.base.json` paths resolve
- `docker-compose.yml` valid YAML; services reference buildable contexts
- `prisma/schema.prisma` parseable (subprocess `pnpm prisma validate`)
- **Port consistency** across emissions: env.validation.ts PORT == docker-compose api PORT == .env.example PORT == M1 REQUIREMENTS DoD port

Fail fast on any check failure.

**NEW-1 — Duplicate Prisma module cleanup**

After Wave B compile, deterministic cleanup removes unused Prisma module path. Grep-based consumer detection.

**NEW-2 — Scaffold template freshness**

Template version-stamping + drift detection. Compare template version against current REQUIREMENTS; warn on drift; fail on major mismatch.

### Phase B Exit Criteria

- [ ] docs/SCAFFOLD_OWNERSHIP.md with 57-60 entries
- [ ] Ownership parser + 3 consumer updates (flag gated)
- [ ] All 6 scaffold emissions working (shared, migrations, web x10, docker)
- [ ] Prisma location aligned to src/database/
- [ ] Cascade suppression working against build-l preserved state (offline replay)
- [ ] SPEC.md reconciliation phase implemented
- [ ] Scaffold verifier gating Wave B dispatch
- [ ] NEW-1 duplicate cleanup tested against build-l's duplicate Prisma
- [ ] NEW-2 template drift detection
- [ ] Scaffold-dump diff captured
- [ ] Full test suite passes (~9930 → ~10,050+)
- [ ] PHASE_B_ARCHITECTURE_REPORT.md captured
- [ ] Production-caller-proof artifact at `session-B-validation/` (mock-SDK walk of scaffold + verification + reconciliation + cascade suppression against build-l preserved state)
- [ ] PHASE_B_REPORT.md written

---

## PHASE C — TRUTHFULNESS + AUDIT LOOP

**Goal:** make the existing audit-fix loop observable and useful. Inject current framework idioms into wave prompts. Close 8 Wave B LLM-bug findings structurally. Plug all 4 latent wirings. Add content-level scope enforcement. Add D-14 fidelity labels.

**Total LOC:** ~800
- N-08 observability + config tweak: ~30 LOC
- N-09 Wave B prompt hardeners (both Claude and Codex paths): ~400 LOC
- N-10 post-wave content auditor: ~300 LOC
- N-17 MCP-informed wave dispatches: ~100 LOC
- N-14 production-caller proof (process): ~0 LOC code + template doc
- §3.1 D-02 v2 consumer-side fail-loud halt: ~40 LOC
- §3.2 D-09 MCP pre-flight wiring: ~40 LOC
- §3.3 D-14 fidelity labels on 4 verification artefacts: ~80 LOC
- Tests: ~100 LOC (§3.4/N-15 already done in Phase A)

**Risk:** MEDIUM (touches audit loop, wave prompts, and recovery paths)

### Agent Team (EXHAUSTIVE pattern)

```
Wave 1 (solo): architecture-discoverer
    MCPs: context7, sequential-thinking
    
    Sequential-thinking: walk the audit loop end-to-end. Walk every recovery path.
    For each latent wiring, identify the exact insertion point.
    
    Reads:
      - cli.py:5843-6037 (_run_audit_loop — confirm IS wired per Appendix B.2.1)
      - cli.py:5605-5700+ (_run_audit_fix_unified)
      - cli.py:4782 (production call site, gated at :4771 config.audit_team.enabled)
      - cli.py:6087, 6254, 6349 (recovery paths that DO write to FIX_CYCLE_LOG.md)
      - fix_executor.py:312-389 (execute_unified_fix_async)
      - audit_models.py:762-806 (group_findings_into_fix_tasks)
      - audit_models.py:533-544 (FixTask dataclass)
      - mcp_servers.py:429-482, :485-523 (D-09 helpers — zero callers)
      - runtime_verification.py (for D-14 fidelity headers)
      - endpoint_prober.py:119, :704, :716, :891-1000 (D-02 v2)
      - wave_executor.py:1640-1648 (D-02 v2 skip-vs-block decision)
      - cli.py:12759 (D-02 v2 consumer-side)
      - wave_executor.py:3318 (where A-09 scope check fires — N-10 insertion point)
      - agents.py:7879-8049 (build_wave_b_prompt — Claude)
      - codex_prompts.py:10-68 (CODEX_WAVE_B_PREAMBLE — Codex)
      - agents.py:5287-5290 (verbatim MCP-stripping comment for N-17 context)
    
    Uses context7:
      - NestJS 11 current idioms for each N-09 pattern (filter registration, ConfigService, Swagger, URL prefix, openapi-generator globals)
      - Prisma 5 shutdown hook pattern
      - Next.js 15 middleware patterns
      - For every Wave B bug (AUD-009/010/012/013/016/018/020/023): query current-framework best practice
    
    Produces: PHASE_C_ARCHITECTURE_REPORT.md with:
      - Audit loop call graph (verifies Appendix B.2.1 correction)
      - Per-Wave-B-bug current-idiom reference (context7-sourced)
      - All 4 latent wiring insertion points
      - N-17 context7 query set per milestone template

Wave 2 (parallel, 5 implementation agents):
  n08-observability-impl:
    Files: cli.py (add FIX_CYCLE_LOG.md write in _run_audit_fix_unified matching pattern from :6087/:6254/:6349), config.py (bump max_reaudit_cycles default + new flag v18.audit_fix_iteration_enabled)
    MCPs: sequential-thinking
  
  n09-prompt-hardeners-impl:
    Files: agents.py:7879-8049 (Claude Wave B prompt), codex_prompts.py:10-68 (Codex preamble)
    MCPs: context7 (for verified current idioms), sequential-thinking
  
  n10-content-auditor-impl:
    Files: wave_executor.py (insertion near :3318), quality_checks.py (new scanner class),
           REQUIREMENTS generator (add forbidden_content section)
    MCPs: context7, sequential-thinking
  
  n17-mcp-prefetch-impl:
    Files: cli.py (new _prefetch_framework_idioms function), 
           agents.py (prompt injection hook),
           codex_prompts.py (prompt injection hook),
           config.py (new flag v18.mcp_informed_dispatches_enabled default True)
    MCPs: context7, sequential-thinking
  
  latent-wiring-impl:
    Files: cli.py:12759 (D-02 halt diagnostic), cli.py (D-09 preflight call sites),
           runtime_verification.py + 3 other artefact writers (D-14 fidelity headers)
    MCPs: sequential-thinking

Wave 3 (parallel):
  test-engineer: writes ALL tests
    MCPs: sequential-thinking
  wiring-verifier: traces every change end-to-end using mock SDK
    MCPs: sequential-thinking

Wave 4: test-engineer runs pytest
Wave 5: team lead writes PHASE_C_REPORT.md
```

### Implementation Details

**N-08 — Audit-Fix Loop Observability + Validation**

PER APPENDIX B.2.1: loop is ALREADY WIRED at `cli.py:4782`. Build-l's empty FIX_CYCLE_LOG is NOT a wiring bug.

Three fixes:
1. Add FIX_CYCLE_LOG.md append in `_run_audit_fix_unified` (match pattern from `cli.py:6087, 6254, 6349`). ~15 LOC.
2. Bump `max_reaudit_cycles` default 2→3 in stock config. Align with code default. ~5 LOC.
3. New flag `v18.audit_fix_iteration_enabled: bool = False` (default OFF until Phase FINAL validates). ~10 LOC.

Tests:
- test_fix_cycle_log_written_on_cycle_2
- test_max_reaudit_cycles_default_is_3
- test_audit_fix_iteration_flag_default_off
- test_offline_replay_buildl_state_through_audit_fix (critical — uses build-l's preserved state with mocked SDK to prove cycle 2 dispatches fix agents)

**N-09 — Wave B prompt hardeners**

8 hardeners (per investigation Part 4 N-09 analysis), applied to BOTH Claude (`agents.py:7879-8049`) and Codex (`codex_prompts.py:10-68`) paths:

- AUD-009 `AllExceptionsFilter`: "register globally OR via APP_FILTER, not both"
- AUD-010 `getOrThrow` vs `.get`: prompt stresses `.get` with default
- AUD-012 bcrypt: resolve spec disagreement (M1 allows JWT shell without bcrypt; clarify M2+ scope)
- AUD-013 ErrorCodes: require `ErrorCodes` import and usage
- AUD-016 Swagger Object typing: specify explicit type
- AUD-018 generate-openapi globals: stress global wiring reuse
- AUD-020 URL-prefix: specify decorator over `setGlobalPrefix`-skip
- AUD-023 e2e mock: require real DB integration

Each hardener MUST cite context7-verified current idiom (researcher agent uses context7 to confirm before writing the hardener).

Scope reduced from originally estimated ~300-400 LOC because N-17 (which goes in parallel) handles current-idiom injection at runtime. N-09 focuses on pattern-level text hardeners. ~400 LOC across both paths.

**N-10 — Post-wave content auditor**

New deterministic scanner in `quality_checks.py`. Extends existing Violation dataclass pattern.

REQUIREMENTS generator adds structured `forbidden_content: list[str]` section:
```yaml
forbidden_content:
  - 'from @/modules/tasks'  # M2 scope
  - 'class TaskController'   # M4 scope
  - 'projectsService\.'      # M3 scope
```

Scanner extends post-wave validator near `wave_executor.py:3318` (where A-09 scope check fires). Scans Wave B/D output against forbidden_content regex list. Violations = warnings on WaveResult.

~300 LOC per Appendix A.

**N-17 — MCP-informed wave dispatches**

PER APPENDIX C.3: at orchestrator layer, BEFORE each Wave B/D dispatch, call context7 for current framework idioms.

```python
async def _prefetch_framework_idioms(
    wave: str, 
    milestone_template: str,
    mcp_client: MCPClient,
) -> dict[str, str]:
    query_set = {
        "B": {
            "full_stack": ["nestjs 11 module", "prisma 5 client", "class-validator 0.14"],
            "backend_only": ["nestjs 11 module", "prisma 5 client"],
        },
        "D": {
            "full_stack": ["next.js 15 app router", "@hey-api/openapi-ts", "react 19"],
            "frontend_only": ["next.js 15 app router", "@hey-api/openapi-ts", "react 19"],
        },
    }
    # ... query and cache ...
```

Inject as `[CURRENT FRAMEWORK IDIOMS]` section BEFORE task manifest in Wave B/D prompts. Cache per-milestone under `.agent-team/framework_idioms_cache.json`.

Flag: `v18.mcp_informed_dispatches_enabled: bool = True` (default ON per report).

**N-14 — Production-caller proof (process)**

Not code. Template doc at `docs/session-validation-template.md` describing required artifact per session: small script mocking SDK, walking production call chain, asserting feature fires.

**Latent wiring §3.1 — D-02 v2 consumer-side fail-loud**

File: `cli.py:12759`

Current: treats `blocked` via same generic recovery-append as `skipped`. No legible halt diagnostic.

Fix: add explicit `if health == "blocked"` branch that raises `RuntimeBlockedError` with host-port diagnostic from `endpoint_prober._detect_unbound_host_ports()`. ~40 LOC.

**Latent wiring §3.2 — D-09 MCP pre-flight**

Files: `mcp_servers.py:429-482` (`run_mcp_preflight`), `:485-523` (`ensure_contract_e2e_fidelity_header`). Zero callers confirmed.

Add call sites:
1. Pipeline startup: call `run_mcp_preflight` before Wave execution starts
2. CONTRACT_E2E_RESULTS.md writer: call `ensure_contract_e2e_fidelity_header`

~40 LOC.

**Latent wiring §3.3 — D-14 fidelity labels**

Generalize D-09's fidelity-header helper across 4 verification artefacts:
- `RUNTIME_VERIFICATION.md`
- `VERIFICATION.md`
- `CONTRACT_E2E_RESULTS.md`
- `GATE_FINDINGS.json`

Each carries explicit fidelity tag (runtime | static | heuristic). ~80 LOC.

### Phase C Exit Criteria

- [ ] FIX_CYCLE_LOG.md append wired in _run_audit_fix_unified
- [ ] max_reaudit_cycles default aligned
- [ ] v18.audit_fix_iteration_enabled flag added
- [ ] Offline replay test passes using build-l's preserved state (confirms cycle 2 dispatches)
- [ ] 8 N-09 hardeners in both Claude and Codex paths (context7-verified idioms)
- [ ] N-10 content auditor scanning forbidden_content
- [ ] N-17 context7 pre-fetch + prompt injection with caching
- [ ] D-02 v2 RuntimeBlockedError halt diagnostic
- [ ] D-09 MCP pre-flight wired at 2 call sites
- [ ] D-14 fidelity labels on 4 verification artefacts
- [ ] N-14 session-validation template doc
- [ ] Full test suite passes (~10,050 → ~10,150)
- [ ] PHASE_C_ARCHITECTURE_REPORT.md captured
- [ ] Production-caller-proof at `session-C-validation/` (mock-SDK walk for audit-fix cycle 2 + context7 injection + latent wirings firing)
- [ ] PHASE_C_REPORT.md written

---

## PHASE D — ORIGINAL TRACKER CLEANUP

**Goal:** close remaining pre-closeout tracker items (Sessions 7-9 from original tracker).

**Total LOC:** ~400
- A-10 + D-15 + D-16 compile-fix + fallback: ~150 LOC
- D-12 Codex last_sdk_tool_name blank: ~50 LOC (obsoleted for Codex path by Phase E; still needed for Claude path)
- D-17 truth-score calibration: ~60 LOC
- D-01 context7 quota pre-flight: ~80 LOC
- D-10 phantom integrity FP suppression: ~40 LOC
- D-14 fidelity labels: already done in Phase C §3.3
- Tests: ~20 LOC

**Risk:** HIGH for A-10 (recovery hot-path); LOW for telemetry

### Agent Team (EXHAUSTIVE pattern)

```
Wave 1 (solo): architecture-discoverer
    MCPs: context7, sequential-thinking
    
    Reads:
      - docs/plans/2026-04-15-a-10-compile-fix-budget-investigation.md (MUST read first)
      - Compile-fix loop in cli.py / wave_executor.py
      - Codex telemetry capture (for D-12)
      - Truth-scoring calibration tables (for D-17)
      - Context7 client (for D-01)
      - Integrity checker (for D-10)
    
    Uses context7:
      - No external framework verification needed — this is internal tracker work
    
    Produces: PHASE_D_ARCHITECTURE_REPORT.md

Wave 2 (parallel):
  a10-d15-d16-impl: compile-fix hot path (HIGH risk — investigation-first)
  d12-impl: Claude-path last_sdk_tool_name capture
  d17-impl: truth-score calibration table update
  d01-impl: context7 quota pre-flight with TECH_RESEARCH.md stub
  d10-impl: integrity checker FP suppression

Wave 3: test-engineer + wiring-verifier
Wave 4: pytest
Wave 5: PHASE_D_REPORT.md
```

### Implementation Details

**A-10 + D-15 + D-16 — Compile-fix + fallback**

READ THE INVESTIGATION DOC FIRST: `docs/plans/2026-04-15-a-10-compile-fix-budget-investigation.md`. Do not guess.

Likely fixes:
- Budget cap raised on fallback path
- Structural triage pass (inspect `package.json`/`tsconfig.json`/top-level configs) BEFORE entering per-file diff loop
- Iteration context bleed cleanup
- Complete fallback output check

Acceptance: compile-fix can handle 5+ iterations without exhaustion cascade.

**D-12 — Codex last_sdk_tool_name**

Finalize-timing bug. Capture tool name at `item/started` boundary, not at teardown. Obsoleted for Codex path by Phase E Bug #20 (uses `item/started` streaming events naturally). Still needed for Claude path (addressed structurally by Phase E NEW-10 Step 4 streaming orphan detection).

**D-17 — Truth-score calibration**

Update calibration table:
- `error_handling=0.06` → recalibrate for framework-level global exception filter pattern
- `test_presence=0.29` on M1 when spec requires empty placeholder → handle "spec requires empty" case

Data from build-j + build-l.

**D-01 — Context7 quota pre-flight**

Builder pre-probes context7 quota. On quota failure, emit `TECH_RESEARCH.md` stub instead of silent omission. Graceful degradation.

**D-10 — Phantom integrity finding**

Integrity checker per-run FP suppression list. DB-004 was re-raised across fix cycles in build-j.

### Phase D Exit Criteria

- [ ] A-10 investigation completed; fix landed (5+ iterations without cascade)
- [ ] D-12 Claude-path tool name captured correctly
- [ ] D-17 calibration table updated from build-j + build-l data
- [ ] D-01 context7 quota pre-flight with TECH_RESEARCH.md stub
- [ ] D-10 integrity FP suppression
- [ ] Full test suite passes (~10,150 → ~10,170)
- [ ] PHASE_D_ARCHITECTURE_REPORT.md captured
- [ ] Production-caller-proof at `session-D-validation/`
- [ ] PHASE_D_REPORT.md written

---

## PHASE E — NEW-10 FULL MIGRATION + BUG #20

**Goal:** migrate EVERY Claude agent to `ClaudeSDKClient` with full MCP access. Eliminate `Task("sub-agent")` dispatch. Wire `client.interrupt()` into wave watchdog. Subscribe to streaming events for orphan detection. In parallel (on Codex side), migrate Codex transport to app-server JSON-RPC.

**Total LOC:** ~1,290
- Session 16.5 — NEW-10 Step 1 (audit_agent.py query→ClaudeSDKClient): ~60 LOC
- Session 17 — NEW-10 Step 2 (eliminate Task() dispatch in enterprise mode): ~250 LOC
- Session 18 — NEW-10 Step 3+4 (client.interrupt + streaming orphan detection): ~180 LOC
- Bug #20 — Codex app-server migration: ~800 LOC + 20 tests

**Risk:** MEDIUM-HIGH (hot-path; new transport layer; architectural change for enterprise mode)

### Agent Team (EXHAUSTIVE pattern — EXTENDED)

This phase is big enough that Wave 2 has SEQUENTIAL sub-waves (not parallel) for NEW-10 Steps 1→2→3+4. Bug #20 runs in parallel with NEW-10 Step 1 since they touch different transport paths.

```
Wave 1 (solo): architecture-discoverer
    MCPs: context7, sequential-thinking
    
    Sequential-thinking task: walk ClaudeSDKClient usage across all 6 files 
    (orchestrator, milestone, wave sessions, interviewer, design-reference, runtime_verification, prd_agent).
    Walk every Task() dispatch in enterprise mode.
    Walk codex_transport.py end-to-end.
    
    Reads (use context7 for every SDK call and every RPC method):
      - audit_agent.py:81, 294 (query() one-shot pattern)
      - agents.py:1818-1895 (enterprise-mode Task() dispatches)
      - cli.py:33, 684, 692, 774, 791, 822, 1698, 1994, 2292, 2332, 2485, 2701, 3359, 3980 (ClaudeSDKClient call sites)
      - wave_executor.py _WaveWatchdogState
      - codex_transport.py (full — 760 LOC)
      - docs/plans/2026-04-15-bug-20-codex-appserver-migration.md (MUST read — contains verified spec)
      - Appendix D of investigation report (verified SDK specs)
    
    CRITICAL context7 verifications (Appendix D):
      - ClaudeSDKClient bidirectional pattern
      - client.interrupt() API signature
      - query() with fork_session=True semantics
      - receive_response() message/content block types (AssistantMessage, ToolUseBlock, ToolResultBlock)
      - HookMatcher / create_sdk_mcp_server / ClaudeAgentOptions
      - Codex app-server initialize RPC
      - Codex turn/submit + turn/interrupt RPCs
      - Codex item/started + item/completed + tokenUsage/updated notifications
    
    Produces: PHASE_E_ARCHITECTURE_REPORT.md with:
      - Per-agent migration table (who migrates first, who depends on what)
      - Session fork inheritance map (which orchestrator context each sub-agent gets)
      - Per-RPC method signature for Codex app-server (verified)
      - Wedge recovery flow (interrupt → corrective turn → continue or escalate)
      - Orphan tool detection schema (Claude path mirrors Codex item/started schema)

Wave 2a (parallel, solo agents):
  
  new10-step1-impl: Session 16.5 scope
    Files: audit_agent.py (migrate :81 and :294)
    MCPs: context7 (for SDK patterns), sequential-thinking
    Dependencies: none
    LOW RISK (isolated file, same semantics)
  
  bug20-impl: Codex app-server migration
    Files: codex_transport.py (replace), new codex_appserver.py module
    MCPs: context7 (for Codex RPC spec verification), sequential-thinking
    Dependencies: none (parallel track)
    HIGH RISK (new transport layer)
    Preserve old transport behind feature flag for rollback

Wave 2b (sequential, after 2a):
  
  new10-step2-impl: Session 17 scope  
    Files: agents.py:1818-1895 (enterprise-mode orchestration rewrite)
    MCPs: context7, sequential-thinking
    Dependencies: NEW-10 Step 1 complete (pattern validated)
    MEDIUM RISK (architectural)
    
    Per-agent migration (all MUST get MCP access via fork_session):
    - architecture-lead
    - coding-lead
    - coding-dept-head
    - review-lead
    - review-dept-head

Wave 2c (sequential, after 2b):
  
  new10-step34-impl: Session 18 scope
    Files: wave_executor.py _WaveWatchdogState (add interrupt hook),
           wave_executor.py (subscribe to streaming events),
           new orphan_detector.py module (Claude path)
    MCPs: context7, sequential-thinking
    Dependencies: NEW-10 Step 2 complete (all agents use ClaudeSDKClient)
    MEDIUM RISK (hot-path change; mirrors Bug #12 lessons)

Wave 3 (parallel):
  test-engineer: writes ALL tests including stall injection for Step 3+4
    MCPs: sequential-thinking
  wiring-verifier: per-agent allowed_tools check (confirms mcp__* present for every sub-agent session)
    MCPs: sequential-thinking

Wave 4: test-engineer runs pytest + targeted integration tests
Wave 5: team lead writes PHASE_E_REPORT.md
```

### Implementation Details

**Session 16.5 — NEW-10 Step 1: audit_agent.py query() → ClaudeSDKClient**

File: `src/agent_team_v15/audit_agent.py:81, 294`

Before:
```python
async for msg in query(prompt=prompt, options=options):
    # process
```

After (per Appendix D §D.1):
```python
async with ClaudeSDKClient(options=options) as client:
    await client.query(prompt)
    async for msg in client.receive_response():
        # process
    # watchdog can call client.interrupt() if stall detected
```

Tests:
- test_audit_agent_uses_claude_sdk_client
- test_audit_agent_interrupt_capability_available
- test_audit_report_json_unchanged (roundtrip)

**Session 17 — NEW-10 Step 2: Eliminate Task("sub-agent") in enterprise mode**

File: `src/agent_team_v15/agents.py:1818-1895`

Current: enterprise-mode prompt instructs `Task("architecture-lead"/"coding-lead"/"coding-dept-head"/"review-lead"/"review-dept-head", ...)`. Sub-agents have NO MCP access.

New: Python orchestrator opens separate `ClaudeSDKClient` sessions per sub-agent role. Each:
- Has full MCP access via `ClaudeAgentOptions.mcp_servers=...`
- Inherits conversation history via `fork_session=True`
- Uses its own allowed_tools list

Per Appendix D §D.2 verified pattern:
```python
async for message in query(
    prompt="...",
    options=ClaudeAgentOptions(
        resume=session_id,
        fork_session=True,  # NEW session; parent history inherited
        mcp_servers={"context7": ..., "sequential-thinking": ..., ...},
        allowed_tools=["mcp__context7__*", "mcp__sequential-thinking__*", "Read", "Write", "Edit", ...],
    )
):
    ...
```

Tests:
- test_enterprise_mode_no_task_dispatch
- test_each_sub_agent_has_mcp_access (verify `mcp__context7__*` in allowed_tools per session)
- test_forked_session_inherits_history
- test_sub_agent_sessions_isolated
- Integration test per sub-agent flow

**Session 18 — NEW-10 Step 3+4: client.interrupt() + streaming orphan detection**

Step 3: Wire `client.interrupt()` into `wave_executor._WaveWatchdogState`. On wedge detection: `await client.interrupt()` then send corrective prompt (preserves session). Mirrors Codex `turn/interrupt`.

Step 4: Subscribe to per-message events from `client.receive_response()`. Detect orphan tool starts (`AssistantMessage` with `ToolUseBlock` but no matching `ToolResultBlock` within timeout).

Tests:
- test_wave_watchdog_interrupts_on_stall
- test_orphan_tool_detection_fires
- test_corrective_turn_preserves_session
- test_orphan_detection_claude_path_symmetric_with_codex
- Stall injection integration tests

**Bug #20 — Codex app-server migration**

Per `docs/plans/2026-04-15-bug-20-codex-appserver-migration.md` + Appendix D §D.3.

Replace `codex exec` subprocess with JSON-RPC over stdio. Initialize sequence:
```json
{
  "method": "initialize",
  "id": 0,
  "params": {
    "clientInfo": {"name": "v18_builder", "title": "V18 Builder", "version": "1.0.0"},
    "capabilities": {
      "experimentalApi": true,
      "optOutNotificationMethods": ["item/agentMessage/delta"]
    }
  }
}
```

RPCs used:
- `session/new`
- `turn/submit`
- `turn/interrupt`
- Notifications: `item/started`, `item/completed`, `tokenUsage/updated`, `turn/diff/updated`

Preserve old transport behind feature flag `v18.codex_transport_mode: str = "appserver"` (can fall back to `"subprocess"` for rollback).

### Phase E Exit Criteria

- [ ] audit_agent.py migrated to ClaudeSDKClient (Step 1)
- [ ] Task() dispatch eliminated from enterprise-mode prompts (Step 2)
- [ ] Every sub-agent session has `mcp__context7__*` in allowed_tools (verified by integration test)
- [ ] client.interrupt() wired into wave watchdog (Step 3)
- [ ] Orphan tool detection on Claude path (Step 4)
- [ ] Codex app-server transport working (Bug #20)
- [ ] Old Codex transport preserved under feature flag
- [ ] 40+ new tests covering migration + transport semantics
- [ ] Full test suite passes (~10,170 → ~10,210+)
- [ ] PHASE_E_ARCHITECTURE_REPORT.md captured
- [ ] Production-caller-proof at `session-E-validation/` (stall injection test + per-agent MCP verification + Codex app-server RPC round-trip)
- [ ] PHASE_E_REPORT.md written

---

## PHASE FINAL — SINGLE COMPREHENSIVE SMOKE (GATE D)

**Goal:** Validate the entire hardened pipeline end-to-end with one comprehensive paid smoke across M1-M6.

**Budget:** $35-50 max

**Config:** ALL feature flags ON at production defaults:
- `v18.ownership_contract_enabled: True`
- `v18.audit_fix_iteration_enabled: True`
- `v18.mcp_informed_dispatches_enabled: True` (default)
- `v18.codex_transport_mode: "appserver"` (Bug #20)
- All existing flags at their post-closeout defaults

### Pre-flight Checklist (MANDATORY — 4 items)

1. `pip show agent-team-v15` → editable path is current worktree
2. `docker ps` → ports 5432/5433/3080 free
3. `which agent-team-v15` → entrypoint resolves to current worktree
4. `docker ps -a` → no stale containers

### Recent Test Validation

5. `pytest tests/ -v --tb=short` → all pass (expected ~10,210+)

### Smoke Run

- **PRD:** stock `v18 test runs/TASKFLOW_MINI_PRD.md` (or chosen enterprise PRD)
- **Config:** production-default config.yaml with all v18 flags ON
- **Output dir:** `v18 test runs/build-m-phase-final-smoke-<TIMESTAMP>/`
- **Preservation:** entire `.agent-team/` directory, source trees, BUILD_LOG.txt, all logs, AUDIT_REPORT.json, STATE.json

### Exit Criteria

- [ ] All milestones M1-M6 PASS
- [ ] ≤5 findings total across all milestones
- [ ] audit_health=passed for each milestone
- [ ] AUDIT_REPORT.json contains `scope` field (N-15)
- [ ] FIX_CYCLE_LOG.md populated (N-08 observability)
- [ ] Cascade findings consolidated (N-11)
- [ ] Framework idioms cache populated at `.agent-team/framework_idioms_cache.json` (N-17)
- [ ] STATE.json invariants consistent (NEW-7) — `summary.success` matches `failed_milestones`
- [ ] No duplicate Prisma modules (NEW-1) — only src/database/ populated
- [ ] Scaffold self-verification passed (N-13) — port consistency check green
- [ ] SPEC.md reconciliation ran cleanly (N-12) — no RECONCILIATION_CONFLICTS.md emitted
- [ ] **Wave T ran at least once on at least one milestone with non-empty test output (NEW-3)**
- [ ] **Codex app-server transport handled at least one Wave B dispatch successfully (NEW-4 + Bug #20)**
- [ ] **All 6 post-Wave-E scanners ran on at least one milestone; results in audit report (NEW-5)**
- [ ] **UI_DESIGN_TOKENS.json loaded and consumed by Wave D.5 on at least one milestone (NEW-6)**
- [ ] Every Claude agent session shows `mcp__*` tools in allowed_tools (NEW-9 + NEW-10)
- [ ] At least one wedge recovery via `client.interrupt()` observed OR orphan detection fired (NEW-10)
- [ ] Budget stayed under $50 cap
- [ ] No regressions from baseline
- [ ] PHASE_FINAL_SMOKE_REPORT.md captures full coverage matrix mapping every N-item + NEW-item + latent wiring to its validation evidence

**If smoke fails:** halt. Do not fix in-flight. Branch + commit + PR + review. If the failure is a new defect class: update the plan; run Phase FINAL again. If it's a known class already covered: root-cause why the fix didn't hold.

---

## PHASE POST-FINAL — MASTER MERGE

**Scope:** No code. Merge `integration-2026-04-15-closeout` → `master`.

**Prerequisite:** Phase FINAL smoke passed.

**Closes PRs:** #3-#12 + #25 as appropriate.

**Cost:** $0.

---

## COVERAGE MAP FOR ITEMS WITH INDIRECT RESOLUTION

Several items in the investigation report are closed INDIRECTLY rather than by a dedicated code change. This section documents exactly how each is resolved so nothing appears missed:

### N-16 — Stock PRD Alignment (LOW, doc-only)

**Resolution:** subsumed by N-04 + N-12.

Per investigation report Part 4 N-16: "Recommendation: (b) — don't proliferate PRDs; fix the drift." The drift is fixed by:
- N-04 (Prisma location reconciliation to src/database/) — Phase B
- N-12 (unified milestone SPEC.md reconciliation) — Phase B

No separate action needed. Phase FINAL smoke validates the stock PRD works correctly once N-04 + N-12 land.

### NEW-3 — Wave T never successfully run in production (HIGH latent)

**Resolution:** closed by Phase FINAL smoke.

Per investigation Part 7 NEW-3: "Fix: runs as N-14 corollary + requires a successful Wave B + C + D build first."

N-14 (production-caller proof process template) lands in Phase C. The first successful Wave B → C → D → T build happens in Phase FINAL smoke. Wave T's production wiring (rollback snapshot at `wave_executor.py:1781`, fix iteration at `:1847-1920`) gets exercised for the first time.

**Phase FINAL smoke exit criterion added:** Wave T ran at least once on at least one milestone with non-empty test output.

### NEW-4 — Codex transport untested in production (HIGH latent)

**Resolution:** closed by Phase E Bug #20 migration + Phase FINAL smoke.

Per investigation Part 7 NEW-4: "Fix: out of scope for post-Gate-A; handled by Session 11."

Session 11 in original numbering = Phase E in this plan (Bug #20 Codex app-server migration). Phase FINAL smoke runs with `v18.codex_transport_mode: "appserver"` which exercises the new transport on real wave calls.

**Phase FINAL smoke exit criterion added:** Codex app-server transport handled at least one Wave B dispatch successfully.

### NEW-5 — Post-Wave-E scanners untested (MEDIUM latent)

**Resolution:** closed by Phase FINAL smoke.

Per investigation Part 7 NEW-5: "Fix: covered by N-14 (production-caller proof) + requires a successful all-wave run."

N-14 template doc lands in Phase C. Phase FINAL smoke is the first successful all-wave run. The 6 post-Wave-E scanners (WIRING-CLIENT-001, I18N-HARDCODED-001, DTO-PROP-001, DTO-CASE-001, CONTRACT-FIELD-001/002 at `wave_executor.py:2957-2960`) fire for the first time in production.

**Phase FINAL smoke exit criterion added:** all 6 post-Wave-E scanners ran on at least one milestone; results appear in the milestone's final audit report.

### NEW-6 — Wave D.5 design-tokens consumption untested (MEDIUM latent)

**Resolution:** closed by Phase FINAL smoke.

Per investigation Part 7 NEW-6: "Fix: as above — requires successful Wave B to reach."

`agents.py:8581-8591` loads UI_DESIGN_TOKENS.json for Wave D/D.5. Phase FINAL smoke runs the full pipeline where this actually executes.

**Phase FINAL smoke exit criterion added:** UI_DESIGN_TOKENS.json loaded and consumed by Wave D.5 on at least one milestone.

### NEW-9 — Wave sub-agents have no direct MCP access (structural)

**Resolution:** closed structurally by N-17 + NEW-10.

Per investigation Part 7 NEW-9: "Fix: structurally address via N-17 (orchestrator pre-fetch injection). Long-term: investigate ClaudeSDKClient session-forking (Fix B in N-17; NEW-10) for MCP inheritance."

Short-term fix (N-17 orchestrator pre-fetch) lands in Phase C.
Long-term fix (NEW-10 session forking with fresh mcp_servers) lands in Phase E Sessions 17 + 18.

After Phase E completes, NEW-9 is STRUCTURALLY resolved — every sub-agent session has its own MCP access via `ClaudeAgentOptions.mcp_servers`.

**Phase FINAL smoke exit criterion added:** every Claude agent session trace shows `mcp__context7__*` in `allowed_tools` (already listed in Phase FINAL criteria).

---

| Metric | Total |
|--------|-------|
| Phases | 5 implementation + 1 smoke + merge = 6 total |
| Implementation LOC | ~4,440 |
| Implementation phases cost | $0 |
| Paid smoke cost | $35-50 (one comprehensive Gate D) |
| Test growth | 9900 → ~10,210+ (~310 new tests) |

**Cost savings vs v1 plan:** $125-130 (5 interim smokes) → $35-50 (1 final smoke). **~70% reduction in paid validation cost.**

**Time savings:** 15 sessions → 5 implementation phases + 1 smoke. Each phase is a single atomic agent-team sprint (not 3 separate sessions for NEW-10, etc.).

---

## EXECUTION DISCIPLINE

**At the start of every phase:**
1. Read the phase spec from this document
2. Read the relevant sections of the deep investigation report
3. Verify prerequisites (previous phase complete, flags correct, tests green)
4. Initialize agent team with context7 + sequential-thinking MCPs mandatory
5. Follow the EXHAUSTIVE pattern: discovery → parallel/sequential implementation → test engineering + wiring verification → final report

**During every phase:**
- Every architect/discovery agent uses sequential-thinking for systematic code walks
- Every agent uses context7 to verify framework behavior before writing/reviewing code — NO assumptions from training data
- Every implementation agent has a production-caller-proof requirement
- Cross-agent coordination through shared architecture report, never through guessing

**At the end of every phase:**
1. All tests passing (no regressions from baseline)
2. Production-caller-proof artifact written at `session-<phase>-validation/`
3. PHASE_<letter>_REPORT.md captures work done + verification evidence
4. Memory rules honored (grep for "validated" claims without end-to-end proof)
5. Offline replay against build-l's preserved state where applicable (audit loop, scope persistence, state invariants, cascade suppression, duplicate cleanup)

**Cross-phase invariants:**
- No phase merges to `integration-2026-04-15-closeout` without reviewer gate
- No master merge until Phase FINAL passes
- Every feature flag's default in code matches documented default in this spec
- Every LOC estimate has room for ±20% variance; overruns trigger scope review

---

## THE EXIT CRITERION

When all 5 implementation phases complete and Phase FINAL smoke has passed:

- [ ] Every N-item (N-01 through N-17) closed with file:line evidence
- [ ] Every NEW-item (NEW-1 through NEW-10) closed
- [ ] All 4 latent wirings cleared (D-02 consumer halt, D-09 MCP pre-flight, D-14 fidelity labels, C-01 scope persistence)
- [ ] PR #25 merged
- [ ] Original tracker Sessions 7-9 deferred items closed (A-10/D-15/D-16/D-12/D-14/D-17/D-01/D-10)
- [ ] Bug #20 codex app-server migrated
- [ ] Phase FINAL smoke passed (≤5 findings across M1-M6)
- [ ] Master merge landed
- [ ] Every phase has a production-caller-proof validation artifact
- [ ] Every phase used context7 + sequential-thinking MCPs for verification
- [ ] Memory rules demonstrably honored across every phase
- [ ] Test baseline: 9900 → ~10,210+ (no regressions)

**Report followed EXACTLY. Nothing broken. Nothing missed.**

---

## WHAT TO DO FIRST

**Phase A starts NOW.** Launch the EXHAUSTIVE agent team:

```
Wave 1 (solo): architecture-discoverer with context7 + sequential-thinking

Wave 2 (parallel, 3 agents, NO FILE OVERLAP):
  - n01-n15-implementer: endpoint_prober.py + audit_models.py:to_json
  - state-invariants-implementer: state.py + cli.py:13491 warning
  - coercion-logging-implementer: audit_models.py:352-356 (from_json extras filter)

Wave 3 (parallel): test-engineer + wiring-verifier

Wave 4: pytest full suite

Wave 5: PHASE_A_REPORT.md + production-caller-proof at session-A-validation/
```

In parallel with Phase A: prepare PR #25 diff summary for reviewer approval.

**Exit Phase A → Phase B. One phase at a time. No skipping, no combining within a phase, no shortcuts.** 

**No smoke runs until Phase FINAL.**
