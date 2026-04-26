# Audit-Fix-Loop Guardrails — Phase 3.5 Handoff

**Date:** 2026-04-26
**Author:** Phase 3 / 1.5 implementer (handoff)
**Reader:** Phase 3.5 implementer (you)
**Predecessors:** Phase 1 (`6663cfe`) → Phase 2 (`7e5ed18`) → Phase 3 (`2b3004d`) → Phase 1.5 (`61a3630`)

---

## 0 — TL;DR

Phase 3 ships a per-feature PreToolUse path-allowlist hook that denies any audit-fix write outside `feature.target_files + sibling_test_files`. **The hook is a deterministic no-op when `target_files` is empty** — features without declared targets pass through with allow-all, defeating the kernel-level scope guard for that dispatch.

Phase 3.5 closes that hole. Two viable paths:

* **A — Ship-block free-form features** (default-deny). Refuse to dispatch any feature without `target_files`.
* **B — Force the fix-PRD generator to declare targets** (default-emit). Make every fix feature declare its surface during PRD construction, never empty.

Plus a third surface that Phase 1.5 explicitly deferred:

* **C — Hook coverage of `_run_full_build` subprocess path**. The full-build escalation runs a separate `agent-team-v15` subprocess; today the audit-fix scope env vars don't propagate into it.

This document specifies all three. Pick A or B for the ship-blocking path; C is independent and orthogonal.

---

## 1 — Why this matters

### 1.1 The Phase 3 gap (verbatim from `phase_3_landing.md`)

> **Free-form features without target_files** are NOT scope-bound today. The feature loop leaves env vars unset when target_files is empty, so the audit-fix hook becomes a no-op for that feature. Phase 3.5 candidate: ship-block free-form features OR force the fix PRD generator to emit explicit target_files for every feature. Anchor (Phase 1) + cross-milestone lock (Phase 2) remain the safety nets.

### 1.2 The actual code site

