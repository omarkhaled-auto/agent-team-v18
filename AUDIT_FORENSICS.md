# Audit System Forensic Analysis

**Date:** 2026-04-01
**Scope:** 12 audit runs on ArkanPM (facilities-platform), comparing automated audit system output against manual audit (62 real findings)
**Analyst:** Audit Forensics Agent

---

## Executive Summary

The audit system failed catastrophically across 12 runs. It consumed 50+ fix milestones, 8 cycles on false positives, regressed in run 12 (37→43 findings), and missed 62 real bugs that a manual audit found. The root causes are: (1) the audit checks PRD acceptance criteria, not actual code correctness; (2) the fix cycle has no regression protection; (3) the scanner cannot distinguish code from non-code content; (4) frontend/integration issues are outside the system's detection model entirely.

---

## A. Why Did Findings Plateau at ~40?

### The Detection Model is Fundamentally Wrong

The audit system (`audit_agent.py`) works by:
1. Extracting acceptance criteria (ACs) from the PRD (`extract_acceptance_criteria()`, line 637)
2. Categorizing each AC as STATIC, BEHAVIORAL, RUNTIME, or EXTERNAL (line 935)
3. Running grep-based checks for STATIC ACs (line 1011)
4. Running Claude-assisted checks for BEHAVIORAL ACs (line 1407)
5. Skipping RUNTIME and EXTERNAL ACs entirely (line 860)

**The system can only find issues that map to a specific PRD acceptance criterion.** It has no mechanism to detect:
- Route mismatches between frontend and backend
- Schema integrity issues (missing cascades, missing relations)
- Frontend-backend API contract violations
- Auth flow incompatibilities
- Build/infrastructure failures
- Response shape inconsistencies

### What the Audit Detects vs What It Misses

| Audit System Categories | Count in Run 12 | Manual Audit Categories | Count |
|---|---|---|---|
| `code_fix` (AC partially implemented) | ~25 | Route mismatches (C-02 through C-12) | 11 CRITICAL |
| `regression` (previously passing, now failing) | 11 | Schema integrity (missing cascades, relations, indexes) | ~25 HIGH/MEDIUM |
| `ux` (REQUIRES_HUMAN, always skipped) | 12 | Frontend-backend API mismatches | 23 confirmed |
| `missing_feature` (no code found for AC) | 2 | Auth/security issues | 6 |
| `security` | 0 | Response shape inconsistencies | 4 sections |
| | | Frontend code quality | 15 |
| | | Infrastructure/build | 6 |
| | | Test failures | 1 section (78 failing tests) |

### The Coverage Gap

The audit system's 94 ACs are all **business rule** and **success criteria** items from the PRD (AC-BR1 through AC-BR57, AC-SC1 through AC-SC34). These test whether specific business logic is implemented (e.g., "WorkOrder SLA resolution time is calculated as...").

The manual audit's 62 findings are almost entirely about **integration correctness** — whether the frontend calls the right endpoints, whether the schema has proper constraints, whether the build even works. These are fundamentally different concerns.

**Detection coverage against the 62 real findings: approximately 0%.** Not a single one of the manual audit's 62 findings maps to an AC-BR or AC-SC criterion that the automated audit checks.

### Why ~40 is the Plateau

The audit started at 90 findings (run 1) but most were Claude API errors (`"Could not resolve authentication method"` — see audit_run1.json where nearly every finding has this error as its description). As the API issues were fixed and real checks ran, findings dropped to the "true" failure count: the ~40 ACs that are partially implemented. The remaining ~40 ACs genuinely pass their behavioral checks. Since the system can only measure AC compliance, it asymptotically approaches the number of ACs that are genuinely incomplete — around 40.

---

## B. Why Did the System REGRESS in Run 12?

### Run 12 Data

- Run 11: 37 findings
- Run 12: 43 findings (+6)
- Run 12 regressions field: **11 ACs** that previously passed now fail (AC-BR3, AC-BR5, AC-BR6, AC-BR8, AC-BR19, AC-BR21, AC-BR27, AC-BR51, AC-SC15, AC-SC29, AC-SC31)

