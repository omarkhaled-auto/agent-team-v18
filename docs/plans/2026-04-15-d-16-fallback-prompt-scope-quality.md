# D-16 — Post-fallback Claude output doesn't compile

**Tracker ID:** D-16 (paired with A-10 and D-15)
**Source:** New — derived from A-10 investigation
**Session:** 7
**Size:** M (~150 LOC)
**Risk:** HIGH
**Status:** plan — depends on A-10 + D-15 findings

---

## 1. Problem statement

Build-j's Wave D Claude-fallback produced 47 files, but the output never stabilized after 3 compile-fix iterations. The routing (PR #10/#11) worked correctly — the fallback prompt itself or the compile-fix's ability to heal fallback output is the weak link.

## 2. Candidate root causes

Triangulate against A-10 investigation. Likely culprits:

1. **Fallback prompt inherits full-PRD scope.** If Wave D's fallback prompt is the same Wave D prompt that over-builds M2–M5 features (pre-A-09), claude-sonnet tries to produce M2–M5 feature pages from scratch in one turn. Predictable: doesn't compile.
2. **Fallback prompt missing monorepo context.** Fallback might not receive `tsconfig.json`, `package.json`, path aliases, so generated files reference imports that won't resolve.
3. **Fallback prompt is a raw retry, not a corrective prompt.** If fallback just re-sends the original Wave D prompt to Claude, Claude produces fresh code without knowing about partial files codex already wrote.

## 3. Proposed fix shape

### 3a. Fallback prompt uses milestone-scoped context

Depends on A-09. After A-09 lands, the fallback prompt inherits the milestone-scoped `ir`/`spec`, not the full PRD. Expected outcome: fallback for M1 produces only scaffold, which Claude can do cleanly in one turn.

### 3b. Fallback prompt includes on-disk state

Before invoking fallback, capture the current on-disk state:
- List of files codex did produce (partial work).
- Current `package.json` + `tsconfig.json`.
- Milestone scope.

Feed to fallback with framing: "The previous attempt produced these partial files. Complete the milestone given this state."

### 3c. Fallback output validation before entering compile-fix

Before handing fallback output to compile-fix loop:
- Verify minimum file set present (for frontend: `package.json`, `next.config.ts`, `tsconfig.json`, `tailwind.config.ts`, `app/layout.tsx`).
- If any missing, re-prompt fallback once with a targeted ask for those files.
- Only enter compile-fix loop when minimum scaffold exists.

## 4. Test plan

File: `tests/test_fallback_prompt.py`

1. **Fallback inherits milestone scope.** Mock M1 scoped `ir`; trigger fallback; assert fallback prompt doesn't mention M2–M5 entities.
2. **Fallback prompt includes on-disk partial state.** Pre-populate a temp dir with 3 codex-produced files; trigger fallback; assert prompt includes those paths.
3. **Fallback output validated before compile-fix.** Mock fallback returning output missing `next.config.ts`; assert a targeted re-prompt fires before compile-fix.

Target: 3 tests.

## 5. Rollback plan

Feature flags:
- `config.v18.fallback_scoped_prompt: bool = True`
- `config.v18.fallback_output_validation: bool = True`
Flip off to restore pre-fix behavior.

## 6. Success criteria

- Unit tests pass.
- Gate A smoke: if fallback fires during M1 (less likely post-A-09), compile-fix stabilizes on the fallback output.

## 7. Sequencing notes

- Bundle with A-10 and D-15 in Session 7.
- Depends on A-09 (scope filter) — without A-09, scoped-prompt change has no scope to inherit.
- Does not couple to Bug #20 directly, but Bug #20 reduces how often fallback fires, which makes D-16's importance smaller.
