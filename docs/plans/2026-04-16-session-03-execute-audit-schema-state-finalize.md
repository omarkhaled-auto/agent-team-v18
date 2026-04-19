# Session 3 Execute — Audit schema + state finalization + M1 startup-AC probe (D-07 + D-13 + D-20)

**Tracker session:** Session 3 in `docs/plans/2026-04-15-builder-reliability-tracker.md` §9.
**Cluster:** Cluster 3 (audit schema + state).
**Why this session:** Session 2 made the scaffold correct. Session 3 makes the pipeline TELL THE TRUTH about what it did — audit JSON parses cleanly, STATE.json's `summary.success`/`audit_health`/`current_wave` are consistent with their authoritative sources, and M1's startup ACs are actually *executed* at audit time instead of left UNKNOWN. These three items together close Tier-1 blockers T1-04, T1-06 (partial), and enable the Gate A smoke in Session 6 to be defensible.

**Items & sizing:**
- **D-07** — Audit producer/consumer schema mismatch (`audit_id` KeyError). S. LOW.
- **D-13** — `State.finalize()` consolidator. M. LOW.
- **D-20** — M1 startup-AC probe. M. MEDIUM (touches audit phase + uses real subprocess at runtime, mocked in tests).

---

## 0. Mandatory reading (in order)

1. `docs/plans/2026-04-15-builder-reliability-tracker.md` §5 (D-07, D-13, D-20) and §9 (Session 3).
2. Per-item plans:
   - `docs/plans/2026-04-15-d-13-state-finalize-consolidator.md` (full plan)
   - `docs/plans/2026-04-15-d-20-m1-startup-ac-probe.md` (full plan)
   - D-07 has no dedicated plan file — it's S-sized, tracker entry is the spec.
3. Evidence:
   - `v18 test runs/build-j-closeout-sonnet-20260415/.agent-team/AUDIT_REPORT.json` — the scorer-produced schema (no `audit_id`, `audit_cycle` not `cycle`, flat `score` not struct). Inspect first; this is what `from_json` must tolerate.
   - `v18 test runs/build-j-closeout-sonnet-20260415/.agent-team/STATE.json` — the inconsistency evidence. `summary.success: true` with `failed_milestones: ["milestone-1"]`. `audit_health: ""`. `wave_progress.milestone-1.current_wave: "D"` with `current_phase: "complete"`.
   - `v18 test runs/build-j-closeout-sonnet-20260415/.agent-team/milestones/milestone-1/REQUIREMENTS.md` "M1 Acceptance Criteria Results" table — shows `npm install` and `prisma migrate dev` marked UNKNOWN because they were never run in audit.
4. Source files:
   - `src/agent_team_v15/audit_models.py` — `AuditReport` dataclass @ ~line 207, `from_json` @ ~line 242, `to_json` @ ~line 221, `build_report` @ ~line 587. These are the D-07 touch points.
   - `src/agent_team_v15/state.py` — State dataclass, `audit_health` field @ line 60. Add `finalize()` here for D-13.
   - `src/agent_team_v15/cli.py` — audit dispatch around line 5253 (`_run_milestone_audit`); final STATE.json write near end of pipeline (search for `state.save()` or equivalent). Call `state.finalize()` before the final save.
5. Memory: `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/feedback_structural_vs_containment.md` + `feedback_verification_before_completion.md`.

---

## 1. Goal

Two PRs against `integration-2026-04-15-closeout` (current HEAD `12941c3`):

- **PR A — D-07 + D-13**: audit schema permissive `from_json` + `State.finalize()` consolidator. Bundled because D-13 depends on D-07 being able to parse the audit report (it reads `audit_health` from AUDIT_REPORT.json).
- **PR B — D-20**: M1 startup-AC probe in the audit phase. Standalone — adds a new module + integrates into `_run_milestone_audit`.

Targeted pytest only. No paid smokes. No real `npm install`, `docker compose up`, or `npx prisma` in tests — all subprocess calls mocked.

---

## 2. Branch + worktree