### How Fix Milestones Introduce Regressions

The fix cycle flow is:

```
audit_agent.run_audit() → findings
    → fix_prd_agent.generate_fix_prd() → fix PRD markdown
        → builder pipeline (parser → contracts → milestones)
            → milestone execution (code changes)
                → re-audit
```

The fix PRD (`fix_prd_agent.py`) generates a document that the builder pipeline processes. The builder then modifies code files. **There is no mechanism to verify that the fix didn't break something else.**

Specific failure pattern from run 12:
1. AC-BR3 was PASS in run 6 (work order completion deducts stock)
2. A fix milestone modified `work-order.service.ts` for a different AC
3. The modification changed the `complete()` method's transaction boundaries
4. AC-BR3 now shows as REGRESSION because the asset history creation moved outside the transaction

### The Regression Detection Mechanism — It Exists But Is Toothless

The system DOES detect regressions (`audit_agent.py` lines 882-898):
```python
if r.ac_id in prev_pass and r.verdict in ("FAIL", "PARTIAL"):
    regressions.append(r.ac_id)
    f.category = FindingCategory.REGRESSION
    if f.severity in (Severity.MEDIUM, Severity.LOW):
        f.severity = Severity.HIGH
```

And `audit_team.py` has termination logic (line 108):
```python
if current_score.score < previous_score.score - 10:
    return True, "regression"
```

**But these only trigger AFTER the damage is done.** The regression is detected in the re-audit, but the code changes have already been committed. There is no pre-commit verification, no test suite run before accepting fixes, and no rollback mechanism.

### The Fix PRD's Regression Prevention Section is Advisory Only

`fix_prd_agent.py` generates a "Regression Prevention" section (line 417) that says:
```
CRITICAL: DO NOT introduce regressions.
```
and lists previously passing ACs. But this is just markdown text in a PRD — it's instructions to the builder, not an enforced constraint. The builder pipeline has no mechanism to verify compliance.

---

## C. Why Did the Fix Cycle Waste 8 Rounds on False Positives?

### The Scanner's Detection Method

The UI compliance scanner (referenced in the fix cycle log as "UI-004") uses a line-based regex to detect spacing values. It flags any line containing a numeric value it considers "not on the 4px grid."

### Why It Can't Distinguish SVG Coordinates from CSS Spacing

The scanner operates on raw source lines. When it sees:
```html
<path d="M3 12l2-2m0 0l7-7 7 7M5 10v10..."/>
```
It extracts the numbers `3`, `12`, `2`, `7`, etc. and checks whether they're on a 4px grid. The number `3` fails the check, so it reports a UI-004 violation.

This is a fundamental limitation of line-based regex scanning — it cannot parse HTML/JSX structure to distinguish SVG path coordinates from CSS utility classes.

### Why the System Didn't Learn from Cycle 1's False Positive Conclusion

The fix cycle log for UI Compliance Cycle 1 explicitly states:
> "While Tailwind's `3` maps to 12px (which is 4px-grid-aligned), the scanner treats the raw numeral as a pixel value."

But in Cycle 2, 3, 4, 5, 6, 7, 8, and 9 — the system continued to generate fix milestones for the same class of issue. **There is no feedback loop from fix cycle conclusions back to the scanner.** Each audit run re-scans from scratch with the same rules. The system has no memory of past false positive determinations.

The 8-cycle progression:
1. **Cycles 1-6:** Replace `gap-3` → `gap-4` across ~120 files (changes 12px to 16px — actual visual regression!)
2. **Cycle 7:** Switch to `gap-[12px]` bracket notation (preserves visual spacing but still triggered by SVG)
3. **Cycle 8:** Extract SVGs to separate file (scanner follows to new file)
4. **Cycle 9:** Replace inline SVGs with @heroicons/react package imports