`src/agent_team_v15/cli.py` `_run_patch_fixes` (Phase 3 code, around line ~7340 after Phase 1.5's drift):

```python
# Phase 3 audit-fix-loop guardrail (§F AC1+AC4):
# per-dispatch path allowlist via env vars. ...
# Empty target_files: we leave the env vars unset for this
# iteration so the audit-fix hook stays in its no-op state
# rather than failing CLOSED on every write — a free-form
# feature that doesn't declare its surface cannot be scope-bound;
# the milestone-anchor (Phase 1) and cross-milestone test-surface
# lock (Phase 2) remain the safety nets there. Ship-blocking the
# free-form path is a Phase 1.5 candidate.
allowlist_paths: list[str] = []
if target_files:
    seen_paths: set[str] = set()
    for target in target_files:
        ...
        allowlist_paths.append(normalized)
        for sibling in derive_sibling_test_files(normalized):
            ...

finding_dispatch_id = f"AUDIT-FIX-R{run_number}-F{index:03d}"
prior_finding_id = os.environ.get("AGENT_TEAM_FINDING_ID")
prior_allowed_paths = os.environ.get("AGENT_TEAM_ALLOWED_PATHS")
if allowlist_paths:
    os.environ["AGENT_TEAM_FINDING_ID"] = finding_dispatch_id
    os.environ["AGENT_TEAM_ALLOWED_PATHS"] = ":".join(allowlist_paths)
```

The conditional `if allowlist_paths:` is the gap. When `target_files` is empty, neither env var is set; `audit_fix_path_guard.py` reads the unset `AGENT_TEAM_FINDING_ID` and short-circuits to `allow`, exactly as it does for non-audit-fix dispatches.

### 1.3 The risk

A free-form feature that touches `apps/api/src/auth.py` to "fix middleware" has zero scope binding under Phase 3. If the fix dispatch hallucinates an "improvement" to `prisma/schema.prisma` (which Phase 1's `_MILESTONE_ANCHOR_IMMUTABLE_DENYLIST` covers but the hook doesn't see), the milestone-anchor catches it on next audit-fail divergence — but the M25-disaster scenario was about MULTIPLE fixes compounding before any single trigger fires. Phase 3's intent was "no fix can write outside its scope, full stop." Phase 3.5 makes that property hold for **every** feature, not just declared-target ones.

### 1.4 How common are free-form features today?

**Unknown — needs measurement before deciding A vs B.** Run a smoke and grep `[FIX-PLAN]` log lines for features with empty `files_to_modify + files_to_create`. If the count is non-trivial (>5% of features), Path B (PRD generator change) is preferable; otherwise Path A (ship-block) is fine.

The `_classify_fix_features` function at `fix_executor.py:488` parses the fix PRD and assigns each feature `target_files`. The empty-target case happens when the auditor LLM emits a "general" finding without a file path → `_convert_findings` populates `Finding.file_path=""` → fix PRD generator emits a feature without `files_to_modify`.

**Suggested measurement command** (paste into a fresh investigation session):

```bash
# In a clean run-dir after one audit-fix cycle:
grep -E "files_to_(modify|create)" .agent-team/audits/*/fix_prd.md | head -50
```

---

## 2 — Path A: Ship-block free-form features

### 2.1 Behaviour

When `target_files` is empty for a feature, **skip the dispatch entirely**. Log a `[FIX-DENYLIST] feature {name} has no target_files; skipped per Phase 3.5` warning. The audit-fix loop continues to the next feature. The unfixed finding remains in the next audit cycle's report.

### 2.2 Implementation sketch

**File:** `src/agent_team_v15/cli.py` `_run_patch_fixes`

Add a guard at the top of the per-feature iteration:

```python
for index, feature in enumerate(patch_features, start=1):
    target_files = [...]  # existing computation
    target_files = list(dict.fromkeys(target_files))
    feature_name = str(...)

    if not target_files:
        # Phase 3.5: refuse to dispatch a free-form feature. The
        # audit-fix hook (Phase 3) cannot scope a dispatch with no
        # declared surface; allow-all violates the M25-disaster
        # prevention property. The unfixed finding will reappear in
        # the next audit cycle — operator may need to refine the
        # finding's primary_file or accept the milestone marked
        # FAILED.
        print_warning(
            f"[FIX-DENYLIST] feature {index}/{len(patch_features)} "
            f"({feature_name}) has no target_files; skipped to "
            f"preserve audit-fix scope binding (Phase 3.5)."
        )
        continue

    execution_mode = ...  # existing
    ...
```

### 2.3 Test fixtures

**File:** `tests/test_audit_fix_guardrails_phase3_5.py` (new)

```python
def test_free_form_feature_is_skipped_at_dispatch():
    # Mock _run_audit_fix_unified to dispatch a feature with empty
    # target_files. Assert: no ClaudeSDKClient call; warning logged;
    # loop continues.
    ...

def test_targeted_features_continue_to_dispatch():
    # Mock two features: F1 with target_files=["apps/web/x.tsx"], F2
    # with empty target_files. Assert F1 dispatches, F2 skipped.
    ...
```

### 2.4 Trade-offs

* **Pro**: Preserves Phase 3's invariant ("every audit-fix write is hook-scoped") rigorously.
* **Pro**: Tiny diff; no PRD-generator surgery.
* **Con**: Some legitimate fixes silently dropped on the floor. The auditor may need to refine the finding (add `primary_file` evidence) for the fix to ship. This is a forcing function — visible in test runs as un-converged ACs.
* **Con**: If the empty-target rate is high, the audit-fix loop's effective coverage drops. Measure first.

### 2.5 Rollback

Revert the `if not target_files: continue` guard. Behaviour returns to Phase 3 (allow-all for free-form features).

---

## 3 — Path B: Force the fix-PRD generator to declare targets

### 3.1 Behaviour

The fix PRD generator (`fix_executor.generate_fix_prd` and `_classify_fix_features`) emits every feature with at least one entry in `files_to_modify` or `files_to_create`. When the auditor finding is "general" (no `primary_file`), the generator either:

* **B.1** — synthesises a target from the finding's evidence (regex over `evidence[]` for any path-shaped string).
* **B.2** — falls back to a designated "general findings file" (e.g., `.agent-team/audit-fix-general.md`) that the dispatch is allowed to write to.
* **B.3** — refuses to emit the feature at all (fail-loud at PRD-generation time, not dispatch time).

### 3.2 Implementation sketch

**Files:**
* `src/agent_team_v15/fix_executor.py` `generate_fix_prd` — surface
  `target_files` per feature explicitly.
* `src/agent_team_v15/fix_executor.py` `_classify_fix_features` — fail
  if a feature lacks `target_files` after generation.
* `src/agent_team_v15/audit_models.py` — extend `AuditFinding` with a
  `synthesise_primary_file()` method that walks `evidence[]` for
  path-shaped strings (regex `[\w./]+\.(py|ts|tsx|jsx|js)`).

The cleanest variant is **B.1 + B.3 combined**: synthesise where possible, fail-loud where not.

```python
# fix_executor.py:_classify_fix_features
features = _parse_fix_features(fix_prd_text)
for feature in features:
    files_to_modify = list(feature.get("files_to_modify", []))
    files_to_create = list(feature.get("files_to_create", []))
    if not files_to_modify and not files_to_create:
        raise FixPlanError(
            f"Feature {feature.get('name', '<unnamed>')} has no "
            "files_to_modify or files_to_create. Phase 3.5 requires "
            "every fix feature to declare its target surface so the "
            "audit-fix path-guard can scope the dispatch. Either: (a) "
            "extend the auditor finding with a primary_file in the "
            "evidence, or (b) re-run with audit_team.allow_general_"
            "findings=False to fail loudly at finding-conversion time."
        )
```

### 3.3 Test fixtures

```python
def test_fix_plan_rejects_feature_without_target_files():
    # Feed a fix PRD with a feature missing files_to_modify and
    # files_to_create. Assert FixPlanError raised at classification.
    ...

def test_fix_plan_synthesises_target_from_evidence():
    # Feed an AuditFinding with evidence=["apps/web/login.tsx:42 -- "
    # "missing await"]. Assert synthesise_primary_file returns
    # "apps/web/login.tsx".
    ...
```

### 3.4 Trade-offs

* **Pro**: Higher coverage — every audit finding gets a scope-bound fix attempt, even general ones.
* **Pro**: Failure mode is "loud at PRD generation" instead of "silent at dispatch", matching `feedback_structural_vs_containment.md`.
* **Con**: More invasive — touches the PRD generator path that's been stable for many phases.
* **Con**: Synthesise heuristic can extract wrong paths (e.g., a stack trace mentioning `node_modules/x.js`). Need to filter against the run-dir reality.

### 3.5 Rollback

Toggle a config flag `audit_team.allow_general_findings=True` to restore the legacy "allow free-form features" behaviour. Schema-additive; revert in code if the flag's UX is messy.

---

## 4 — Path C: Hook coverage of `_run_full_build` subprocess path

### 4.1 The gap

When `_run_audit_fix_unified` escalates to `_run_full_build` (full-builder rerun via subprocess), the audit-fix scope env vars (`AGENT_TEAM_FINDING_ID`, `AGENT_TEAM_ALLOWED_PATHS`) are deliberately NOT set — the inner orchestrator's wave dispatches (Wave A/B/C/D) need to be unrestricted by audit-fix scope.

But the inner orchestrator's OWN audit-fix loop (if it fires) would need its own scope binding. Today, the inner builder writes its own settings.json via `agent_teams_backend._ensure_wave_d_path_guard_settings` at first wave dispatch — Phase 3's settings.json writer DOES include the audit-fix-path-guard entry alongside Wave D's. So the hook is registered.

What's missing: the inner builder's `_run_audit_fix_unified` runs without inherited `AGENT_TEAM_FINDING_ID`, so the hook short-circuits to allow on every dispatch. The inner audit-fix has zero scope binding **inside** the subprocess.

### 4.2 Why this is hard

The subprocess is a fresh `agent-team-v15` invocation. The parent's per-feature loop in `_run_patch_fixes` doesn't run there — the inner builder runs its own waves and its own audit-fix. Setting env vars in the parent doesn't propagate the right scope (it propagates the parent's last feature's scope, which is wrong for the inner builder).

### 4.3 Possible approaches

* **C.1** — Don't propagate parent scope. Let the inner builder run its OWN per-feature scope binding (Phase 3 already does this). The settings.json writer ensures the hook is registered. This works **automatically** — no parent-side change needed. Verify with a smoke test.
* **C.2** — Mark the subprocess as "audit-fix escalation" via a new env var (`AGENT_TEAM_ESCALATED_FIX=1`) so the inner builder knows it's running in a scope-restricted context. Fail-CLOSED on any wave dispatch outside `apps/web/**` — basically run with Wave D scope by default. Aggressive; possibly breaks legitimate Wave A/B/C dispatches.
* **C.3** — Plumb `AGENT_TEAM_FINDING_ID` + `AGENT_TEAM_ALLOWED_PATHS` into the subprocess env. The inner builder's hook reads them. But the inner builder dispatches WAVES (not features), so the allowlist would block Wave A's `apps/api/**` writes etc. Very wrong.

**Recommendation: C.1 — verify the inner builder's per-feature scope binding works inside the subprocess via a smoke test. Document the verification.** No code change needed unless verification fails.

### 4.4 Test fixture

```python
def test_full_build_subprocess_has_per_feature_scope_binding():
    # Spawn _run_full_build with a tmp run-dir + audit-fix PRD.
    # Verify the inner builder writes .claude/settings.json with both
    # hook entries. Verify a hostile inner audit-fix attempt to write
    # outside its declared target_files is denied.
    # Likely needs a real (slow) end-to-end smoke; consider marking
    # @pytest.mark.slow or running in m1_fast_forward only.
```

---

## 5 — Decision matrix

| Question | Path A | Path B | Path C |
|---|---|---|---|
| Closes Phase 3 gap? | Yes | Yes | Partially (subprocess scope only) |
| Risk to existing fix coverage | Drops free-form fixes | Forces synthesis | None |
| Code blast radius | ~10 lines | ~50 lines + tests | ~0 lines (verification only) |
| Best when | Free-form features are rare | Free-form features are common | Always run alongside A or B |
| Rollback | Trivial | Config flag | N/A |
| Recommended order | Do FIRST if measurement shows <5% free-form | Do FIRST if measurement shows >5% | Verify after A or B |

---

## 6 — Pre-flight checks (mandatory before Phase 3.5 implementation)

1. **Re-read all four predecessor landings**: `phase_1_landing.md`, `phase_2_landing.md`, `phase_3_landing.md`, `phase_1_5_landing.md`. The stack composes; understanding all four is required.
2. **Re-verify Phase 3 citations against current source**: `cli.py:_run_patch_fixes` per-feature loop has drifted with Phase 1.5's wiring; the `if allowlist_paths:` gate is at a different line now.
3. **Run baseline test slice**:
   ```
   pytest tests/test_audit_fix_guardrails_phase{1,1_5,2,3}.py \
          tests/test_hook_multimatcher_conflict.py \
          tests/test_wave_d_path_guard.py
   ```
   Must be fully green (~52 tests).
4. **Measure free-form feature rate**: run a smoke of a representative PRD; grep the generated fix PRDs for empty `files_to_modify + files_to_create` features. Decide A vs B based on count.
5. **TDD discipline**: write the failing test fixtures FIRST. Confirm they fail with the expected `AssertionError` (not `ImportError` from a typo) BEFORE implementing.

---

## 7 — Suggested workflow (mirrors Phase 3 / 1.5)

1. Pick A or B (or both, in order). C is verification-only.
2. Create `tests/test_audit_fix_guardrails_phase3_5.py` with the failing fixtures.
3. Implement the chosen path.
4. Run the broader guardrails test slice + `m1_fast_forward` harness.
5. Direct-to-master, single commit `feat(audit-fix-guardrails): Phase 3.5 — <one-line summary>`.
6. Push immediately.
7. Write `phase_3_5_landing.md` capturing:
   * Path chosen (A / B / both).
   * Free-form feature rate measured.
   * Whether C verification passed (or if not, what's the next step).
   * New surfaces locked in tests.
   * Carry-overs (likely subset of these handoff items).

---

## 8 — Anti-patterns to avoid

(Per `feedback_structural_vs_containment.md` + `feedback_verification_before_completion.md`.)

* **Don't ship a kill-threshold or timeout** as a substitute for the scope binding. The point is structural prevention, not containment.
* **Don't assume the rate without measuring.** Picking A when free-form is common would tank coverage; picking B when it's rare adds maintenance burden for no gain.
* **Don't silently widen the allowlist.** A free-form feature's "fix" is to use `apps/web/**` as a default scope — that's just Wave D semantics on top of audit-fix, defeats the per-finding intent.
* **Don't let the PRD generator emit `files_to_modify=["*"]` or similar wildcard.** The exact-file allowlist semantic in Phase 3 is load-bearing — wildcards reintroduce the gap.
* **Don't change the fail-CLOSED semantic of `audit_fix_path_guard.py`.** It correctly denies on missing payload / empty allowlist; that's the asymmetric stance vs Wave D's fail-OPEN.

---

## 9 — Open questions to resolve in Phase 3.5

1. **What happens to a finding when its feature is skipped (Path A)?** Does it surface as `UNVERIFIED` in the next audit? Block the milestone? Plan to test.
2. **Should free-form skipped features count against `max_reaudit_cycles`?** The cycle still ran; only the dispatch was skipped. Probably yes; verify.
3. **Should `synthesise_primary_file` (Path B.1) prefer the most-recently-mentioned file in the evidence, the first one, or a most-frequent count?** First-mentioned matches the existing `_convert_findings` heuristic at `cli.py:7218`.
4. **Should Path C's verification be a smoke test or a unit test?** Smoke is more honest but slow; unit needs heavy mocking of the subprocess.
5. **Does the `_run_full_build` subprocess inherit `os.environ["AGENT_TEAM_FINDING_ID"]` from the parent's last iteration?** The Phase 3 wiring restores prior values via try/finally, so the answer should be NO — but worth a real check.

---

## 10 — File index

* **Plan**: `docs/plans/2026-04-26-audit-fix-guardrails-phase1-3.md` (sections D, E, F, H — anti-patterns).
* **Phase 1 landing**: `~/.claude/projects/.../memory/phase_1_landing.md`.
* **Phase 2 landing**: `~/.claude/projects/.../memory/phase_2_landing.md`.
* **Phase 3 landing**: `~/.claude/projects/.../memory/phase_3_landing.md`.
* **Phase 1.5 landing**: `~/.claude/projects/.../memory/phase_1_5_landing.md`.
* **Hook scripts**: `src/agent_team_v15/wave_d_path_guard.py`,
  `src/agent_team_v15/audit_fix_path_guard.py`.
* **Settings writer**: `src/agent_team_v15/agent_teams_backend.py`
  (`_ensure_wave_d_path_guard_settings`).
* **Wiring**: `src/agent_team_v15/cli.py:_run_audit_fix_unified` +
  `_run_patch_fixes` + `_run_audit_loop`.
* **Free-function**: `src/agent_team_v15/audit_models.py`
  (`derive_sibling_test_files`).

---

## 11 — Halting conditions

Per the original plan §0.6, STOP and surface to user if:

* A predecessor landing memory disagrees with the current source.
* The free-form feature rate measurement is impossible to obtain (e.g., the smoke environment is broken).
* Path B's synthesis heuristic returns a path that doesn't exist on disk and there's no clean fallback.
* The full-build subprocess verification (Path C) shows scope leak in either direction (parent → subprocess or subprocess → parent).
* The `m1_fast_forward` harness regresses on previously-clean gates.

NEVER paper over a halt. The audit-fix safety net's value is precisely that it doesn't compound silent failures.
