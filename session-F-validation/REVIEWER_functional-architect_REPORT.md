# Functional Architect Reviewer Report

## Summary

- **Findings: 6** (4 CRITICAL, 1 MEDIUM, 1 LOW)
- **Fixes applied: 0** (HALT sent to team-lead per inviolable rule #6 — see
  F-ARCH-001..004 disposition; awaiting wiring decision before dispatching
  fixers.)
- **Unfixed: 6** (all awaiting team-lead arbitration; 4 CRITICAL findings
  represent a structural gap the sweeper delivered but never integrated.)

Primary conclusion: **the pipeline WILL NOT COHERE as a unified system on
the production smoke**. Phase F's ~1,035 LOC of new modules
(`wave_b_sanitizer`, `audit_scope_scanner`, `infra_detector`,
`confidence_banners`) is entirely orphaned — the sweeper landed module
source + isolation tests + config flags but **no call sites**. All four
flags default `True`, so operators reading the config believe the hooks
are active; in reality nothing is wired. A real build will pass 10,530
pytests and still ship the exact surface gaps (Wave B orphans, silent
audit passes, no api_prefix detection, no report confidence banners) the
Phase F plan was written to close.

The remaining architecture (budget softening, D-02 `infra_missing`, N-11
Wave D cascade extension, N-17 pre-fetch, scaffold verifier gating) is
structurally sound.

## Methodology

Sequential-thinking across the 5 required areas (wave sequencing, flag
interactions, recovery paths, multi-milestone state, Phase F-specifics).
All framework claims verified against code — no training-data shortcuts
were used. Evidence is citation-backed (file:line) rather than narrative.
Context7 was not required for this pass because the critical finding
is integration absence, not framework-usage correctness — framework
behaviour would be relevant if call sites existed to audit.

Verification pattern for F-ARCH-001..004:

```
grep -rn "wave_b_sanitizer|audit_scope_scanner|infra_detector|\
          confidence_banners" src/agent_team_v15/
# -> only hits are comments in config.py, plus self-references in the
#    four module files. Zero imports from cli.py or wave_executor.py.

grep -rn "sanitize_wave_b|scan_audit_scope|detect_runtime_infra|\
          stamp_all_reports|build_probe_url|build_scope_gap_findings|\
          build_orphan_findings" src/agent_team_v15/
# -> only hits are doc-string references in config.py.

git status
# -> all four modules are untracked files in phase-f-final-review.
```

## Findings

### F-ARCH-001: Wave B sanitizer (N-19) is never invoked

**Severity:** CRITICAL
**Area:** Wave sequencing and handoffs
**File:line:** `src/agent_team_v15/wave_b_sanitizer.py:238` (defined);
expected call site is `src/agent_team_v15/wave_executor.py:3222`
(immediately after `_maybe_cleanup_duplicate_prisma` on Wave B success).
**Evidence:**

```
$ grep -rn "sanitize_wave_b\|wave_b_sanitizer" src/agent_team_v15/ \
      | grep -v wave_b_sanitizer.py
# only hit: config.py docstring
```

The post-Wave-B success branch in `wave_executor.py:3206-3222`:

```python
if wave_letter == "B" and compile_result.passed:
    dto_guard = await _run_wave_b_dto_contract_guard(...)
    if dto_guard.findings:
        wave_result.findings.extend(dto_guard.findings)
    compile_result.iterations += dto_guard.compile_iterations
    compile_result.fix_cost += dto_guard.fix_cost
    # NEW-1: remove stale apps/api/src/prisma/ duplicates now
    # that Wave B content has stabilized. Flag-gated, no-op when
    # disabled (default). See _maybe_cleanup_duplicate_prisma.
    _maybe_cleanup_duplicate_prisma(cwd=cwd, config=config)
    # <-- N-19 sanitizer call missing here.
```