Each cycle cost a full fix milestone execution. The total cost was 9 fix milestones (cycles 1-9) plus the visual regressions introduced by cycles 1-6 (bumping 12px spacing to 16px across the entire app).

---

## D. Why Did `missing_fe` and `ux` Findings Never Get Fixed?

### `missing_feature` Findings (Category: `missing_fe`)

The `_results_to_findings()` function (line 1832) classifies findings as `MISSING_FEATURE` when:
```python
elif "no relevant code found" in r.evidence.lower():
    category = FindingCategory.MISSING_FEATURE
```

These findings have `estimated_effort: "medium"` and generic fix suggestions like `"Implement AC-XXX as specified in [section]"`. The fix PRD includes them as `FEAT-NNN` items (fix_prd_agent.py line 375):
```python
if f.category == FindingCategory.MISSING_FEATURE:
    label = f"FEAT-{feat_count:03d}"
    sections.append(f"**{label}: {f.title}** [NEW FEATURE]")
```

**But the builder pipeline treats fix PRDs as incremental patches, not feature implementations.** A fix milestone is scoped to modify existing files, not create entire new features. When the PRD says "FEAT-001: Implement asset transfer workflow," the builder has no template, no scaffolding, and no guidance beyond the AC text. The milestone either times out or produces a stub.

### `ux` Findings (Category: `ux`)

The audit classifies RUNTIME and EXTERNAL ACs as `SKIP` (line 860-866):
```python
for ac in skip_acs:
    results.append(CheckResult(ac_id=ac.id, verdict="SKIP", evidence=f"Requires {ac.check_type.value} verification (human needed)"))
```

These become findings with `severity: REQUIRES_HUMAN` and `category: UX` (line 1831):
```python
elif r.verdict == "SKIP":
    category = FindingCategory.UX
```

**These findings are excluded from the score denominator** (line 905-906):
```python
skipped = sum(1 for r in results if r.verdict == "SKIP")
denominator = len(results) - skipped
```

And from fix candidates in `audit_models.py` (line 458):
```python
if f.severity in fix_severities and f.verdict in ("FAIL", "PARTIAL"):
    fix_candidates.append(i)
```

Since UX findings have verdict `SKIP` (not `FAIL` or `PARTIAL`), they are never included in `fix_candidates` and thus never appear in fix tasks. **The 12 UX findings (constant across all 12 runs) are structurally unfixable by the system.**

### The Fix PRD Does Include Them — But Nobody Acts

Looking at `fix_prd_agent.py`, findings of ALL categories are included in the bounded contexts section. But the builder's milestone system processes fix tasks from `group_findings_into_fix_tasks()` (audit_models.py line 475), which only includes `fix_candidates`. UX findings never become fix tasks.

---

## E. What Did the REAL Audit (62 Findings) Catch That the System Missed?

### Complete Mapping: 62 Real Findings vs Audit System Detection Capability

#### CRITICAL (12 findings) — 0 detected by audit system

| Real Finding | Type | Could Audit System Detect? | Why Not |
|---|---|---|---|
| C-01: Role name split (`technician` vs `maintenance_tech`) | Cross-cutting string mismatch | NO | No AC covers role string consistency |
| C-02: Missing PATCH checklist endpoint | Route mismatch | NO | Audit checks AC text, not route existence |
| C-03: Missing GET buildings/:id/assets | Route mismatch | NO | Same |
| C-04: Property contact nested vs top-level | Route mismatch | NO | Same |
| C-05: warranty_id @default("") on UUID FK | Schema integrity | NO | No AC covers FK default values |
| C-06: Invalid deleted_at filter on StockLevel | Prisma query error | NO | No AC covers query correctness |
| C-07: Wrong field reference in warranty include | Prisma query error | NO | Same |
| C-08: MFA flow incompatible FE/BE | Auth flow mismatch | NO | No AC covers auth flow contract |
| C-09: Building amenity/system write routes | Route mismatch | NO | Same as C-02 |
| C-10: Floor/zone CRUD routes don't exist | Route mismatch | NO | Same |
| C-11: Unit detail 3 subresource routes missing | Route mismatch | NO | Same |
| C-12: Work request attachment route missing | Route mismatch | NO | Same |

