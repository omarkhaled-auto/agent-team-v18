# A-06 — RTL baseline: physical CSS properties instead of logical

**Tracker ID:** A-06
**Source:** F-027 (MEDIUM) + §8 gate finding "off-grid spacing values"
**Session:** 2 (scaffold cluster)
**Size:** M (~60 LOC)
**Risk:** LOW
**Status:** plan (INVESTIGATE first)

---

## 1. Problem statement

M1 REQUIREMENTS.md states: "All CSS spacing/layout must use CSS logical properties from the start — this is enforced at the globals.css level."

Build-j audit F-027 flagged `apps/web/src/components/layout/app-shell.tsx:46` using `px-*`/`py-*` (physical). The flagged file (`app-shell.tsx`) is M3+ scope that A-09 will stop producing during M1 — but the underlying question is: does the M1 scaffold's `globals.css` + `tailwind.config.ts` actually enforce logical properties, or does it just document them?

## 2. Investigation needed

Before writing code:
1. Read the scaffolded `globals.css` from build-j at `v18 test runs/build-j-closeout-sonnet-20260415/apps/web/src/styles/globals.css`.
2. Read `tailwind.config.ts` from same run.
3. Determine whether logical-property utilities (`ps-*`, `pe-*`, `ms-*`, `me-*`) are enabled via Tailwind's `corePlugins` or a custom preset.
4. Decide if the baseline is correct (only M3+ wave output was wrong) or also broken.

Expected investigation time: 20 minutes.

## 3. Proposed fix shape (two branches)

### Branch A — Baseline is correct, M3+ output is wrong

If `globals.css` + `tailwind.config.ts` correctly enable logical utilities, the A-06 fix becomes:
- Add an ESLint rule or Tailwind plugin that disallows `px-*` and `py-*` and errors on them.
- Document in `globals.css` template: "RTL enforcement — use `ps-*`/`pe-*` instead of `px-*`."

The actual F-027 violation is resolved by A-09 (which stops Wave D from producing `app-shell.tsx` during M1 at all).

### Branch B — Baseline itself needs work

If Tailwind config doesn't enable logical utilities:
- Update `_scaffold_nextjs_pages` (scaffold_runner.py) template for `tailwind.config.ts` to enable `corePlugins` for logical-property utilities.
- Update `globals.css` template to set `html { direction: var(--dir); }` + `:root[dir="rtl"] { ... }` scaffolding.
- Keep the lint rule from Branch A.

## 4. Test plan

File: `tests/test_rtl_scaffold.py`

1. **Scaffolded tailwind config enables logical-property utilities.** Run scaffold; read `apps/web/tailwind.config.ts`; assert it includes logical utility configuration.
2. **Scaffolded globals.css has RTL baseline.** Assert `html[dir="rtl"]` selector exists.
3. **Lint rule catches `px-*` usage.** Add a synthetic file using `px-4`; run ESLint (or equivalent); assert error.

Target: 3 tests.

## 5. Rollback plan

The Tailwind config change is a single-file edit. If it breaks builds, revert that file; lint rule is off-by-default behind a config flag.

## 6. Success criteria

- Unit tests pass.
- Static check: scaffold a fresh M1 tree, grep for `px-*|py-*` in committed `.tsx`/`.css` — zero matches.
- After A-09 + A-06 land, re-run the audit against a stock smoke and F-027-class findings should be absent.

## 7. Sequencing notes

- Land in Session 2 alongside other scaffold template fixes (A-01..A-08).
- Complements A-09: A-09 stops Wave D from emitting out-of-scope components; A-06 ensures that IF something emits CSS, the enforcement is in place.
