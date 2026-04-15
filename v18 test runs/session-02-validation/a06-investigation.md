# A-06 — RTL baseline investigation (logical CSS properties)

**Decision:** **Branch A — baseline correct, add lint rule.**

## Evidence

### globals.css (build-j)

`v18 test runs/build-j-closeout-sonnet-20260415/apps/web/src/styles/globals.css`
already uses CSS logical properties throughout:

- `html { min-block-size: 100%; }`
- `body { min-block-size: 100vh; }`
- `input, select, textarea { inline-size: 100%; }`
- `html[dir='rtl'] { text-align: start; }`

And declares `html[dir='rtl']` as the RTL toggle selector. This satisfies
M1 REQUIREMENTS.md ("`html[dir='rtl']` selector in `globals.css`").

### tailwind.config.ts (build-j)

Config uses `corePlugins: { preflight: true }` and relies on Tailwind v3.4's
default core plugins. Tailwind 3.4 ships logical-property utilities
(`ps-*`, `pe-*`, `ms-*`, `me-*`, `border-s-*`, `border-e-*`, etc.) as
first-class utilities — no `corePlugins` opt-in needed. The baseline is
therefore **functional**: the logical utilities are available by default
any time the scaffolded project uses Tailwind ^3.4.

### Actual F-027 cause

Audit F-027 flagged `apps/web/src/components/layout/app-shell.tsx:46`
using `px-*` (physical). This file is M3+ scope that A-09 (merged as PR #13,
commit f23ddad) now stops the builder from emitting during M1. Even if Wave
D did emit such a file, the underlying Tailwind baseline is fine — the
violation was a Wave D authoring mistake, not a scaffold defect.

## Fix (Branch A — scope-bounded to scaffold layer)

Scaffold now emits three deterministic files to enforce the baseline:

1. `apps/web/src/styles/globals.css` — logical-property baseline
   (`min-block-size`, `inline-size`, `text-align: start`) + `html[dir='rtl']`
   selector. Explicit comment directs authors to `ps-*`/`pe-*`.
2. `apps/web/tailwind.config.ts` — Tailwind v3.4 config with logical
   utilities available via the default `corePlugins`, design-token colors,
   font families. Comment references the lint rule.
3. `apps/web/eslint.config.js` — flat-config ESLint with a
   `no-restricted-syntax` rule that rejects JSX `className`/string literals
   containing physical spacing utilities (`px-`, `py-`, `mx-`, `my-`,
   `pl-`, `pr-`, `pt-`, `pb-`, `ml-`, `mr-`, `mt-`, `mb-`). The rule fires
   on any `Literal` or `TemplateElement` matching the regex, so both static
   strings and template interpolation are caught.

Tests assert the static contents of each emitted file — we do NOT run
ESLint in tests per the plan guardrails.

## Sequencing with A-09

A-09 stops Wave D from authoring M3+ files during M1. A-06 ensures that if
*any* milestone does emit CSS, the scaffold baseline enforces logical
properties via the lint rule. Complementary, not overlapping.