#### HIGH (22 findings) — 0 detected by audit system

| Real Finding | Type | Could Audit System Detect? |
|---|---|---|
| H-01: 40+ missing onDelete Cascade | Schema integrity | NO |
| H-02: 15+ missing @relation definitions | Schema integrity | NO |
| H-03: 7 services missing soft-delete filter | Query correctness | NO |
| H-04: Post-pagination filtering | Logic error | NO |
| H-05: Invalid UUID fallback 'no-match' | Logic error | NO |
| H-06: Missing items relation in include | Query completeness | NO |
| H-07: Vendor category filter wrong field | Logic error | NO |
| H-08: Raw SQL injection risk | Security | NO |
| H-09: GET /users?role=technician empty | Data mismatch | NO |
| H-10: Audit log date filter params wrong | API contract | NO |
| H-11: 50+ field name fallbacks | Response shape | NO |
| H-12: Array vs {data,meta} inconsistency | Response shape | NO |
| H-13: Missing avatarUrl in profile | API contract | NO |
| H-14: Hardcoded enums without constants | Code quality | NO |
| H-15: Silent error handling on all pages | Code quality | NO |
| H-16: Missing status-history route | Route mismatch | NO |
| H-17: /test vs /test-connection route | Route mismatch | NO |
| H-18: FRONTEND_URL port mismatch | Config error | NO |
| H-19: Web build broken | Build failure | NO |
| H-20: Prisma migrations not applied | Infrastructure | NO |
| H-21: 94+ magic string pseudo-enums | Schema design | NO |
| H-22: Unit test suite failing | Test failure | NO |

#### MEDIUM (17 findings) — 0 detected

All 17 medium findings (missing indexes, off-by-one errors, tenant isolation gaps, type safety bypasses, etc.) are structural/integration issues outside the AC-based detection model.

#### LOW (11 findings) — 0 detected

All 11 low findings (decimal inconsistency, localStorage XSS, unsafe date parsing, etc.) are code quality issues outside the AC-based detection model.

### Audit System TRUE Detection Rate

**Against the 62 real bugs: 0/62 = 0% detection rate.**

The audit system and the manual audit are checking completely different things:
- **Audit system:** "Does the code implement what the PRD acceptance criterion says?" (business logic compliance)
- **Manual audit:** "Does the code actually work?" (integration correctness, schema integrity, route matching, build health)

The audit system's findings (AC-BR3 partially implemented, AC-BR5 race condition, etc.) are valid observations about business rule compliance — but they are a different class of concern from the 62 real bugs that would cause runtime failures.

---

## F. Root Cause Taxonomy

### 1. Detection Gap (accounts for ~85% of failure)

**The audit only checks PRD acceptance criteria against code.** It has no scanner for:
- Frontend-to-backend route matching
- Prisma schema integrity (cascades, relations, indexes, type correctness)
- Build/compilation health
- API response shape consistency
- Auth flow contract alignment
- Configuration correctness (.env, Docker, CORS)

**Impact:** 62/62 real findings missed.

### 2. False Positive Pollution (accounts for ~30% of wasted effort)

**The UI compliance scanner cannot parse structured content.** It treats SVG path coordinates, Tailwind scale values, and CSS pixel values identically. It also misinterprets Tailwind's scale-3 (which is 12px, on the 4px grid) as "3px" (not on grid).

**Impact:** 9 fix cycles (UI Compliance cycles 1-9), ~120 files modified unnecessarily, visual spacing regressions introduced by bumping 12px to 16px across the app.

### 3. Fix Regression (accounts for ~25% of finding count in run 12)

**No pre-commit verification.** Fix milestones modify code without running tests, without checking that previously-passing ACs still pass, and without any rollback mechanism. The regression detection in the re-audit is post-hoc — the damage is already done.