```
git fetch origin
git worktree add ../agent-team-v18-session-03 integration-2026-04-15-closeout
cd ../agent-team-v18-session-03
git checkout -b session-03-audit-schema-state-finalize
```

Two commits on one branch. Two stacked PRs against `integration-2026-04-15-closeout`, same pattern as Session 2.

---

## 3. Execution order — TDD

### Phase 1 — D-07: permissive audit schema (part of PR A)

**Scope:** `src/agent_team_v15/audit_models.py` only. Do NOT touch `audit_prompts.py` or the scorer-agent prompt — the fix is on the CONSUMER side (make `from_json` tolerate the producer's shape). Keep this tight — tracker size is S (~40 LOC).

**Investigation (20 min):**
1. Read build-j's `AUDIT_REPORT.json` end-to-end. Record every top-level field the scorer writes.
2. Compare to `AuditReport.to_json()` keys + `AuditReport.from_json()` required keys.
3. Identify every divergence. Expected findings: missing `audit_id`, `audit_cycle` vs `cycle`, flat `score` vs struct, missing `auditors_deployed`, extra `verdict`/`health`/`finding_counts`/`category_summary`/`notes`/`max_score`/`deductions_total`/`deductions_capped`.
4. Save a short note to `v18 test runs/session-03-validation/d07-schema-divergence.md` with the divergence list.

**Fix shape:** Extend `AuditReport.from_json` to be a superset parser — accept both the legacy `to_json` shape AND the scorer-produced shape:

- `audit_id`: optional. If missing, synthesize as `f"audit-{timestamp}-c{cycle}"` (stable for round-trip).
- `cycle`: accept either `cycle` or `audit_cycle` (aliased).
- `auditors_deployed`: default `[]` when missing.
- `score`: accept either an `AuditScore`-shaped dict OR a flat `{"score": N, "max_score": M}` pair at top level. When flat, build an `AuditScore` with the available fields + default thresholds.
- Preserve new fields as `extras: dict[str, Any]` on `AuditReport` — don't drop them; they're informational for downstream consumers (verdict/health/notes).

**Also:** `AuditReport.to_json()` stays canonical (produces the `to_json` shape). No changes to scorer prompt. The permissive reader is the single source of truth for parsing; the canonical writer stays uniform.

**Tests (in `tests/test_audit_models.py` — extend, don't replace):**
1. **Round-trip against build-j's actual AUDIT_REPORT.json.** Load the file verbatim; `AuditReport.from_json(text)` does not raise; result has populated `audit_id` (synthesized), `cycle` (from `audit_cycle`), `auditors_deployed` (default `[]`), `findings`, and `extras` carrying `verdict`/`health`/`notes`/`category_summary`.
2. **Legacy to_json→from_json round-trip still works.** Take an `AuditReport`, `to_json()` it, `from_json()` it back, compare. Byte-identity not required but field-equality on the populated fields IS.
3. **Synthesized audit_id is deterministic.** Same timestamp+cycle → same audit_id string.
4. **Flat score accepted.** Parse a JSON with `"score": 42, "max_score": 1000` at top level; assert `result.score.score == 42.0`, `result.score.max_score == 1000`.

Target: 4 new tests. Full test_audit_models.py still green.

### Phase 2 — D-13: State.finalize() consolidator (part of PR A)

**Scope:** `src/agent_team_v15/state.py` + `src/agent_team_v15/cli.py`.

Follow `docs/plans/2026-04-15-d-13-state-finalize-consolidator.md` §3 exactly. Implementation summary:

1. **Add `State.finalize(self) -> None`** per plan §3a. Reconciles:
   - `summary["success"] = len(self.failed_milestones) == 0`
   - `audit_health` — read from `AUDIT_REPORT.json` via `AuditReport.from_json` (which now parses it thanks to D-07); fall back to `""` if file missing/unparseable. Read the `extras.get("health", "")` field since `health` is one of the scorer-produced extras captured in D-07.
   - `current_wave` — clear from `wave_progress[*]` dict when `current_phase == "complete"`. Pop, don't set to None.
   - `stack_contract.confidence` — if no `backend_framework` AND no `frontend_framework`, set `confidence = "low"` (overriding whatever the caller stored).
   - `gate_results` — load from `GATE_FINDINGS.json` when present.
2. **Call `state.finalize()` once**, at end of pipeline before final STATE.json write. Find the call site — likely a `state.save()` or equivalent in `cli.py`. Add the finalize call immediately before.
3. **Idempotent:** calling `finalize()` twice produces identical output. Tests cover this.

**Tests (new file `tests/test_state_finalize.py`):** 7 tests per plan §4:
1. Failed milestone → `summary["success"] == False`.
2. Audit report present → `audit_health == "failed"` (from AUDIT_REPORT.json.extras.health).
3. `current_phase == "complete"` clears `current_wave` from every wave_progress entry.
4. Empty `stack_contract` → `confidence == "low"`.
5. Populated `stack_contract` → `confidence` unchanged (caller-specified value preserved).
6. GATE_FINDINGS.json present → `gate_results` matches file contents.
7. `finalize()` twice → second call has no effect (idempotent).

Use `tmp_path` fixture. Mock file-system reads with fixture JSON. Do NOT run the full pipeline.

### Phase 1+2 exit — before committing PR A

- `pytest tests/test_audit_models.py tests/test_state_finalize.py -v` — all pass.
- Static round-trip: write a one-off Python script under `v18 test runs/session-03-validation/roundtrip-buildj-audit.py` that loads `v18 test runs/build-j-closeout-sonnet-20260415/.agent-team/AUDIT_REPORT.json`, calls `AuditReport.from_json(text)`, prints populated fields. Save stdout to `v18 test runs/session-03-validation/d07-roundtrip-transcript.txt`. Confirm: no exception, audit_id present, cycle=1, findings=41, extras.health='failed'.
- **Commit subject:** `feat(audit,state): permissive from_json + State.finalize consolidator (D-07 + D-13)`.

### Phase 3 — D-20: M1 startup-AC probe (PR B)

**Scope:** new file `src/agent_team_v15/m1_startup_probe.py` + integration point in `src/agent_team_v15/cli.py` `_run_milestone_audit` + AuditReport field update in `audit_models.py`.

Follow `docs/plans/2026-04-15-d-20-m1-startup-ac-probe.md` §3 with these specifics:

**3a. New `m1_startup_probe.py`:**

```python
def run_m1_startup_probe(workspace: Path) -> dict[str, dict[str, Any]]:
    """Execute M1's 5 subprocess-level ACs in order; return structured results.

    Each entry: {status: "pass"|"fail"|"timeout", exit_code: int, stdout_tail: str, stderr_tail: str, duration_s: float}
    Teardown (`docker compose down`) always runs in a finally block, even if a probe fails mid-flight.

    This is only called for infrastructure milestones (complexity_estimate.entity_count == 0).
    """
```

Probes, in order:
1. `npm install` (timeout 300s, cwd=workspace).
2. `docker compose up -d postgres` (timeout 120s). Detect `docker compose` vs legacy `docker-compose` — try `docker compose version` first, fall back.
3. `npx prisma migrate dev --name init` (timeout 180s, cwd=workspace/apps/api). Requires DATABASE_URL env — set `postgresql://postgres:postgres@localhost:5432/app` as a fallback. Mark as `skipped_by_dep` if probe 2 failed.
4. `npm run test:api` (timeout 60s, cwd=workspace).
5. `npm run test:web` (timeout 60s, cwd=workspace).

Teardown: `docker compose down` (timeout 60s). Runs from a finally block regardless of probe success.

Each probe's stdout/stderr captured to last 1000 chars for telemetry. No full stdout stored (can be large for npm install).

**3b. Integration in `_run_milestone_audit` (or wherever audit finalizes `AUDIT_REPORT.json`):**

```python
# D-20: run M1 startup probe for infrastructure milestones only.
complexity = master_plan_milestone_entry.get("complexity_estimate", {})
is_infra_milestone = complexity.get("entity_count", 0) == 0 and milestone.template == "full_stack"
if is_infra_milestone and config.v18.m1_startup_probe:
    probe_results = run_m1_startup_probe(Path(workspace))
    # Attach to audit report
    report.acceptance_tests = {"m1_startup_probe": probe_results}
    # If any probe failed, set verdict to FAIL regardless of finding count
    if any(r["status"] in ("fail", "timeout") for r in probe_results.values()):
        report.extras["verdict"] = "FAIL"
```

**3c. New field on `AuditReport`:** `acceptance_tests: dict[str, Any] = field(default_factory=dict)`. Include in `to_json` + `from_json` (D-07's permissive reader picks it up as a known field now, not an extra).

**3d. Feature flag:** `config.v18.m1_startup_probe: bool = True`. Default ON; tests cover both.

**Tests (new file `tests/test_m1_startup_probe.py`):** per plan §4, 5 tests — all mock `subprocess.run`:

1. **Happy path:** all 5 probes return exit 0; assert `acceptance_tests.m1_startup_probe` has 5 entries all `status="pass"`.
2. **npm install fail:** mock exit 1; assert `AuditReport.extras["verdict"] == "FAIL"`.
3. **Non-infra milestone skipped:** mock an M3-like milestone (entity_count=1); assert probe never runs, `acceptance_tests` empty.
4. **Timeout handled:** mock subprocess raising `TimeoutExpired`; assert probe records `status="timeout"`, pipeline continues.
5. **Teardown always runs:** mock probe 2 (docker compose up) raising; assert `docker compose down` still called in finally.

**IMPORTANT: Use `unittest.mock.patch` on `subprocess.run` (or your own probe wrapper). NO real subprocess invocations in tests.** The probe function may have an internal `_run(cmd, timeout, cwd)` helper that tests mock — that's the cleanest seam.

### Phase 3 exit — before committing PR B

- `pytest tests/test_m1_startup_probe.py -v` — 5/5 pass.
- **Do NOT** run the probe end-to-end. That's a paid-smoke-adjacent activity and explicitly forbidden this session. Gate A smoke (Session 6) is where end-to-end proof happens.
- Save a short note to `v18 test runs/session-03-validation/d20-integration-summary.md` describing the probe's call-site integration in cli.py (1 paragraph + relevant line numbers).
- **Commit subject:** `feat(audit): M1 startup-AC probe with subprocess mocking (D-20)`.

---

## 4. Hard constraints

- **No paid smokes.**
- **No real `npm install`, `docker compose up`, `docker compose down`, `npx prisma`, `pnpm`, `yarn`, or `node` invocations in tests.** All subprocess calls mocked via `unittest.mock.patch`. The probe runner itself uses real subprocess at runtime — but tests NEVER exercise that real path.
- **No merges.** Push branch + open 2 PRs against `integration-2026-04-15-closeout`.
- **Do NOT touch:**
  - `src/agent_team_v15/wave_executor.py`
  - `src/agent_team_v15/codex_transport.py`
  - `src/agent_team_v15/provider_router.py`
  - `src/agent_team_v15/audit_prompts.py` (scorer prompt lives here — D-07 fix is consumer-side only)
  - `src/agent_team_v15/audit_team.py` (already wired in Session 1)
  - `src/agent_team_v15/scaffold_runner.py` (Session 2 territory)
  - `src/agent_team_v15/milestone_scope.py`, `scope_filter.py`, `audit_scope.py` (Session 1)
  - The compile-fix / fallback paths.
- **Do NOT add/change Wave D/B prompts, contract generation, or anything outside the D-07/D-13/D-20 surface.**
- **Do NOT bump `AuditReport` fields beyond what D-07 requires.** Adding `extras: dict[str, Any]` is sufficient for out-of-model scorer fields; do not promote them to first-class fields in this session. (That would be a separate schema-versioning PR.)
- **Do NOT change config.yaml defaults** unless a new v18 flag demands it. D-20 adds exactly one flag (`m1_startup_probe: bool = True`).
- **Do NOT run the full suite.** Targeted pytest per §5.

---

## 5. Guardrail checks before pushing each PR

**PR A (D-07 + D-13):**
- `git diff integration-2026-04-15-closeout...HEAD --stat` shows changes only in:
  - `src/agent_team_v15/audit_models.py` (modified)
  - `src/agent_team_v15/state.py` (modified)
  - `src/agent_team_v15/cli.py` (modified — single `state.finalize()` call site near final save)
  - `tests/test_audit_models.py` (modified — extend)
  - `tests/test_state_finalize.py` (new)
  - `v18 test runs/session-03-validation/d07-schema-divergence.md` (new)
  - `v18 test runs/session-03-validation/roundtrip-buildj-audit.py` (new)
  - `v18 test runs/session-03-validation/d07-roundtrip-transcript.txt` (new)

**PR B (D-20):**
- Diff shows changes only in:
  - `src/agent_team_v15/m1_startup_probe.py` (new)
  - `src/agent_team_v15/audit_models.py` (modified — add `acceptance_tests` field)
  - `src/agent_team_v15/cli.py` (modified — probe integration in `_run_milestone_audit`)
  - `src/agent_team_v15/config.py` (modified — add `m1_startup_probe: bool = True` to V18Config)
  - `tests/test_m1_startup_probe.py` (new)
  - `v18 test runs/session-03-validation/d20-integration-summary.md` (new)

**Targeted pytest (not full suite):**

```
pytest tests/test_audit_models.py \
       tests/test_state_finalize.py \
       tests/test_m1_startup_probe.py \
       tests/test_scaffold_runner.py \
       tests/test_scaffold_m1_correctness.py \
       tests/test_audit_scope.py \
       tests/test_audit_scope_wiring.py \
       tests/test_wave_scope_filter.py \
       -v
```

Scaffold + scope tests included as regression guard — shouldn't be affected, but quick sanity check catches surprises.

---

## 6. Reporting back

When both PRs are open, reply in the conversation with a single structured message:

```
## Session 3 execution report

### PRs
- PR A (D-07 + D-13 — audit schema + state finalize): <url>
- PR B (D-20 — M1 startup-AC probe): <url>

### Tests
- tests/test_audit_models.py: <N>/<N> pass (includes 4 new D-07 tests)
- tests/test_state_finalize.py (new): 7/7 pass
- tests/test_m1_startup_probe.py (new): 5/5 pass
- Targeted cluster (pytest command above): <N> passed, 0 failed

### Static verification
- D-07 schema-divergence note: v18 test runs/session-03-validation/d07-schema-divergence.md (N top-level fields the scorer writes vs AuditReport consumes)
- D-07 round-trip transcript: v18 test runs/session-03-validation/d07-roundtrip-transcript.txt (build-j AUDIT_REPORT.json parses cleanly, audit_id synthesized, extras.health=failed)
- D-20 integration summary: v18 test runs/session-03-validation/d20-integration-summary.md (call site + line numbers)

### Deviations from plan
<one paragraph: anything the D-07 investigation uncovered that changed scope, or any test-harness design decisions that the plan didn't anticipate>

### Files changed
<git diff --stat output, grouped by PR>

### Blockers encountered
<either "none" or a structured list>
```

If an investigation (D-07 divergence, or D-20's mocking harness) reveals the fix is larger than the plan authorized, **stop and report**. Do NOT ship partial work. Do NOT widen scope unilaterally.

---

## 7. What "done" looks like

- Two PRs open against `integration-2026-04-15-closeout`.
- All targeted tests pass (per §5).
- `AuditReport.from_json` parses build-j's actual AUDIT_REPORT.json without exception; `audit_id` synthesized; `extras` carries verdict/health/notes.
- `State.finalize()` exists, is called once in the pipeline, and is idempotent. 7 tests prove reconciliation rules.
- M1 startup-AC probe module exists, wired into audit phase for infrastructure milestones only, gated by `config.v18.m1_startup_probe`. 5 tests prove the probe's control flow via subprocess mocks.
- No real `npm` / `docker` / `npx` invocations in test runs.
- Validation artefacts under `v18 test runs/session-03-validation/`.
- No code outside D-07/D-13/D-20 surface.
- Report posted matching §6 template.

The reviewer (next conversation turn) will diff both PRs against the tracker + per-item plans, verify artefacts, and either merge or request changes.
