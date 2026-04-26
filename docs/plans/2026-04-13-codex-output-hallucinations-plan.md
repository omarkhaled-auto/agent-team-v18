# Bug #11 — Codex Output Hallucinations Not Caught by Scanners

> **Status:** New — documented during 2026-04-13 smoke-test frontend review. Not yet fixed.
>
> **Severity:** MEDIUM — causes build-time or runtime failures in the generated application. The V18 audit team might catch some of these, but they should be caught deterministically, cheaply, post-Wave-D before the per-milestone audit runs.

## ⚠️ NOTE TO THE IMPLEMENTING AGENT

Investigate the full set of Codex hallucinations first. The two captured in this plan are *examples*, not the complete list. Additional hallucinations may exist in the 2026-04-13 clean-attempt-2 output that I didn't spot. A minimal fix that only catches *these two* is half a fix.

1. **Read the full `/c/smoke/clean/src/` tree** (preserved at `v18 test runs/build-c-hardened-clean/src/`) for additional hallucinations — invalid framework APIs, made-up types, nonexistent config keys. Document at least 5 distinct classes before designing the scanner.
2. **Check existing scanners** in `src/agent_team_v15/quality_checks.py` to understand the `Violation` shape and how the fix-loop consumes them. New scanners should follow the same pattern.
3. **Decide scan phase.** DTO scanners run post-Wave-B (backend focus). The proposed frontend-hallucination scanners should run post-Wave-D (before Wave D.5) so the fix loop can correct them before polish makes them harder to rip out.
4. **Decide LLM vs deterministic.** Some hallucinations are regex-catchable (`locale as 'en' | 'ar' | 'XX'` → is 'XX' in the PRD's locale list?). Others require library knowledge (is `Inter` a valid Google Font? does it have an `arabic` subset?). Start with the regex-catchable class — it's cheap and high-signal.

---

## Symptoms (observed)

### H1 — Invalid locale in frontend type assertion

In `src/app/layout.tsx`:
```typescript
dir={getDirection(locale as 'en' | 'ar' | 'id')}
```

PRD (`TASKFLOW_MINI_PRD.md` line ~11) says `Language support: English (LTR) + Arabic (RTL) — both must work from day one.` Only `en` and `ar`. The third locale `'id'` (Indonesian?) is a Codex hallucination — not in the PRD, not in the `messages/` dir, not in next-intl config.

Runtime impact: if the route accepts any locale value not in en/ar, the type assertion silently succeeds (TypeScript casts happily), then `getDirection('id')` probably returns `ltr` (default). Silent wrong-language fallback.

### H2 — Nonexistent Google Font subset

In `src/app/layout.tsx`:
```typescript
const inter = Inter({
  subsets: ['latin', 'arabic'],
  variable: '--font-inter',
});
```

Google Fonts' `Inter` family **does not have an `arabic` subset**. Available subsets: `latin`, `latin-ext`, `cyrillic`, `cyrillic-ext`, `greek`, `greek-ext`, `vietnamese`. The correct way to get Arabic support is to use a different font like `Noto_Sans_Arabic`, `Cairo`, or `IBM_Plex_Sans_Arabic` as a secondary family.

Runtime impact: Next.js will fail at build time (or runtime) when it tries to fetch the nonexistent subset. 500 error on first SSR render. Because Wave D.5 was polishing CSS while this line still existed, this bug never got caught by the build's compile check (TypeScript doesn't validate Google Fonts subset strings — they're just `string[]`).

## Why existing scanners don't catch this

- **DTO-PROP-001 / DTO-CASE-001** scan DTO files for decorator + casing. Scoped to backend.
- **WIRING-CLIENT-001** (per checklist, never verified this run) checks that frontend API calls match backend routes. Doesn't know about locale strings or font subsets.
- **CONTRACT-FIELD-001/002** (per checklist) compare frontend field names to OpenAPI schemas. Doesn't catch locale or font hallucinations.
- **i18n scanner** (Wave E, never ran) would catch missing translation keys but not a bogus locale in a type assertion.

Neither TypeScript's type checker nor ESLint would catch these — they're valid syntax at the type level, the values are just wrong at the semantic level.

## Scope

Add a new scanner class `run_frontend_contract_scan(project_root, pr_context)` that runs post-Wave-D and emits violations for:

1. Locale strings in type assertions that don't match the PRD's declared locale list (`LOCALE-HALLUCINATE-001`)
2. Google Fonts subset strings that the target font doesn't support (`FONT-SUBSET-001`)
3. (Follow-up, per investigation) other hallucination classes

Integrate with the existing fix-loop pattern (Wave D's compile_iterations). A violation feeds into a fix prompt for Codex (Wave D) or Claude (Wave D.5), which must rewrite the offending file.

## Proposed Implementation

### 1. `LOCALE-HALLUCINATE-001` scanner

Input: PRD-declared locales (parse from PRD or from `next.config.ts` / `i18n.ts` / `src/i18n/routing.ts`).

Regex to find type assertions like `locale as 'a' | 'b' | 'c'`:
```python
_RE_LOCALE_ASSERT = re.compile(
    r"\b\w+\s+as\s+(['\"][a-z]{2,3}['\"]\s*(?:\|\s*['\"][a-z]{2,3}['\"]\s*)*)",
    re.IGNORECASE,
)
```

For each match:
- Parse out the individual locale codes
- Compare against the PRD/declared list
- Any code in the assertion but NOT in the PRD list → `LOCALE-HALLUCINATE-001` (severity: MEDIUM)

```python
violations.append(Violation(
    check="LOCALE-HALLUCINATE-001",
    message=(
        f"Type assertion lists locale '{hallucinated}' which is not in the "
        f"project's declared locales ({', '.join(declared)}). Remove it from "
        f"the union type."
    ),
    file_path=rel_path,
    line=line,
    severity="error",
))
```

### 2. `FONT-SUBSET-001` scanner

Input: Google Fonts subset matrix (hardcoded small table; ~30 common fonts × their subset lists, extensible).

Regex to find `next/font/google` imports and their subset args:
```python
_RE_GOOGLE_FONT_IMPORT = re.compile(
    r"import\s*\{\s*(\w+)\s*\}\s*from\s*['\"]next/font/google['\"]",
)
_RE_GOOGLE_FONT_CALL = re.compile(
    r"(\w+)\(\s*\{[^}]*subsets:\s*\[([^\]]+)\]",
    re.DOTALL,
)
```

Cross-reference the font name (match group 1) against the subset matrix. Any subset not in the matrix for that font → `FONT-SUBSET-001` (severity: error — this is a build-time failure).

```python
_GOOGLE_FONT_SUBSETS = {
    "Inter": {"latin", "latin-ext", "cyrillic", "cyrillic-ext", "greek", "greek-ext", "vietnamese"},
    "Noto_Sans_Arabic": {"arabic"},
    "Cairo": {"arabic", "latin", "latin-ext"},
    "IBM_Plex_Sans_Arabic": {"arabic"},
    "Roboto": {"latin", "latin-ext", "cyrillic", "cyrillic-ext", "greek", "greek-ext", "vietnamese"},
    # ... extend as needed
}
```

For unknown fonts: emit a LOW-severity warning (can't validate), not a blocking error.

### 3. Hook into Wave D fix loop

Same pattern as `run_dto_contract_scan`. Post-Wave-D, before Wave D.5 starts, run the frontend scanner. If violations found, feed them to a fix prompt and re-compile.

## Investigation Checklist (before writing code)

- [ ] Read `/c/smoke/clean/src/` (preserved copy) for additional hallucination classes
- [ ] Read existing `quality_checks.run_dto_contract_scan` to understand the integration pattern
- [ ] Confirm where post-Wave-D scanners should hook in (probably in `wave_executor.py` after Wave D telemetry writes, before Wave D.5 launches)
- [ ] Verify the PRD-declared locale list is machine-extractable — if not, extend `product_ir.py` to parse it
- [ ] Survey `next/font/google` usage in the generated code to confirm the regex catches real patterns

## Acceptance Criteria

- [ ] `LOCALE-HALLUCINATE-001` scanner detects `locale as 'en' | 'ar' | 'id'` when PRD says en+ar only
- [ ] `FONT-SUBSET-001` scanner detects `Inter({ subsets: ['arabic'] })` and flags as error
- [ ] Both scanners integrate with Wave D's fix-loop pattern (violations feed into fix prompts)
- [ ] At least 3 additional hallucination classes discovered during investigation and added as `-002`, `-003`, etc.
- [ ] Test: scanner correctly identifies the two known hallucinations in `/c/smoke/clean/src/app/layout.tsx`
- [ ] Test: scanner produces zero false positives on a known-good Next.js + next-intl project
- [ ] Test: `_GOOGLE_FONT_SUBSETS` matrix is straightforward to extend (add one entry, run scanner)
- [ ] No regression — existing DTO scanners continue to pass

## Risk Notes

- **Google Fonts subset matrix maintenance.** Font families add/remove subsets over time. The matrix will drift. Acceptable: treat "unknown font name" as warning-only, not error. Users can extend the matrix; missing entries fail safe.
- **False positives on legitimate unusual fonts.** Self-hosted fonts via `next/font/local` don't hit the Google scanner. Make sure the `FONT-SUBSET-001` scanner only fires on `next/font/google` imports, not `next/font/local`.
- **Locale scanner may need PRD-extraction fallback.** If the PRD doesn't explicitly list locales (some PRDs just say "i18n"), skip the scan with an INFO-level log rather than failing. Only flag `LOCALE-HALLUCINATE-001` when the declared list is unambiguous.
- **Scope creep risk.** "Catch all LLM hallucinations" is a forever project. This plan's scope is: known-real hallucinations from one empirical run, plus a pattern for extending. Don't try to solve hallucination-detection generally.

## Done When

- Re-running 2026-04-13 smoke test on a Prisma-PRD (after Bug #9 is fixed) catches both H1 and H2 automatically in Wave D's fix loop — they get rewritten to correct values before Wave D.5 begins
- Hallucination telemetry is visible in per-wave JSON: `frontend_hallucinations_detected: [...]`
- The `FINAL_COMPARISON_REPORT.md` for the next smoke test shows zero manual review findings in the "Codex output drift" section (because the scanner caught them)
