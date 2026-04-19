# Session 5 Execute — Runtime + toolchain hardening (D-02 + D-03 + D-09)

**Tracker session:** Session 5 in `docs/plans/2026-04-15-builder-reliability-tracker.md` §9.
**Cluster:** Cluster 5 (runtime + toolchain hardening).
**Why this session:** Build-j showed the builder silently degrading three different runtime/toolchain paths — compose-less runtime verification skipped, OpenAPI launcher failed on Windows with `WinError 2`, Contract Engine MCP tool missing so endpoint validation used static-only. None of these are fatal alone; together they produce a pipeline that "passes" while actually running in degraded mode on every axis. Session 5 closes all three so Session 6's Gate A smoke produces reliable verification signals — no "health=skipped" when we wanted runtime verification, no OpenAPI regex fallback surprises, no silent missing-MCP swap to static analysis.

**This is the last code-change session before Gate A smoke (Session 6).** After Session 5 merges, we run the first paid smoke of the closeout.

**Items & sizing:**
- **D-02** — Runtime verification graceful-block when compose missing (S, ~40 LOC). LOW–MEDIUM risk.
- **D-03** — OpenAPI launcher Windows executable resolution (S, ~30 LOC). LOW risk.
- **D-09** — Contract Engine MCP tool pre-flight + structured fallback labeling (S, ~30 LOC). LOW risk.

---

## 0. Mandatory reading (in order)

1. `docs/plans/2026-04-15-builder-reliability-tracker.md` §5 (D-02, D-03, D-09) and §9 (Session 5).
2. **No per-item plans exist** — all three are S-sized, tracker entry is the full spec.
3. Evidence:
   - `v18 test runs/build-j-closeout-sonnet-20260415/.agent-team/RUNTIME_VERIFICATION.md` — the "No docker-compose file found — runtime verification skipped." evidence.
   - `v18 test runs/build-j-closeout-sonnet-20260415/BUILD_LOG.txt` — grep for `WinError 2` (D-03) and `validate_endpoint Contract Engine MCP tool is not present` (D-09). Each line is the production failure.
   - `v18 test runs/build-j-closeout-sonnet-20260415/FINAL_VALIDATION_REPORT.md` §4.1 + §4.4 — context on why each matters.
4. Source files:
   - `src/agent_team_v15/runtime_verification.py` — D-02 touch point. Read the whole file; it's the one that currently produces `health=skipped`.
   - `src/agent_team_v15/openapi_generator.py` — D-03 touch point. Find the subprocess invocation that hit WinError 2.
   - `src/agent_team_v15/mcp_servers.py` — D-09 touch point. Register the Contract Engine MCP (or document its absence and ensure the fallback is labeled).
5. Memory: `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/feedback_structural_vs_containment.md` + `feedback_verification_before_completion.md`.

---

## 1. Goal

Three PRs against `integration-2026-04-15-closeout` (current HEAD `11f7cda`). All three are independent — no stacking needed. Open against integration directly.

- **PR A — D-02**: runtime_verification graceful-block. When `config.v18.live_endpoint_check=True` but compose is missing AND no live app, return `health=blocked` (not `skipped`) with a structured error. Forces the downstream gate to halt rather than silently degrade.
- **PR B — D-03**: OpenAPI launcher uses `shutil.which` + platform-aware extension resolution. No more `WinError 2` on Windows; falls through to regex extraction only after a legible error logs the exact executable path tried.
- **PR C — D-09**: Contract Engine MCP pre-flight. Add to `mcp_servers.py` registration if the engine is available; if not, log a structured "MCP tool missing — using static analysis" marker and stamp it on every CONTRACT_E2E_RESULTS.md the builder writes.

Targeted pytest only. No paid smokes. No real subprocess, SDK, or Docker calls. Platform-aware mocking for D-03.

---

## 2. Branch + worktree

```
git fetch origin
git worktree add ../agent-team-v18-session-05 integration-2026-04-15-closeout
cd ../agent-team-v18-session-05
git checkout -b session-05a-runtime-verification
```