**Analysis:**
The sweeper report (SWEEPER_REPORT.md, Touch 5) claims:
> "Post-Wave-B hook: compares emitted files against the ownership
> contract (`docs/SCAFFOLD_OWNERSHIP.md`). Any Wave B emission in a
> scaffold-owned path is flagged as an orphan candidate."

No hook is registered. The module exists, passes 10 unit tests in
isolation, and has a flag (`v18.wave_b_output_sanitization_enabled`
default `True`), but `sanitize_wave_b_outputs(...)` is never called
between Wave B emission and Wave C consumption. Production smoke will
ship Wave B orphans exactly as before Phase F. The flag default `True`
is misleading: operators see "sanitization enabled" in the config but
the hook is a no-op.

**Proposed fix (structural):**

1. In `wave_executor.py`, after `_maybe_cleanup_duplicate_prisma(...)`
   on Wave B success, add:

   ```python
   if wave_letter == "B" and compile_result.passed:
       ...
       _maybe_cleanup_duplicate_prisma(cwd=cwd, config=config)
       try:
           from .scaffold_runner import load_ownership_contract
           from .wave_b_sanitizer import (
               sanitize_wave_b_outputs,
               build_orphan_findings,
           )
           contract = load_ownership_contract()
           sani_report = sanitize_wave_b_outputs(
               cwd=cwd,
               contract=contract,
               wave_b_files=(
                   wave_result.files_created
                   + wave_result.files_modified
               ),
               config=config,
           )
           for payload in build_orphan_findings(sani_report):
               wave_result.findings.append(
                   WaveFinding(
                       code=payload["finding_id"],
                       severity=payload["severity"],
                       file=payload["evidence"][0].replace("path: ", ""),
                       line=0,
                       message=payload["summary"],
                   )
               )
       except (FileNotFoundError, ValueError) as exc:
           logger.info("N-19 sanitizer skipped: %s", exc)
   ```

2. Add one integration test in
   `tests/test_wave_b_sanitizer_integration.py` that constructs a fake
   Wave B emission set plus a fixture contract and asserts
   `WaveFinding(code="N-19-ORPHAN-...")` is appended. Keep existing
   tests passing; do not modify the sanitizer's behavior tests.

3. Verify: `pytest tests/test_wave_b_sanitizer.py tests/test_wave_b_sanitizer_integration.py` — expect 10 existing + 1 new = 11 passing, zero regressions.

**Fix status:** NOT_APPLIED_RATIONALE — HALT sent to team-lead. This is
structural integration affecting the primary wave path; parallel reviewers
(runtime-behavior, integration-boundary) may also touch `wave_executor.py`
this window. Dispatching a fixer without team-lead coordination risks a
merge conflict and/or a concurrent-modification test-suite regression.

---

### F-ARCH-002: Audit scope scanner never runs before the LLM auditor

**Severity:** CRITICAL
**Area:** Wave sequencing and handoffs
**File:line:** `src/agent_team_v15/audit_scope_scanner.py:199`
(defined); expected call site is
`src/agent_team_v15/cli.py:5853` (inside `_run_milestone_audit`) or
`cli.py:6481` (start of `_run_audit_loop`, before cycle 1).
**Evidence:**

```
$ grep -rn "scan_audit_scope\|audit_scope_scanner\|build_scope_gap_findings" \
      src/agent_team_v15/ | grep -v audit_scope_scanner.py
# only hit: config.py docstring
```

`_run_audit_loop` at `cli.py:6431-6655` and `_run_milestone_audit` at
`cli.py:5853` both construct auditors and findings without ever calling
the scope scanner. The flag `v18.audit_scope_completeness_enabled`
defaults `True`, and the config.py docstring explicitly states "the
audit pipeline runs `audit_scope_scanner` before the LLM scorer" —
that claim is currently false.