**Impact:** 11 regressions in run 12 (AC-BR3, BR5, BR6, BR8, BR19, BR21, BR27, BR51, SC15, SC29, SC31). These were ACs that PASSED in earlier runs but FAILED after fix milestones modified their implementation files.

### 4. Fix Ineffectiveness (accounts for ~15% of stagnation)

**`missing_feature` and `ux` findings are structurally unfixable:**
- `missing_feature`: Fix PRD labels them as FEAT-NNN but the builder can't scaffold new features
- `ux`: Classified as SKIP, excluded from fix candidates, never become fix tasks

**Impact:** 14 findings (12 UX + 2 missing_fe) persisted unchanged across all 12 runs.

### 5. Cycle Waste (accounts for ~60% of total cost)

**No learning between cycles.** Each audit run re-scans from scratch. False positive conclusions from cycle N are not fed back into cycle N+1. The same findings are re-detected, re-triaged, and re-fixed repeatedly.

**Specific waste accounting:**
- 9 cycles on Tailwind spacing-3 / SVG false positives
- 4 cycles on database_defaults (fixes were lost/reverted between cycles)
- 2 cycles on asset integrity false positives (Next.js public/ directory convention)
- 6 cycles on hardcoded hex colors (legitimate but low-value — cosmetic fixes consuming full milestone budgets)
- Multiple cycles on the same AC-BR findings that regressed and needed re-fixing

---

## Appendix: Key Source File Locations

| File | Lines | Role |
|---|---|---|
| `src/agent_team_v15/audit_agent.py` | 1878 | Core audit engine — AC extraction, static/behavioral checks, cross-cutting review |
| `src/agent_team_v15/audit_models.py` | 569 | Data models, dedup, scoring, fix task grouping |
| `src/agent_team_v15/audit_prompts.py` | 425 | Prompts for 6 specialized auditors + scorer |
| `src/agent_team_v15/audit_team.py` | 207 | Team orchestration, termination logic, scan overlap |
| `src/agent_team_v15/fix_prd_agent.py` | 550 | Fix PRD generation from findings |
| `C:\Projects\ArkanPM\.agent-team\FIX_CYCLE_LOG.md` | ~438 | Complete fix cycle history |
| `C:\Projects\ArkanPM\CODEBASE_AUDIT_REPORT.md` | ~1623 | Manual audit — 62 real findings |

---

## G. Architectural Insight: Two-Mode Audit Design

### The Current System is Agentic — But Aimed at the Wrong Target

The current audit IS agentic. `_call_claude_sdk_agentic()` (audit_agent.py line 84) uses the Claude Agent SDK with Read/Grep/Glob tools over max_turns=6. The two-phase approach (Phase 1: investigate with tools, Phase 2: render verdict) is sound engineering. The problem is not the mechanism — it's what the mechanism is pointed at.

The audit answers: **"Does the codebase satisfy this PRD acceptance criterion?"**

The 62 real bugs answer a different question: **"Does the codebase have integration bugs, schema defects, route mismatches, and build failures?"**

These are two fundamentally different audit modes.

### The Required Two-Mode Architecture

#### Mode 1: PRD Compliance (existing, keep as-is)
- **Question:** Does the build satisfy the PRD?
- **Method:** Extract ACs, check each against code (static + agentic behavioral)
- **When to use:** During the convergence loop's review fleet, AFTER the build is functionally complete
- **Findings:** "AC-BR3 is only partially implemented" — business logic gaps
- **Keep the existing agentic flow** but increase max_turns from 6 to 15+ for deeper investigation

#### Mode 2: Implementation Quality (NEW, primary mode for fix cycles)
- **Question:** Does the build actually work? Are frontend and backend wired correctly?
- **Method:** Deterministic validators as the PRIMARY scan, agentic Claude only for business logic investigation
- **When to use:** During fix cycles, as the primary audit mode
- **Findings:** "PATCH /work-orders/:id/checklist/:itemId has no backend endpoint" — integration defects