Three independent branches (NOT stacked — each item touches a different file):
- `session-05a-runtime-verification` — PR A (D-02)
- `session-05b-openapi-launcher` (branched from integration, not from PR A) — PR B (D-03)
- `session-05c-mcp-preflight` (branched from integration) — PR C (D-09)

Three PRs against `integration-2026-04-15-closeout`. Each independent, no stacking required.

---

## 3. Execution order — TDD

### PR A — D-02: runtime_verification graceful-block

**Scope:** `src/agent_team_v15/runtime_verification.py` only. Tests in `tests/test_runtime_verification.py` (new or extended).

**Fix:**
1. Current behaviour: when no compose file + no live app + `live_endpoint_check=True`, returns `health="skipped"` silently.
2. New behaviour: return `health="blocked"` with a structured error payload:
   ```python
   {
       "tested_endpoints": 0,
       "passed_endpoints": 0,
       "failed_endpoints": 0,
       "health": "blocked",
       "block_reason": "compose_file_missing",  # or "live_app_unreachable"
       "details": {
           "compose_path_checked": "<path>",
           "live_app_url_checked": "<url>",
           "live_endpoint_check": True,
       }
   }
   ```
3. `health="skipped"` STILL applies when `live_endpoint_check=False` (user opted out). `health="blocked"` applies only when the user opted in AND infrastructure is missing.
4. Downstream gate behaviour: find the consumer of `endpoint_test_report.health` and ensure `"blocked"` halts the pipeline (or at least fails the gate loudly) instead of proceeding as if "skipped" was acceptable. This likely lives in `cli.py` — grep for `endpoint_test_report` or `health == "skipped"` to find the consumer. **If no consumer exists to change, document that in a code comment and in the PR body** — `blocked` becomes informational-only until a consumer is added (out of scope this session).

**Tests:**
1. **Compose missing + live_endpoint_check=True → health=blocked.** Mock filesystem (no compose file) + `requests.get` raising ConnectionError; assert `health=="blocked"`, `block_reason=="compose_file_missing"`.
2. **Compose missing + live_endpoint_check=False → health=skipped.** Same filesystem mock, flag off; assert `health=="skipped"` (legacy path preserved).
3. **Compose present + boot succeeds → normal flow.** Mock compose file exists + `requests.get` returning 200; assert `health != "blocked"`, runs the real endpoint checks.
4. **Compose missing + live app reachable → use live app.** Mock compose missing + `requests.get` returning 200 at the configured live-app URL; assert `health != "blocked"` (uses live app fallback — existing behaviour preserved).
5. **Structured details present.** Assert `details` dict has `compose_path_checked` and `live_app_url_checked` populated.

Target: 5 new/extended tests.

**No feature flag.** Structural fix. Pre-existing behaviour was wrong (silent skip violates M1 AC).

**Commit subject:** `fix(runtime-verification): block instead of skip when compose + live app both missing (D-02)`.

### PR B — D-03: OpenAPI launcher Windows resolution

**Scope:** `src/agent_team_v15/openapi_generator.py` only. Tests in `tests/test_openapi_generator.py` (new or extended).

**Fix:**
1. Find the subprocess invocation(s) that hit `WinError 2`. Likely something like `subprocess.run(["npx", "openapi-generator-cli", ...])` where `npx` isn't found on PATH when called without shell=True on Windows.
2. Before invoking, resolve the executable with `shutil.which(cmd)`:
   ```python
   import shutil
   resolved = shutil.which(cmd)
   if resolved is None:
       # Try Windows-specific extensions explicitly
       for ext in (".cmd", ".exe", ".bat"):
           resolved = shutil.which(cmd + ext)
           if resolved:
               break
   if resolved is None:
       logger.error("OpenAPI launcher: %r not found on PATH (checked .cmd/.exe/.bat)", cmd)
       raise OpenAPILauncherNotFound(cmd)
   ```
3. Invoke with the resolved absolute path: `subprocess.run([resolved, ...])`.
4. Catch `OpenAPILauncherNotFound` in the caller and log "OpenAPI launcher unavailable; falling back to regex extraction — {cmd} missing" (legible, not the cryptic `WinError 2`).
5. The regex fallback path stays unchanged — we're just making the degradation legible.