**Analysis:**
Silent-pass regressions are exactly the class of defect the scope
scanner was written to catch. Without wiring it, a requirement that
names e.g. "arabic RTL support" but whose N-10 scanner is disabled will
still show GREEN in the audit; that's the production-smoke failure mode
the sweeper intended to close. The module emits INFO-severity
meta-findings so there is no risk of false-positive gating even if
wired in naively.

**Proposed fix (structural):**

1. Inside `_run_milestone_audit` (cli.py:5853), immediately before
   the LLM scorer invocation, add:

   ```python
   from .audit_scope_scanner import scan_audit_scope, build_scope_gap_findings
   scope_gaps = scan_audit_scope(
       cwd=cwd,
       requirements_path=requirements_path,
       config=config,
   )
   scope_findings_payload = build_scope_gap_findings(scope_gaps)
   # merge into the final AUDIT_REPORT.findings list after the LLM scorer
   # returns — the scope findings are INFO so they never gate on their own.
   ```

2. Merge `scope_findings_payload` into the scorer's returned finding
   list before `report_path.write_text(...)` at cli.py:6651.

3. Verify: `pytest tests/test_audit_scope_scanner.py` (12 existing) +
   add one `test_run_audit_loop_includes_scope_findings` integration
   test; expect 12+1 = 13 passing.

**Fix status:** NOT_APPLIED_RATIONALE — HALT sent to team-lead. Paired
with F-ARCH-004 below (both modify audit loop exit path); suggest a
single fixer handle both to avoid double-edit risk.

---

### F-ARCH-003: Broader runtime infra detector never called at probe time

**Severity:** CRITICAL
**Area:** Wave sequencing and handoffs
**File:line:** `src/agent_team_v15/infra_detector.py:167` (defined);
expected call sites are
`src/agent_team_v15/endpoint_prober.py:1023` (`_detect_app_url`) and
`src/agent_team_v15/wave_executor.py:1863` (`_run_wave_b_probing`).
**Evidence:**

```
$ grep -rn "detect_runtime_infra\|build_probe_url\|infra_detector" \
      src/agent_team_v15/ | grep -v infra_detector.py
# only hit: config.py docstring
```

**Analysis:**
NestJS 11 projects emit `setGlobalPrefix('api')` in
`apps/api/src/main.ts` so every endpoint lives under `/api/...`. Phase
A's `endpoint_prober._detect_app_url` only resolves the base URL
(host:port). Without the infra detector, probes will hit
`http://localhost:3080/users` instead of `http://localhost:3080/api/users`,
and every probe will 404 unless the scaffold emits `api/` in every
handler path — which it does not. Phase F §7.5's prefix-aware probe URL
assembly (`build_probe_url(app_url, route, infra=...)`) is precisely
designed for this; the module is correct; it is simply never called.

For M1 stacks with `setGlobalPrefix`, probes will skip (
`wave_executor.py:1910: return False, reason, []`) as "real signal" →
Wave B fails → Wave C never dispatches → full pipeline halt on a
misconfigured probe URL. The defect masks as a Wave B failure when the
actual cause is a missing `/api` prefix.

**Proposed fix (structural):**

1. In `wave_executor._run_wave_b_probing`, fetch infra once up front:

   ```python
   from .infra_detector import detect_runtime_infra, build_probe_url
   infra = detect_runtime_infra(cwd, config=config)
   # pass `infra` into `generate_probe_manifest` or post-process the
   # generated manifest's probe URLs via `build_probe_url(app_url, route, infra=infra)`.
   ```

2. In `endpoint_prober.generate_probe_manifest`, accept an optional
   `infra: RuntimeInfra | None = None` kwarg; when present, route
   paths through `build_probe_url` before emitting. When absent,
   preserve current behavior byte-identically.

3. Verify: `pytest tests/test_infra_detector.py` (19 existing) + one
   integration test
   `tests/test_endpoint_prober_uses_infra_prefix.py` that constructs a
   workspace with `setGlobalPrefix('api')` in a mock main.ts and
   asserts the manifest URLs include `/api/`. Expect 19+1 = 20
   passing, zero regressions.

