# A-10 — Wave D compile-fix budget exhausts at 3 attempts

**Tracker ID:** A-10 (paired with D-15 and D-16)
**Source:** §4.2 "Compile failed after 3 attempt(s)"; §10 item 2
**Session:** 7 (INVESTIGATION FIRST)
**Size:** M (~120 LOC once direction is chosen)
**Risk:** HIGH (recovery hot-path; budget changes affect cost)
**Status:** plan — investigation required before committing to fix shape

---

## 1. Problem statement

Build-j Wave D workflow:
1. Codex wedged on orphan `command_execution` tool.
2. PR #11 fail-fast fired at 627s idle.
3. PR #10 routed retry to Claude fallback.
4. Claude fallback produced 47 files.
5. Compile-fix loop ran 3 iterations.
6. `compile_passed: false`, error = `Compile failed after 3 attempt(s)`.
7. Wave D marked `success: false`, M1 marked FAILED.

The **routing fixes worked**. The **compile-fix recovery did not**.

**Evidence:**
- `milestone-1-wave-D.json`: `fallback_used: true`, `retry_count: 1`, `compile_iterations: 3`, `compile_passed: false`.
- `wave_executor.py:2779/3195` emit the 3-attempt failure message.

## 2. Investigation (DO THIS FIRST)

Open in sequence:
1. `v18 test runs/build-j-closeout-sonnet-20260415/apps/web/` — read the 47 files Claude fallback produced. Look for:
   - Are they coherent (real Next.js scaffold) or malformed?
   - Do they reference packages that weren't installed?
   - Do they have tsconfig / path alias issues?
2. `src/agent_team_v15/compile_profiles.py` — read the compile-fix loop. Record:
   - What's the iteration cap? (Expected: 3.)
   - What context does iteration N see? Does it see iteration N-1's errors + diffs, or just the current state?
   - Does the loop invoke a fresh model per iteration or accumulate context?
3. `src/agent_team_v15/wave_executor.py` around lines 2779 and 3195 — the compile-fix caller sites. Record:
   - Is the cap configurable (config.v18.compile_fix_max_attempts or similar)?
   - Is the cap different on fallback path vs normal path?
4. `BUILD_LOG.txt` from build-j — search for `[compile-fix]` or equivalent log markers to see what each iteration actually did.

Document findings in this plan under §3 before writing fix code.

## 3. Candidate root causes + corresponding fix shapes

### Candidate 1: Budget too low on fallback path

If iteration 3 was making progress but needed more iterations: simple budget bump for fallback-mode only.

```python
compile_fix_max_attempts = 5 if fallback_used else 3
```

**Evidence pattern:** Each iteration's error count decreases but doesn't hit zero.

### Candidate 2: Context bleed

If iteration N doesn't see iteration N-1's fixes (each iteration treated as fresh): fix is to accumulate diff history into the compile-fix context.

**Evidence pattern:** Same error flagged in every iteration even after a "fix" was attempted.

### Candidate 3: Structural misfit

If Claude-fallback produced code depends on packages not in package.json (e.g., uses `react-hook-form` without installing it), compile-fix can't resolve by editing .tsx files — it needs to modify package.json + run `npm install`.

**Evidence pattern:** Errors are `Cannot find module 'X'` for packages not in deps.

### Candidate 4: Wrong compiler/incomplete scaffold

If Next.js is missing a required config (e.g., `next.config.ts` missing from what fallback produced): compile fails in a way that per-file diffs can't recover from.

**Evidence pattern:** Errors are infrastructure/config-layer, not source-file-layer.

## 4. Fix shape (CHOOSE AFTER INVESTIGATION)

### If Candidate 1 (budget): one-line change

- Add `config.v18.compile_fix_max_attempts_fallback: int = 5`.
- `wave_executor.py` reads and applies the fallback-specific cap when `fallback_used=True`.

### If Candidate 2 (context bleed): compile-fix loop refactor

- Extend `compile_profiles.py` to persist iteration history (error list + diff applied) and include it in iteration N's context.

### If Candidate 3 (structural): add a triage pass

- Before iteration 1, run a "structural review" that inspects `package.json`, `tsconfig.json`, missing deps. If structural issues found, address them first (add deps, run `npm install`), THEN enter the per-file diff loop.
- This aligns with D-15.

### If Candidate 4 (missing infra): validate fallback output completeness

- After Claude fallback returns, verify a minimum set of config files exist (`next.config.ts`, `tailwind.config.ts`, `tsconfig.json`, `package.json`). If any are missing, ask the model for them BEFORE entering compile-fix.

## 5. Test plan

File: `tests/test_compile_fix_recovery.py`

Tests depend on chosen candidate, but all paths should include:

1. **Budget fork by fallback.** Mock a wave with `fallback_used=True`; assert compile-fix loop uses the fallback cap.
2. **Structural triage catches missing deps.** Feed a compile state where `react-hook-form` is imported but not in package.json; assert triage pass surfaces this and adds the dep.
3. **Compile failure report is structured.** When the loop exhausts, assert the wave's `error` field contains a structured report: `{iterations, error_count_per_iter, final_error_categories}` — not a cryptic "Compile failed after N attempt(s)".

Target: 3–5 tests.

## 6. Rollback plan

All changes behind config flags:
- `config.v18.compile_fix_max_attempts_fallback`: revert to 3 if runs get expensive.
- `config.v18.compile_fix_structural_triage: bool = True`: flip off if triage adds overhead without value.

## 7. Success criteria

- Chosen investigation candidate is documented with evidence from build-j files.
- Fix PR includes the investigation findings in the commit message.
- Unit tests for the chosen candidate pass.
- No paid smoke required for Gate A; end-to-end proof is Gate D (full smoke).

## 8. Sequencing notes

- Couple with D-15 (same compile-fix loop) and D-16 (fallback prompt quality) in Session 7.
- Land AFTER A-09 (Session 1) because A-09 reduces the scope Claude fallback must produce, which may eliminate Candidate 3 + 4 entirely.
- Do not couple to Bug #20 — compile-fix is post-codex-failure, orthogonal to transport.