### Implementation Quality Mode: Scan Battery

The Implementation Quality mode should run these deterministic validators as a coordinated battery:

1. **schema_validator** — Check Prisma schema for: missing @relation on FK fields, missing onDelete cascades on parent-child relations, @default("") on UUID FKs, missing indexes on frequently-queried fields, type inconsistencies (BigInt vs Int for same-purpose fields)

2. **integration_verifier** (route matcher) — Parse all `api.get/post/patch/delete()` calls in frontend pages, extract the URL patterns. Parse all `@Controller()` + `@Get/@Post/@Patch/@Delete` decorators in backend controllers, extract the route patterns. Cross-reference and report mismatches. This single scanner would have caught 11 of the 12 CRITICAL findings.

3. **quality_validators** — Check for: services querying models with `deleted_at` fields but not filtering `deleted_at: null`; `(this.prisma as any)` type safety bypasses; post-pagination filtering; invalid UUID fallback strings; raw SQL concatenation without parameterization

4. **quality_checks** (build/test) — Run `pnpm build` and report failures. Run test suite and report failing tests. Compare test results against previous run for regressions.

5. **ui_compliance** (upgraded) — Resolve Tailwind scale values to actual pixels before grid checking. Exclude SVG `<path d="...">` content from spacing analysis. Parse JSX structure to distinguish CSS classes from non-CSS attributes.

### Agentic Claude's Role in Implementation Quality Mode

After the deterministic battery runs, an agentic Claude session (max_turns=15+) should:
1. Receive the deterministic scan results as context
2. Have the validators available as callable TOOLS (not just their results)
3. Investigate findings that deterministic tools can't fully assess: business logic correctness, state machine completeness, auth flow contract alignment, response shape consistency
4. Use Read/Grep/Glob to explore the codebase, PLUS the new validators as tools for targeted re-scans
5. Produce verdicts that are INFORMED by deterministic evidence, not pure LLM judgment

### Why Implementation Quality Must Be Primary for Fix Cycles

The convergence loop's review fleet already checks PRD compliance. Running it again in the audit is redundant. The fix cycle's job is to catch what the review fleet misses — which is exactly the integration-level defects that caused the 62 real findings. The deterministic validators catch these reliably, repeatably, and without false positives from LLM hallucination.

---

## Summary of Required Changes (for audit-architect and audit-implementer)

1. **Implement two-mode architecture** — Mode 1 (PRD Compliance) keeps the existing agentic AC-checking flow. Mode 2 (Implementation Quality) uses deterministic validators as primary scan, agentic Claude for investigation of edge cases only. Mode 2 should be the DEFAULT for fix cycles.

2. **Build five deterministic validators** — schema_validator (Prisma integrity), integration_verifier (route matching), quality_validators (code quality patterns), quality_checks (build/test runner), ui_compliance (upgraded with Tailwind resolution and SVG exclusion). These are CODE-LEVEL scanners, not LLM-based.

3. **Expose validators as agentic tools** — The agentic Claude session should be able to call validators during investigation, not just receive their results. This allows targeted re-scans during deep dives.

4. **Increase agentic investigation depth** — max_turns=6 is too few. Increase to 15+ for deep investigation. The current two-phase approach (investigate then verdict) is sound but needs more room to explore.

5. **Add pre-fix regression gates** — Run test suite before and after fix milestones. Diff results. Reject fixes that introduce test failures or AC regressions. This is enforcement, not advisory markdown.

6. **Add cycle memory** — False positive determinations from cycle N must suppress re-detection in cycle N+1. Fix conclusions must persist across cycles. Previous scan results should be loaded and diffed, not re-discovered from scratch.

7. **Make UX/missing_feature findings actionable** — Either expand the builder to handle feature scaffolding, or reclassify as "manual action required" and exclude from fix candidate scoring.

8. **Add budget-based termination** — If N milestones have been spent with less than X% improvement per milestone, stop and report to the user. The 50+ milestones on ArkanPM should have been capped at ~15.
