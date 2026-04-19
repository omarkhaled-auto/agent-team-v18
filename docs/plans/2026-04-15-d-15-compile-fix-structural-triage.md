# D-15 — Compile-fix loop lacks structural triage

**Tracker ID:** D-15 (paired with A-10 and D-16)
**Source:** New — derived from A-10 investigation
**Session:** 7
**Size:** M (~100 LOC)
**Risk:** HIGH (recovery hot-path)
**Status:** plan — depends on A-10 investigation findings

---

## 1. Problem statement

Build-j's compile-fix loop on Wave D's Claude-fallback output exhausted 3 iterations without stabilizing. The loop as currently designed iterates per-file diffs, which can't resolve errors whose root cause is structural (missing devDep, wrong tsconfig paths, missing `next.config.ts`).

## 2. Proposed fix shape (pending A-10 investigation)

### 2a. Pre-loop structural triage pass

Before entering the per-file diff loop, run a single "structural review":
1. Inspect `package.json` — are all imports in the codebase represented in deps?
2. Inspect `tsconfig.json` — are paths + module resolution consistent?
3. Inspect top-level config files (`next.config.ts`, `tailwind.config.ts`, `vitest.config.ts`) — are they present and non-empty?
4. If any structural issue found: surface a "structural fix required" action (add dep, install, regenerate config) BEFORE the diff loop starts.

### 2b. Iteration context accumulator

Extend `compile_profiles.py`'s loop so iteration N sees:
- The list of errors from iteration N-1.
- The diff that was applied at iteration N-1.
- A "what changed" marker for whether errors decreased / plateaued / increased.

If the iteration counter shows a plateau (same error count two iterations in a row), break early and return a structured report rather than burning more budget.

### 2c. Structured compile-failure report

When the loop exhausts: return a `CompileFailureReport` struct:
```python
@dataclass
class CompileFailureReport:
    iterations: int
    error_count_per_iter: list[int]
    final_error_categories: dict[str, int]  # {"missing_module": 3, "type_error": 12, ...}
    probable_root_cause: str  # heuristic guess based on categories
```

Surface this in `wave_result.error` so operators don't see "Compile failed after 3 attempt(s)" with no further info.

## 3. Test plan

File: `tests/test_compile_structural_triage.py`

1. **Missing devDep triggers triage.** Feed a codebase importing `react-hook-form` without it in package.json; assert triage catches this before diff loop.
2. **Missing tsconfig paths triggers triage.** Feed a codebase referencing `@/components/*` without tsconfig paths entry; assert triage catches.
3. **Plateau detection breaks early.** Feed iteration 1 + 2 with same error count; assert loop exits at iter 2 with plateau marker.
4. **Structured report on exhaustion.** Force 3+ iterations; assert `CompileFailureReport` struct returned with categorized errors.

Target: 4 tests.

## 4. Rollback plan

Feature flag `config.v18.compile_fix_structural_triage: bool = True`. Flip off to restore pre-fix behavior.

## 5. Success criteria

- Unit tests pass.
- Gate A smoke (if it happens to trigger a compile-fix loop): the loop either stabilizes or returns a structured report, not a cryptic message.

## 6. Sequencing notes

- Bundle with A-10 and D-16 in Session 7. All three share the compile-fix / fallback recovery layer.
- A-10 investigation drives the specific implementation shape here.
- Do not couple to Bug #20.