**Fix status:** NOT_APPLIED_RATIONALE — HALT sent to team-lead. Paired
with runtime-behavior reviewer's likely touchpoint in endpoint_prober;
if runtime-behavior is also editing probe URL assembly there is a very
real merge-conflict risk.

---

### F-ARCH-004: Confidence banners never stamped on any report

**Severity:** CRITICAL
**Area:** Multi-milestone state (reports span every milestone)
**File:line:** `src/agent_team_v15/confidence_banners.py:257`
(`stamp_all_reports` defined); expected call site is
`src/agent_team_v15/cli.py` immediately after `_run_audit_loop` returns
or at orchestration finalize.
**Evidence:**

```
$ grep -rn "stamp_all_reports\|confidence_banners\|ConfidenceSignals" \
      src/agent_team_v15/ | grep -v confidence_banners.py
# only hit: config.py docstring
```

**Analysis:**
Operators triaging a completed smoke will look at `AUDIT_REPORT.json`,
`BUILD_LOG.txt`, `GATE_*_REPORT.md`, and `*_RECOVERY_REPORT.md` — none
will carry the `confidence` field or banner line the Phase F plan
advertises. D-14 fidelity labels on the four verification artefacts
remain intact (verified at `mcp_servers.py:534-561`), so the subset of
users who only read those 4 files see fidelity — but the generalisation
promised by Phase F §7.10 is not delivered.

Not a gating risk per se, but a trust-signal gap that will be
interpreted as "everything is CONFIDENT" by default when in reality
nothing has been asserted about the underlying signals.

**Proposed fix (structural):**

1. After `_run_audit_loop` returns in cli.py, gather `ConfidenceSignals`
   from the already-tracked state (`state.evidence_mode`,
   `state.scanners_run`, `state.scanners_total`, convergence /
   plateau flags, `docker_ctx.api_healthy`), then call
   `stamp_all_reports(agent_team_dir=Path(cwd)/".agent-team", signals=signals, config=config)`.

2. Alternatively, add a single `_finalize_reports` helper at
   orchestration-end (mirrors "end-of-run" semantics) and call
   `stamp_all_reports` from there.

3. Verify: `pytest tests/test_confidence_banners.py` (17 existing) +
   one integration test that creates a fake `.agent-team/` tree with
   an AUDIT_REPORT.json and asserts `stamp_all_reports` returns
   non-empty `touched` after orchestration. Expect 17+1 = 18 passing.

**Fix status:** NOT_APPLIED_RATIONALE — HALT sent to team-lead.

---

### F-ARCH-005: Phase F Wave D cascade extension is gated by a
default-OFF flag

**Severity:** MEDIUM
**Area:** Flag interactions
**File:line:** `src/agent_team_v15/cli.py:696`
(`_consolidate_cascade_findings` early-return) and
`src/agent_team_v15/config.py:872` (`cascade_consolidation_enabled`).
**Evidence:**

```
# cli.py:696
if not _cascade_consolidation_enabled(config) or not cwd:
    return report

# config.py:872
cascade_consolidation_enabled: bool = False
```

**Analysis:**
The sweeper's Touch 1 ("Extend N-11 cascade to Wave D failures")
correctly augments `_consolidate_cascade_findings` to read
`state.wave_progress` and include Wave-D roots (`apps/web`,
`packages/api-client`). Touch 1 is well-wired. BUT the entire function
short-circuits when `cascade_consolidation_enabled=False` (Phase B
default-off flag). For a stock Phase F smoke — where the Phase B flag
is left at its default `False` — Touch 1 adds zero behavior. Operators
who flip only the Phase F flags (as the sweeper report implies) will
not see Wave D cascade consolidation.

