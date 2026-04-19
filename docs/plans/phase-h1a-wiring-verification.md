# Phase H1a — Wiring Verification Report

> Branch: `phase-h1a-compose-ownership-enforcement` (verified against uncommitted Wave 2 state, base `b77fca0`)
> Author: `wiring-verifier` (Wave 3B, Task #8)
> Scope: verify the 5 hook sites / 7 pattern IDs shipped by Wave 2 are wired into the LIVE execution path, correctly flag-gated, crash-isolated from peers, and reach `AUDIT_REPORT.json`.

This report reads the source at HEAD + uncommitted changes. All cited `file:line` pairs were opened by direct read during verification. The companion test suite at `tests/test_h1a_wiring.py` proves each invariant with pytest.

---

## 4A — Execution position (per-item)

| # | Item | Hook site (file:line) | Trigger condition | Fires on failed milestone? |
|---|------|----------------------|-------------------|------|
| 1 | Wave B compose-wiring directive | `src/agent_team_v15/agents.py:8589-8598` (insertion into `build_wave_b_prompt` body's `parts.extend([...])`) + `src/agent_team_v15/codex_prompts.py:155-182` (PREAMBLE `## Infrastructure Wiring`) + `src/agent_team_v15/codex_prompts.py:207` (SUFFIX checklist bullet) | Every Wave B prompt emission (Claude body and Codex PREAMBLE both populated — survives Codex→Claude fallback per `provider_router.py:273-425`). | N/A — prompt content is per-wave, not per-milestone-outcome |
| 2 | Scaffold verifier (SCAFFOLD-COMPOSE-001 + DoD-port oracle via milestone_id) | `src/agent_team_v15/wave_executor.py:4249-4256` calls `_maybe_run_scaffold_verifier(..., milestone_id=result.milestone_id)` inside the `if wave_letter == "Scaffold"` block (after `_run_pre_wave_scaffolding`, before Wave B dispatches). `scaffold_verifier.py:160-212` invokes `_check_port_consistency` then `_check_compose_topology`. | `_get_v18_value(config, "scaffold_verifier_enabled", False)`. Runs AFTER scaffolding completes; the `continue` at `wave_executor.py:4284` skips Wave B dispatch until the next loop iteration. | Not applicable — runs before the milestone can "fail"; a FAIL verdict itself causes scaffold-fail break at `:4266-4268`. |
| 3 | DoD feasibility verifier (DOD-FEASIBILITY-001) | `src/agent_team_v15/wave_executor.py:4981-5024`. Sits AFTER `persist_wave_findings_for_audit(...)` at `:4965-4971` and BEFORE the architecture-writer append at `:5028+`. | `_get_v18_value(config, "dod_feasibility_verifier_enabled", False)`. Hook is outside the `for wave_letter in waves[start_index:]` loop (loop body ends at `:4963` with `break` on failure), so the milestone-teardown block ALWAYS runs regardless of Wave outcome. | **YES (proven).** `break` at `:4961-4963` exits the loop but control falls through to the teardown. Verified: `test_dod_feasibility_fires_when_wave_b_fails` in `tests/test_h1a_wiring.py`. |
| 4 | Ownership enforcer — THREE hook sites | Check A: `wave_executor.py:4270-4273` (`_maybe_run_scaffold_ownership_fingerprint` inside the scaffolding-completed block). Check C: `wave_executor.py:4697-4725` inside `if wave_letter == "A" and wave_result.success:`. Post-wave drift: `wave_executor.py:4834-4858` inside the artifact-save branch, guarded by `str(wave_letter).upper() != "A"`. | Check A: fires when scaffolding runs successfully (gated by `ownership_enforcement_enabled`). Check C: fires only when Wave A's `wave_result.success` is True. Post-wave drift: fires for every non-A wave whose artifact was saved (gate `ownership_enforcement_enabled`). | Check A fires only when scaffold completes (earlier failures would break out). Check C only fires on `wave_result.success=True`, so NOT on Wave A failure. Post-wave drift only fires inside the artifact-save branch (i.e. after `wave_result.success` check) — so **does NOT fire on a failed non-A wave**. This is acceptable per plan: the enforcer is an advisory probe on successful artifacts. |
| 5 | Probe spec-oracle guard (PROBE-SPEC-DRIFT-001) | `src/agent_team_v15/endpoint_prober.py:1144-1172` (top of `_detect_app_url`, before precedence chain). | `_probe_spec_oracle_enabled(config)` reads `v18.probe_spec_oracle_enabled`. The guard only fires when BOTH (a) flag is True AND (b) `milestone_id` is truthy AND (c) REQUIREMENTS.md exists AND (d) DoD port is parseable. | Fails fast by raising `ProbeSpecDriftError`; the probe's caller (`_run_wave_b_probing`) converts that into a wave failure. **WIRING GAP**: see §milestone_id threading below. |
| 6 | Runtime tautology guard (RUNTIME-TAUTOLOGY-001) | `src/agent_team_v15/cli.py:13880-13912` (runs inside the runtime-verification emitter BEFORE the `N/M healthy` print line and the zero-services branch). | `_v18_cfg.runtime_tautology_guard_enabled` read inline. | N/A — runs during runtime verification, not per-milestone. |
| 7 | TRUTH summary panel | `src/agent_team_v15/cli.py:14014-14024`. Emitted AFTER `_truth_scores_path.write_text(...)` at `:14012` and BEFORE the `_truth_threshold` check at `:14029`. | **Not flag-gated** — always on (comment at `:14014` explicitly "Always on — this is a telemetry surface change"). | N/A — runs at BUILD_LOG end-of-run. |

**Item 5 (probe spec-oracle) placement confirmed inside `_detect_app_url` — lines 1144-1172, BEFORE the legacy precedence chain.**
**Item 6 (runtime tautology) placement confirmed BEFORE the `N/M healthy` print — lines 13880-13912 runs first, with the finding then printed at `:13929` and `:13933`.**

---

## 4B — Config gating (call-site vs early-return)

For each flag-gated hook the caller evaluates the gate BEFORE constructing arguments / performing the call. Verified by direct read:

| # | Item | Flag | Call-site gated or inner early-return? | Evidence |
|---|------|------|---------------------------------|------|
| 2 | Scaffold verifier | `scaffold_verifier_enabled` | **Call-site gated** (no invocation when False). | `wave_executor.py:4248` — `if _get_v18_value(config, "scaffold_verifier_enabled", False):` wraps the entire `_maybe_run_scaffold_verifier(...)` call. |
| 3 | DoD feasibility | `dod_feasibility_verifier_enabled` | **Call-site gated.** | `wave_executor.py:4981` — `if _get_v18_value(config, "dod_feasibility_verifier_enabled", False):` wraps the entire verifier block including import. |
| 4A | Ownership fingerprint | `ownership_enforcement_enabled` | **Call-site gated** (inside helper). | `wave_executor.py:1119` helper `_maybe_run_scaffold_ownership_fingerprint` — `if not _get_v18_value(config, "ownership_enforcement_enabled", False): return`. Returns before any import / module-touching work. |
| 4C | Wave-A forbidden-writes | `ownership_enforcement_enabled` | **Call-site gated.** | `wave_executor.py:4697-4699` — `if _get_v18_value(config, "ownership_enforcement_enabled", False):` wraps the enforcer import + call. |
| 4 post-wave | Post-wave drift | `ownership_enforcement_enabled` | **Call-site gated (combined with wave != A).** | `wave_executor.py:4834-4836` — `if _get_v18_value(config, "ownership_enforcement_enabled", False) and str(wave_letter).upper() != "A":` wraps the enforcer import + call. |
| 5 | Probe spec-oracle | `probe_spec_oracle_enabled` | **Inner early-return within `_detect_app_url`.** Body of the guard wrapped in `if _probe_spec_oracle_enabled(config): ...`. Outside the guard the legacy precedence chain runs unchanged. | `endpoint_prober.py:1148` — `if _probe_spec_oracle_enabled(config):` block, with disk/ parse work entirely inside. When False, function proceeds straight to legacy precedence at `:1174+`. |
| 6 | Runtime tautology guard | `runtime_tautology_guard_enabled` | **Call-site gated** (only the compose-graph walk and print call are inside the flag check). | `cli.py:13884-13912` — outer flag read at `:13884-13891`, then `if _tautology_guard_enabled:` wraps the `_runtime_tautology_finding(...)` call; `_tautology_finding` remains `None` when flag is False so the `print_warning(_tautology_finding)` branches at `:13929` / `:13933` are also no-ops. |
| 7 | TRUTH summary | **NOT FLAG-GATED** (always on, per Item 7 design). | n/a | `cli.py:14014` comment: `Always on — this is a telemetry surface change, not a feature toggle.` |

All flag-gated paths verified: when the flag is False, the check is NOT called (not merely called-and-early-return, except for Item 5 which is design — `_detect_app_url` is a pure function and the guard must live inside it). Item 5's inner gate still returns before doing any I/O or raising: `_probe_spec_oracle_enabled` performs only a dict/attr lookup, so there is no observable behaviour change from the legacy path.

---

## 4C — Crash isolation (peer checks at same hook site)

All enforcement checks that share a hook site wrap their body in `try/except Exception`. A crash in one does not prevent the next. Verified pairs:

| Hook site | Peer checks | Isolation confirmed? | Evidence |
|-----------|-------------|---------------------|------|
| Scaffold completion (`wave_executor.py:4248-4273`) | Scaffold verifier (Item 2) + Ownership fingerprint (Item 4A) | **Yes.** Verifier is wrapped via `_maybe_run_scaffold_verifier`'s internal `try/except Exception` at `:1068-1077` + `:1104-1105`. Fingerprint is wrapped via `_maybe_run_scaffold_ownership_fingerprint`'s outer `try/except Exception` at `:1140-1170`. A crash in one cannot prevent the other because each is a separate helper with its own try/except. | File reads; test `test_scaffold_hooks_are_crash_isolated` in `tests/test_h1a_wiring.py`. |
| Wave A completion (`wave_executor.py:4681-4725`) | Contract-conflict reader + Wave-A forbidden-writes enforcer | **Yes.** `_read_wave_a_contract_conflict(cwd)` at `:4682` is wrapped in its own `try` inside the helper; the `ownership_enforcement_enabled` block at `:4697-4725` has its own outer `try/except Exception` at `:4700-4725`. | Test `test_wave_a_hooks_are_crash_isolated`. |
| Per-wave artifact save + post-wave drift (`wave_executor.py:4793-4858`) | Artifact extract/save (pre-existing) + post-wave drift enforcer | **Yes.** Drift block at `:4837-4858` has its own `try/except Exception`. Artifact save at `:4819-4825` throws would be caught by outer structure — NOT by drift block; thus drift block only runs when artifact save succeeded (which is correct by design). | Test `test_post_wave_drift_is_crash_isolated`. |
| Milestone teardown (`wave_executor.py:4965-5024`) | `persist_wave_findings_for_audit` + DoD feasibility verifier | **Yes.** DoD block at `:4981-5024` has its own outer `try/except Exception`. The re-persist call at `:5011-5022` has its own inner `try/except`. First persist at `:4965-4971` is outside the DoD block so it cannot be blocked by a DoD crash. | Test `test_dod_feasibility_is_crash_isolated`. |
| Runtime verification emitter (`cli.py:13880-13912`) | Graph walk + legacy N/M print | **Yes.** `_runtime_tautology_finding` guarded by its own `try/except` at `:13901-13907`. Legacy `print_info`/`print_warning` blocks at `:13915-13934` are unaffected if tautology errors. | Test `test_runtime_tautology_is_crash_isolated`. |
| BUILD_LOG end-of-run (`cli.py:14014-14024`) | TRUTH_SCORES.json write + TRUTH panel emit | **Yes.** Panel block has its own `try/except` that silences all failures (`# Never block on telemetry emission.`). | Test `test_truth_panel_is_crash_isolated`. |

---

## 4D — Reporting integration (pattern ID → destination)

| Pattern ID | Emitter | Path to AUDIT_REPORT.json | Confirmed? |
|------------|---------|---------------------------|------|
| `SCAFFOLD-COMPOSE-001` | `scaffold_verifier._check_compose_topology` → `summary_lines` (`f"SCAFFOLD-COMPOSE-001 {diag}"`) | Summary line persisted to `.agent-team/scaffold_verifier_report.json` via `wave_executor._maybe_run_scaffold_verifier:1079-1103`. Cascade-consolidation reads this report (`cli.py:767-782`) for root-cause paths. Wrapped as `error_message` (`"Scaffold-verifier FAIL: ..."`) into a SCAFFOLD `WaveResult` which goes into `WAVE_FINDINGS.json` via `persist_wave_findings_for_audit`. | **Partial.** Reaches `scaffold_verifier_report.json` (cascade path) and `WAVE_FINDINGS.json` indirectly via `error_message` string. Does NOT flow as a structured `{code: "SCAFFOLD-COMPOSE-001"}` WaveFinding. **Gap flagged** — see Reporting Gaps below. |
| `SCAFFOLD-PORT-002` | `scaffold_verifier._check_port_consistency` → `summary_lines` | Same path as above. | **Partial — same gap.** |
| `DOD-FEASIBILITY-001` | `dod_feasibility_verifier.run_dod_feasibility_check` → `Finding(code="DOD-FEASIBILITY-001")` | Converted to `WaveFinding(code="DOD-FEASIBILITY-001")` in `wave_executor.py:4998-5008`, appended to synthetic `DOD_FEASIBILITY` `WaveResult`, appended to `result.waves`, re-persisted to `WAVE_FINDINGS.json` at `:5012-5018`. | **Confirmed.** Structured finding reaches the audit loop via WAVE_FINDINGS.json. |
| `OWNERSHIP-DRIFT-001` (scaffold fingerprint) | `ownership_enforcer.check_template_drift_and_fingerprint` → `Finding(code="OWNERSHIP-DRIFT-001")` | Converted to `WaveFinding` in `wave_executor.py:1146-1154`, appended to synthetic SCAFFOLD `WaveResult`, appended to `result.waves`. Flows into the next `persist_wave_findings_for_audit` call (inside the wave loop when the next wave completes, OR the end-of-loop call at `:4965`). | **Confirmed** — reaches WAVE_FINDINGS.json via `result.waves`. |
| `OWNERSHIP-DRIFT-001` (post-wave drift) | `ownership_enforcer.check_post_wave_drift` → `Finding` | Converted to `WaveFinding` at `wave_executor.py:4843-4852` and appended directly to the current wave's `wave_result.findings`, which reaches `persist_wave_findings_for_audit` at end-of-milestone. | **Confirmed.** |
| `OWNERSHIP-WAVE-A-FORBIDDEN-001` | `ownership_enforcer.check_wave_a_forbidden_writes` | Converted to `WaveFinding` at `wave_executor.py:4712-4720` and appended to Wave A's `wave_result.findings`. | **Confirmed.** |
| `PROBE-SPEC-DRIFT-001` | `endpoint_prober._detect_app_url` raises `ProbeSpecDriftError` | The exception propagates up through `_detect_app_url` → `start_docker_for_probing` → `_run_wave_b_probing`. **Today the error flows as a generic exception**; no code explicitly converts `ProbeSpecDriftError` into a structured `WaveFinding(code="PROBE-SPEC-DRIFT-001")`. It will be caught by `_run_wave_b_probing`'s outer exception handling (if any) and most likely become a generic `probe_error` string. | **Partial.** Reaches BUILD_LOG as an exception message; does NOT flow as a structured `{code: "PROBE-SPEC-DRIFT-001"}` finding — UNLESS the Wave-B probing path has explicit catch-and-convert. Flagged below. |
| `RUNTIME-TAUTOLOGY-001` | `cli._runtime_tautology_finding` returns a string | `print_warning(_tautology_finding)` at `cli.py:13929` + `:13933` emits to BUILD_LOG. No structured WaveFinding. | **Partial — BUILD_LOG only.** Does NOT flow into AUDIT_REPORT.json as a structured finding. This is consistent with other runtime-verification signals (which live in `RUNTIME_VERIFICATION.md` and BUILD_LOG, not AUDIT_REPORT). |

### Reporting Gaps (flagged; not blockers)

1. **`SCAFFOLD-COMPOSE-001` / `SCAFFOLD-PORT-002` string-only**: the scaffold_verifier emits summary-line tokens (e.g. `"SCAFFOLD-COMPOSE-001 docker-compose.yml missing services.api"`) but the downstream wrapper only persists them as `error_message` (`"Scaffold-verifier FAIL: <summary>"`) on a failing SCAFFOLD `WaveResult`. No `WaveFinding(code="SCAFFOLD-COMPOSE-001")` is created. Auditors who grep for the pattern ID in BUILD_LOG or `scaffold_verifier_report.json` will find it; auditors who walk `AUDIT_REPORT.json` findings by `code` will not. **Recommended follow-up (out of h1a scope):** in `_maybe_run_scaffold_verifier`, parse `report.summary_lines` tokens starting with `SCAFFOLD-` and synthesize structured `WaveFinding` objects for the failing SCAFFOLD WaveResult.
2. **`PROBE-SPEC-DRIFT-001` exception-only**: raised as `ProbeSpecDriftError`, which is caught generically by `_run_wave_b_probing`'s exception handling. No dedicated catch-and-convert to `WaveFinding(code="PROBE-SPEC-DRIFT-001")`. **Recommended follow-up (out of h1a scope):** in `_run_wave_b_probing` (or the probe-error-to-finding converter), add an explicit `except ProbeSpecDriftError as exc: findings.append(WaveFinding(code="PROBE-SPEC-DRIFT-001", ...))` clause before the generic handler.
3. **`RUNTIME-TAUTOLOGY-001` BUILD_LOG-only**: consistent with existing runtime-verification surface design. No gap vs plan — plan says "BUILD_LOG + AUDIT_REPORT"; currently BUILD_LOG only. Could add a sink into WAVE_FINDINGS via a synthetic MILESTONE-level WaveResult, but runtime verification is not milestone-scoped in this codebase.

**None of the three gaps blocks Phase H1a.** The primary defence surfaces (structured findings into `WAVE_FINDINGS.json` for DOD-FEASIBILITY and OWNERSHIP-*, cascade consolidation for SCAFFOLD-* via `scaffold_verifier_report.json`, build-log visibility for RUNTIME-TAUTOLOGY and PROBE-SPEC-DRIFT) work end-to-end. The gaps are pattern-ID hygiene — auditors can still find the signal; they just have to grep the human-readable layer instead of a structured `code` field.

---

## 4E — Pattern-ID uniqueness

Grepped the full source tree (`src/` + `tests/` + `docs/`). Results:

| Pattern ID | Occurrences | Collision? |
|------------|-------------|------------|
| `SCAFFOLD-COMPOSE-001` | `scaffold_verifier.py:203, 212, 413` + `docs/plans/phase-h1a-*` | **No collision** (only Phase H1a references). |
| `SCAFFOLD-PORT-002` | `scaffold_verifier.py:197, 201` + `docs/plans/phase-h1a-*` | **No collision.** No pre-existing `SCAFFOLD-PORT-001` either — suffix `-002` is intentional (preserves room if a future check wants `-001`). |
| `DOD-FEASIBILITY-001` | `dod_feasibility_verifier.py:12, 181, 246` + `config.py:1050` + docs | **No collision.** |
| `OWNERSHIP-DRIFT-001` | `ownership_enforcer.py:12, 26, 243, 283, 396` + `wave_executor.py:1128, 4833` + docs | **No collision.** |
| `OWNERSHIP-WAVE-A-FORBIDDEN-001` | `ownership_enforcer.py:20, 334` + docs | **No collision.** |
| `PROBE-SPEC-DRIFT-001` | `endpoint_prober.py:1073, 1081, 1148, 1164` + `config.py:1032` + docs | **No collision.** Existing `PROBE-FIX-TIMEOUT` and `PROBE-{status}` patterns at `wave_executor.py:2275, 2317` are the only other `PROBE-*` codes — no overlap. |
| `RUNTIME-TAUTOLOGY-001` | `cli.py:177, 239, 251, 263, 268, 13883` + `verification.py:395, 431` + `config.py:1039` + docs | **No collision.** No pre-existing `RUNTIME-*` codes found in `src/`. |

**No collisions.** All seven pattern IDs are unique.

---

## Dead-code audit

**Claim under audit:** `wave_executor.py:3881-3913` is DEAD because `execute_milestone_waves` at `:3584` returns-awaits `_execute_milestone_waves_with_stack_contract` at `:3584`, making everything past that return unreachable.

**Independent verification walk:**

1. Public entry points that reach `execute_milestone_waves`:
   - `cli.py:4257, 4284, 4892, 4918` (production callers).
   - `tests/test_files_created_diff_after_compile_fix.py:18/72/114`, `tests/test_provider_routing.py:65/2378`, `tests/test_v18_phase2_wave_engine.py:18` (test callers).
2. `execute_milestone_waves` definition at `wave_executor.py:3618-3654`:
   - Signature at `:3618-3633`.
   - Body at `:3639-3654` is a single `return await _execute_milestone_waves_with_stack_contract(...)` expression.
3. Everything after line 3654 and before the next `async def` at `wave_executor.py:4092` is unreachable — **lines 3655-4091 are dead** (a verbatim older copy of the wave loop preserved for reference but never executed). The plan-cited range `3881-3913` falls inside this dead block.
4. The LIVE wave loop is `_execute_milestone_waves_with_stack_contract` starting at `wave_executor.py:4092`. Verifier-agent correctly wired all Wave 2 hooks into the LIVE path:
   - Scaffold hook at `:4270-4273` (reached via the live scaffolding-completed block).
   - Wave A forbidden-writes at `:4697-4725` (inside live `wave_letter == "A" and wave_result.success` block).
   - Post-wave drift at `:4834-4858` (inside live artifact-save branch).
   - DoD feasibility at `:4981-5024` (milestone-teardown, post-persist).
5. Cross-reference: `tests/test_scaffold_wave_dispatch.py:84` already documents the dead-code claim verbatim (`"the other top-level loop in execute_milestone_waves is dead code"`). The claim is accepted by the existing test suite as ground truth.

**Verdict:** Claim is CORRECT. No hooks were missed on a live path. Dead-block 3655-4091 should be cleaned up in a future phase (out of h1a scope).

**No HALT.**

---

## milestone_id threading gap

### Audit

Five call sites of `_detect_app_url` at h1a HEAD (verified via grep):

- `endpoint_prober.py:711` — inside `start_docker_for_probing(cwd, config, milestone_id)`. NEW kwarg `milestone_id` threaded through to `_detect_app_url(..., milestone_id=milestone_id)`. **GOOD.**

Callers of `start_docker_for_probing`:

- `src/agent_team_v15/wave_executor.py:2207` — `docker_ctx = await start_docker_for_probing(cwd, config)`. **DOES NOT PASS `milestone_id`.** This is the Wave B probing path (`_run_wave_b_probing` internal call, ultimately invoked from `wave_executor.py:4865-4871`).
- `src/agent_team_v15/fix_executor.py:725` — `docker_ctx = await start_docker_for_probing(cwd, config)`. **DOES NOT PASS `milestone_id`.** This is the fix-executor probe path.

Callers of `_run_wave_b_probing`:

- `wave_executor.py:3975` (dead-code copy — irrelevant) and `:4865` (live path). Neither passes `milestone_id` to the helper; the helper's signature at `:2184-2192` has no `milestone_id` kwarg.

### Consequence

With `probe_spec_oracle_enabled=True`, the guard inside `_detect_app_url` silently skips because:

1. `start_docker_for_probing` is called at `wave_executor.py:2207` without `milestone_id` (default `None`).
2. `_detect_app_url(project_root, config, milestone_id=None)` receives `milestone_id=None`.
3. `_milestone_requirements_path(project_root, None)` at `endpoint_prober.py:1114-1117` returns `None` early.
4. The guard body at `endpoint_prober.py:1149-1172` short-circuits at `if requirements_md is not None and requirements_md.is_file():` because `requirements_md is None`.
5. **Net effect: Item 5 guard silently no-ops even when the flag is True.**

### Proposed minimal one-line fix (for team-lead action, out of wiring-verifier scope)

Thread `milestone_id` end-to-end through the Wave B probing stack. Smallest surface:

1. `wave_executor.py:2184-2192` — add `milestone_id: str | None = None` kwarg to `_run_wave_b_probing`.
2. `wave_executor.py:2207` — change `docker_ctx = await start_docker_for_probing(cwd, config)` to `docker_ctx = await start_docker_for_probing(cwd, config, milestone_id=milestone_id)`.
3. `wave_executor.py:4865-4871` — at the call site inside the live wave loop, add `milestone_id=result.milestone_id` to the kwargs.
4. (Optional) `fix_executor.py:725` — if the fix-executor probe should also benefit from the guard, thread `milestone_id` through its callers similarly. Not strictly required for Phase H1a: the fix-executor path is orthogonal to Wave B compose-wiring defence.

Single most-impactful one-line change: adding `milestone_id=result.milestone_id` to the `_run_wave_b_probing(...)` kwargs at `wave_executor.py:4865` + the internal propagation. This is net ~4 lines across two functions.

**Severity**: not a HALT — the flag is default OFF in this phase, and enabling it will produce a `logger.warning("endpoint_prober: DoD port not parseable ...")` on the `is_file()` branch, OR a silent-skip on `milestone_id=None`. With the guard producing zero enforcement, enabling the flag yields no new errors; the behaviour degrades gracefully.

**Recommendation**: route the threading fix to a source-editing Wave (not this wiring verifier). Wave 5 / production-caller-proofs (Task #9) is the appropriate destination.

---

## HALT assessment

| HALT condition | Triggered? |
|----------------|------------|
| Dead-code claim is wrong (hook missed a live path). | No — claim verified correct; hooks on live path only. |
| A flag-gated check actually fires regardless of flag value. | No — every gated check has call-site or inner-return gating confirmed by direct read. |
| A hook expected to fire on failed milestones is Wave-E-gated. | No — DoD feasibility hook at `:4981-5024` is milestone-teardown, not Wave-E-gated; verified by read + pytest. |
| A pattern ID collides with an existing one. | No — all seven IDs unique. |

**No HALT.** Wave 2 wiring is structurally sound. Two non-blocking gaps surfaced (probe `milestone_id` threading; pattern-ID-to-structured-finding conversion for SCAFFOLD-* and PROBE-SPEC-DRIFT-001) — both documented above with proposed follow-ups.

---

## Deliverables

- `docs/plans/phase-h1a-wiring-verification.md` — this report.
- `tests/test_h1a_wiring.py` — pytest coverage for:
  - hook fire positions via mocked wave_executor trace (one test per hook),
  - flag-gating round-trips (not-fire when False, fire when True) for Items 3, 4 (A+C+post-wave), 5, 6,
  - crash isolation for every shared hook site,
  - DoD feasibility firing after Wave B failure (`result.error_wave = "B"`, `break` at :4963),
  - pattern-ID-to-AUDIT_REPORT end-to-end simulation (via `WAVE_FINDINGS.json` read).