**Tests:**
1. **`shutil.which` resolves the command → subprocess called with resolved path.** Mock `shutil.which` returning `C:\npm\npx.cmd`; assert `subprocess.run` called with that exact path as argv[0].
2. **`shutil.which` returns None for base name, then resolves with `.cmd`.** Mock `shutil.which("npx")` returning None, `shutil.which("npx.cmd")` returning the path; assert the `.cmd` variant is used.
3. **All extensions miss → `OpenAPILauncherNotFound` raised.** Mock `shutil.which` returning None for all; assert exception with the command name in the message.
4. **Caller catches the exception and logs fallback.** Integration test: mock launcher missing; call the higher-level generation function; assert fallback path ran AND the log message is the legible form (not `WinError 2`).

Target: 4 new/extended tests.

**No feature flag.** Pure toolchain robustness.

**Commit subject:** `fix(openapi-generator): resolve launcher via shutil.which with Windows extension fallback (D-03)`.

### PR C — D-09: Contract Engine MCP pre-flight

**Scope:** `src/agent_team_v15/mcp_servers.py` + wherever CONTRACT_E2E_RESULTS.md is written (likely `contract_verifier.py` or `contract_client.py` — grep to find). Tests in `tests/test_mcp_servers.py` (new or extended).

**Investigation first (15 min):**
- Does the Contract Engine MCP tool exist as deployable code in this repo? Grep for `validate_endpoint`, `ContractEngine`, or similar. If yes: it's a registration gap. If no: the fix is documenting the gap + labeling the fallback loudly.
- Save 100-word note to `v18 test runs/session-05-validation/d09-investigation.md` with the finding.

**Fix (branch based on investigation):**

**Branch A — MCP tool exists but unregistered:**
1. Add its registration to `mcp_servers.py` so it's available when the pipeline starts.
2. Add a pre-flight check at pipeline startup: enumerate registered MCP tools; log a structured line like `MCP pre-flight: validate_endpoint {available|missing}`. Persist to a new `.agent-team/MCP_PREFLIGHT.json` for audit trail.

**Branch B — MCP tool does not exist as deployable:**
1. Do NOT add it to `mcp_servers.py`.
2. Still add the pre-flight check (§B.1 above) so operators can see the `missing` status explicitly in logs + `MCP_PREFLIGHT.json`.
3. In the contract-verification code path (wherever CONTRACT_E2E_RESULTS.md is written), when `validate_endpoint` is unavailable, prepend the output file with a **clearly labeled** header:
   ```markdown
   > **Verification fidelity:** STATIC ANALYSIS (not runtime). The
   > `validate_endpoint` Contract Engine MCP tool is not deployed in this
   > environment. Results below are derived from source-code diff against
   > `ENDPOINT_CONTRACTS.md`, not from live endpoint probing. Confidence
   > is lower than a real runtime validation would provide.
   ```
   This replaces the current implicit fallback with explicit labeling.

**Most likely branch:** B (build-j's log says "not present in the deployed toolset" which implies it simply doesn't exist as deployable code).

**Tests:**
1. **Pre-flight check enumerates tools.** Mock a set of registered MCP tools; call the pre-flight function; assert `MCP_PREFLIGHT.json` written with structured status.
2. **`validate_endpoint` missing → pre-flight logs structured line.** Assert the log message contains `"validate_endpoint"` and `"missing"` as distinct tokens.
3. **Fallback labeling appears in CONTRACT_E2E_RESULTS.md.** When `validate_endpoint` is missing, the output file starts with the fidelity header block; when available, it does not.
4. **Branch A (if applicable): registered tool shows up in pre-flight.** Only if investigation chose Branch A.

Target: 3–4 new tests depending on branch.

**No feature flag.** Structural logging + labeling; no behaviour toggle.

**Commit subject:** `feat(mcp): pre-flight check + labeled static-analysis fallback for validate_endpoint (D-09)`.

---

## 4. Hard constraints