**Proposed fix (structural):**
EITHER (a) flip `cascade_consolidation_enabled` default to `True` for
Phase F (documented as part of the Phase F flag set), OR (b) introduce
a separate `wave_d_cascade_enabled` flag so Wave D consolidation
decouples from the Phase B scaffold-cascade opt-in. Option (a) is
simpler and closer to the sweeper's stated intent; option (b) honors
backward compat.

**Fix status:** NOT_APPLIED_RATIONALE — HALT sent to team-lead; depends
on the product decision about Phase F default-on posture.

---

### F-ARCH-006: `derive_confidence` returns CONFIDENT when
`scanners_total == 0`

**Severity:** LOW
**Area:** Phase F specific (edge case)
**File:line:** `src/agent_team_v15/confidence_banners.py:99-103`
**Evidence:**

```python
# confidence_banners.py:99-103
if scanner_ratio > 0 and scanner_ratio < 0.5:
    return CONFIDENCE_LOW, reasoning
if mode == "soft_gate" and signals.fix_loop_converged and (
    signals.scanners_total == 0 or scanner_ratio >= 0.99
) and signals.runtime_verification_ran:
    return CONFIDENCE_CONFIDENT, reasoning
```

**Analysis:**
When a build configuration has no post-Wave-E scanners wired
(`scanners_total = 0`, `scanners_run = 0`), the condition
`signals.scanners_total == 0 or scanner_ratio >= 0.99` is True and the
function returns CONFIDENT provided the fix loop converged and runtime
verification ran. That's arguably correct ("no scanners demanded →
nothing to fail") but it can mask a misconfiguration where scanners
SHOULD have been registered but were silently skipped. Downgrading to
MEDIUM when `scanners_total == 0` would be more defensive and better
match the stated intent ("never tells an operator CONFIDENT when
evidence is missing").

This is irrelevant as long as F-ARCH-004 stays unfixed (the module is
never called). Once F-ARCH-004 is wired, this edge case becomes
observable.

**Proposed fix (structural):**
Change the CONFIDENT gate from `scanners_total == 0 OR
scanner_ratio >= 0.99` to `scanners_total > 0 AND scanner_ratio >= 0.99`.
`scanners_total == 0` should fall through to MEDIUM with a reasoning
note: "no post-Wave-E scanners registered — cannot assert completeness".

**Fix status:** NOT_APPLIED_RATIONALE — deferred until F-ARCH-004 is
addressed; fixing the edge case in isolation has no runtime effect.

---

## Areas verified without new findings

### Area 1: Wave sequencing and handoffs (partial) — scaffold verifier
- Phase B's N-13 scaffold verifier: verified at
  `wave_executor.py:3699-3701` to run after Wave A only when
  `scaffold_verifier_enabled=True`. Failure halts before Wave B
  dispatch. Structurally correct.
- Phase C's N-17 pre-fetch: verified at `cli.py:3946-3960` to lazy-fetch
  Context7 idiom docs from `_build_wave_prompt_with_idioms` BEFORE
  `_build_wave_prompt` returns. Fires once per milestone per wave (B,
  D); cache at `.agent-team/framework_idioms_cache.json`. D-01
  unavailability note emits when pre-fetch returns empty. Structurally
  correct.

### Area 2: Flag interactions — OOS-3 validated
- Phase A OOS-3's fix for `ownership_contract_enabled=True` +
  `scaffold_verifier_enabled=False` combo: verified in
  `scaffold_runner.py:346-357` — when ownership-contract is on but the
  verifier is off, the validator still runs a soft warning at
  `scaffold_runner.py:370-380`. No crash path.
- Phase F net flag defaults: 4 new flags all default `True`, but
  F-ARCH-001..004 document that all four are orphaned. Flag semantics
  are currently a promise the code does not keep.

### Area 3: Recovery paths
- `RuntimeBlockedError`: confirmed it does not exist (Phase C HALT-1);
  D-02 uses `DockerContext.infra_missing: bool` flag, verified at
  `endpoint_prober.py:104-119` and `wave_executor.py:1902`. The
  consumer correctly distinguishes "infra genuinely absent → skip" from
  "infra present but app not healthy → block". No pseudo-skip regression.
- Budget softening: verified no non-terminating loops. `_run_audit_loop`
  still bounded by `max_cycles` (`cli.py:6450,6530`), plateau detection
  (`cli.py:6618-6628`), regression rollback (`cli.py:6604-6611`).
  `coordinated_builder._run_after_audit` still bounded by
  `max_iterations` (advisory budget warning at `coordinated_builder.py:597-602`).
  `runtime_verification.MaxRoundsGuard` still bounded at
  `runtime_verification.py:679-685,719-720`. Loops terminate.

### Area 4: Multi-milestone state
- N-11 Wave D cascade: `_load_wave_d_failure_roots(cwd)` at
  `cli.py:626-668` iterates all `state.wave_progress` entries (not M1
  only). Works correctly for M2..M6 when `failed_wave == "D"` is
  recorded on any milestone.
- Confidence banner multi-milestone: `stamp_all_reports` at
  `confidence_banners.py:280-307` walks both `root.glob("AUDIT_REPORT.json")`
  AND `root.glob("milestones/*/AUDIT_REPORT.json")`. Idempotent per
  artefact. Would work correctly IF called — see F-ARCH-004.

### Area 5: Phase F-specific edge cases
- `wave_b_sanitizer`: `contract is None` → graceful skip with
  `skipped_reason="no_contract"` (no FileNotFoundError). Fail-open.
- `audit_scope_scanner`: missing / malformed REQUIREMENTS.md →
  `_parse_requirements_md` returns `[]`; `scan_audit_scope` returns
  `[]`; no exception. Fail-open.
- `infra_detector`: missing `apps/api/` → all detection paths return
  empty strings; empty `RuntimeInfra`; info log at line 222; no
  exception.
- N-19 `_scan_for_consumers` perf: uses `rglob` then filters by
  `skip_dirs` in `part` list. On large workspaces this walks the full
  tree, but the skip filter runs per-file, not per-dir, so
  `node_modules` contents ARE traversed before being rejected. Not
  a correctness bug but a perf surprise. Low priority.

## Cross-scope notes (not mine, flagged for team-lead arbitration)

- Test coverage: Part 3 (lockdown test engineer) should explicitly add
  integration tests for the new Phase F hooks once F-ARCH-001..004 are
  wired. Module-level isolation tests do not substitute for pipeline
  coverage.
- Potential runtime-behavior scope: F-ARCH-003 modifies
  `endpoint_prober`; please coordinate with the runtime-behavior
  reviewer if they plan edits to `_detect_app_url` or probe URL
  assembly.
- Potential integration-boundary scope: F-ARCH-001 / F-ARCH-002 both
  modify wave/audit control flow; please coordinate with the
  integration-boundary reviewer if they plan edits to wave dispatch or
  audit merging.

## Final verdict

- **Will this ~5,500 LOC cohere and function as a unified system?**
  No — not without wiring F-ARCH-001..004. Phases A-E are coherent and
  individually sound. Phase F delivered working modules but not working
  integration.
- **Is the architecture sound below the Phase F gap?**
  Yes, based on the evidence inspected in Areas 1-4. Recovery paths
  terminate, D-02 is structurally correct, N-11 Wave D extension is
  correctly wired into the consolidator, Budget softening preserves
  loop termination.
- **Recommended next step before smoke:**
  Dispatch a single coordinated fixer (preferred: re-task the Phase F
  sweeper) to wire the four orphaned modules per the proposed fixes
  above, add 4 integration tests (one per hook), and re-run the full
  suite to verify `10,530 + 4 = 10,534 passed, 0 failed`. Without the
  wiring, the Phase F flags misrepresent the live pipeline behavior.

_End of report._