- **No paid smokes.** Gate A smoke is Session 6, after this lands.
- **No real subprocess, Docker, or MCP network calls in tests.** Mock `subprocess.run`, `shutil.which`, filesystem reads, MCP registry reads.
- **No merges.** Three independent PRs against `integration-2026-04-15-closeout`. Reviewer merges.
- **Do NOT touch:**
  - `src/agent_team_v15/wave_executor.py`
  - `src/agent_team_v15/codex_transport.py`
  - `src/agent_team_v15/provider_router.py`
  - `src/agent_team_v15/cli.py` (Session 4 finalized orchestration/recovery)
  - `src/agent_team_v15/scaffold_runner.py` (Session 2)
  - `src/agent_team_v15/audit_models.py`, `state.py`, `m1_startup_probe.py` (Session 3)
  - `src/agent_team_v15/milestone_scope.py`, `scope_filter.py`, `audit_scope.py` (Session 1)
  - Compile-fix / fallback paths.
- **Authorized surface per PR:**
  - PR A (D-02): `runtime_verification.py` + test file. Consumer-side downstream change in `cli.py` is authorized IF investigation shows a consumer needs updating to honor `health=blocked` — but **only the minimum one-line condition change**, not broader orchestration edits.
  - PR B (D-03): `openapi_generator.py` + test file.
  - PR C (D-09): `mcp_servers.py` + the contract-verification output file writer (grep to locate — likely `contract_verifier.py` / `contract_client.py`) + test files + investigation note.
- **Do NOT add new feature flags.** All three items are structural.
- **Do NOT run the full suite.** Targeted pytest per §5.

---

## 5. Guardrail checks before pushing each PR

**PR A (D-02):** diff shows changes only in `runtime_verification.py`, new/extended tests, possibly one-line change in `cli.py` IF a consumer needed updating. Net ≤ 150 LOC.

**PR B (D-03):** diff shows changes only in `openapi_generator.py` + new/extended tests. Net ≤ 100 LOC.

**PR C (D-09):** diff shows changes only in `mcp_servers.py` + contract-verification writer + new tests + investigation note. Net ≤ 150 LOC.

**Targeted pytest (not full suite):**

```
pytest tests/test_runtime_verification.py \
       tests/test_openapi_generator.py \
       tests/test_mcp_servers.py \
       tests/test_contract_generation_orchestration.py \
       tests/test_audit_models.py \
       tests/test_state_finalize.py \
       tests/test_m1_startup_probe.py \
       tests/test_scaffold_m1_correctness.py \
       tests/test_orchestration_review_fleet.py \
       tests/test_recovery_prompt_hygiene.py \
       tests/test_wave_t_findings.py \
       -v
```

Sessions 1–4 tests included as regression guards.

---

## 6. Reporting back

```
## Session 5 execution report

### PRs
- PR A (D-02 — runtime verification graceful-block): <url>
- PR B (D-03 — OpenAPI launcher Windows resolution): <url>
- PR C (D-09 — MCP pre-flight + labeled fallback): <url>

### Tests
- tests/test_runtime_verification.py (new/extended): <N>/<N> pass
- tests/test_openapi_generator.py (new/extended): <N>/<N> pass
- tests/test_mcp_servers.py (new/extended): <N>/<N> pass
- Targeted cluster (§5 command): <N> passed, 0 failed

### Static verification
- D-09 investigation: v18 test runs/session-05-validation/d09-investigation.md — Branch A (registration) or Branch B (labeling) chosen

### Deviations from plan
<one paragraph>

### Files changed
<git diff --stat output, grouped by PR>

### Blockers encountered
<either "none" or a structured list>
```

If D-09's investigation reveals the Contract Engine MCP needs a real implementation (not just registration or labeling), stop and report — that's a deeper piece of work than this session authorizes.

---

## 7. What "done" looks like

- Three independent PRs open against `integration-2026-04-15-closeout`.
- All targeted tests pass.
- D-09 investigation note committed.
- No feature flags added (all three are structural).
- No code outside authorized surface per PR.
- No real subprocess / Docker / MCP calls in test runs.
- Report posted matching §6 template.

The reviewer (next conversation turn) will diff the three PRs, verify investigation reasoning, and either merge or request changes. **After Session 5 merges, we run the Gate A smoke in Session 6.** Session 5 is the last code-change session before that checkpoint.
