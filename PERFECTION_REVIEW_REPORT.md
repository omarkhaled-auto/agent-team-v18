# Builder Perfection Plan — Implementation Review Report

> **Date:** 2026-04-04
> **Reviewers:** 7 parallel agents (prompt-reviewer, gate-reviewer, flow-tracer, audit-reviewer, config-reviewer, conflict-detector, simulation-designer)
> **Scope:** All files modified by the 9-phase, 43-item Builder Perfection Plan
> **Mode:** READ-ONLY review — no files modified

---

## Review Summary

| Reviewer | Findings | Critical | High | Medium | Low | Info |
|----------|----------|----------|------|--------|-----|------|
| prompt-reviewer | 16 | 3 | 4 | 5 | 4 | 0 |
| gate-reviewer | 16 | 5 | 4 | 4 | 3 | 0 |
| flow-tracer | 15 | 5 | 5 | 0 | 0 | 5 |
| audit-reviewer | 18 | 4 | 5 | 5 | 4 | 0 |
| config-reviewer | 16 | 3 | 4 | 5 | 4 | 0 |
| conflict-detector | 11 | 2 | 4 | 5 | 0 | 0 |
| simulation-designer | 24 scenarios | — | — | — | — | — |
| **TOTAL (raw)** | **92 + 24 scenarios** | **22** | **26** | **24** | **15** | **5** |
| **TOTAL (deduplicated)** | **52 unique + 24 scenarios** | **13** | **15** | **14** | **10** | **0** |

> **Note:** Many agents independently discovered the same issues (especially the 6 orphaned quality gate functions). The deduplicated counts below reflect unique findings only.

---

## CRITICAL Findings (Must Fix Before Any Build)

| # | ID | Reviewer(s) | File:Line | Finding | Impact | Recommended Fix |
|---|-----|-------------|-----------|---------|--------|-----------------|
| 1 | ORPHAN-1 | gate, flow, sim | quality_checks.py:8102 | **`check_implementation_depth()` is ORPHANED** — defined but never called from cli.py, coordinated_builder.py, or any production code. Only called in test_builder_perfection_wave3.py. | DEPTH-001 through DEPTH-004 violations are computed but never seen by the orchestrator. Test co-location, error handling, loading/error state checks have ZERO effect on builder behavior. | Wire into coordinated_builder.py post-milestone verification or cli.py post-orchestration scan loop. |
| 2 | ORPHAN-2 | gate, flow, sim | quality_checks.py:7988 | **`verify_endpoint_contracts()` is ORPHANED** — defined but never called from production code. | The "keystone" Phase 4 contract-first verification has ZERO runtime effect. Frontend API calls are never validated against contracts. Uncontracted API calls are never flagged. | Wire into verification.py `verify_task_completion()` or cli.py milestone loop. |
| 3 | ORPHAN-3 | gate, flow, sim | quality_checks.py:573 | **`compute_weighted_score()` is ORPHANED** — defined but never called. | The 1000-point weighted scoring system (Phase 6.3) and >= 850 stop condition are dead code. Actual stop condition in `config_agent.py:evaluate_stop_conditions()` uses improvement-threshold + zero-CRITICAL/HIGH logic, NOT weighted scoring. The 850 threshold exists only in a comment (line 570) and in LLM prompt text (audit_prompts.py:1013). | Either replace or supplement `evaluate_stop_conditions()` with weighted score check. |
| 4 | ORPHAN-4 | gate, flow, sim | quality_checks.py:8050 | **`check_agent_deployment()` is ORPHANED** — defined but never called from production code. | Minimum agent count enforcement (Phase 6.5) has zero effect. Phase leads can deploy 3 agents instead of 8 with no programmatic objection. | Wire into orchestrator or coordinated_builder pre-phase-lead dispatch. |
| 5 | ORPHAN-5 | gate, flow, sim | quality_checks.py:8158 | **`verify_review_integrity()` is ORPHANED** — defined but never called from production code. | Self-checked requirements (review_cycles=0) are never detected. Implementers marking their own work [x] goes uncaught. Review gaming is completely undetectable at runtime. | Wire into coordinated_builder.py post-review verification. |
| 6 | ORPHAN-6 | gate | quality_checks.py:7637 | **`compute_quality_score()` is ORPHANED** — defined but never imported or called. | Regression guardrail quality prediction has zero runtime effect. | Wire into post-build verification or remove. |
| 7 | AUDIT-BYPASS | flow | coordinated_builder.py:32 | **Coordinated builder imports `run_audit`, NOT `run_full_audit`.** The audit-fix loop never uses the new comprehensive auditor, 1000-point scoring, or audit methodology prompts from audit_prompts.py. | The ENTIRE coordinated build loop uses old-style AC-based scoring. New audit methodology from Phase 6 is bypassed in the main build loop. `run_full_audit()` (which calls `_run_comprehensive_gate()` with `COMPREHENSIVE_AUDITOR_PROMPT` and 1000-point scoring) is only reachable via CLI audit-team path, not the coordinated builder. | Change import to `run_full_audit` and update the call at coordinated_builder.py ~line 396. **This is the single most impactful fix.** |
| 8 | PROMPT-GAP-1 | prompt, conflict | agents.py (CODING_LEAD_PROMPT:4130) | **Agent count minimums MISSING from coding-lead AND review-lead prompts.** Plan Phase 6.5.1 specifies "MINIMUM 8 code-writers at enterprise depth" and "MINIMUM 5 reviewers" as hard mandates. Grep for "MINIMUM 8" returns zero matches in agents.py. Neither CODING_LEAD_PROMPT nor REVIEW_LEAD_PROMPT has agent deployment minimum rules. | Phase leads will continue deploying 3-4 agents instead of 8-15, causing the exact shallow-coverage problem the plan aims to fix. | Add the "Agent Deployment Rules (MANDATORY)" block from Plan Phase 6.5.1 to both prompts. |
| 9 | PROMPT-GAP-2 | prompt | agents.py (ORCHESTRATOR) | **GATE 7 (Fleet Scaling) NOT in orchestrator prompt.** Plan Phase 6.5.2 specifies a GATE 7 that enforces minimum deployment counts and re-instructs phase leads that under-deploy. No "GATE 7" exists. Convergence gates stop at GATE 6. | Orchestrator has no mechanism to detect or correct phase leads that deploy too few agents. | Add GATE 7 to Section 3 of ORCHESTRATOR_SYSTEM_PROMPT, after GATE 6. |
| 10 | PROMPT-GAP-3 | prompt | agents.py:4130-4187 | **CODING_LEAD_PROMPT has no contract-first frontend blocking gate.** Plan Phase 4.3 says coding-lead MUST include contract entries in each frontend task and frontend tasks CANNOT be assigned until ENDPOINT_CONTRACTS.md exists. Coding-lead has zero mention of ENDPOINT_CONTRACTS.md. | Frontend tasks assigned without contract context, reproducing the 34% wiring score. The contract-first protocol is broken at the assignment level. | Add "FRONTEND TASK ASSIGNMENT PROTOCOL" from task-assigner prompt (line 3605-3619) to coding-lead prompt. |
| 11 | CONFIG-GAP-1 | config | config.py:1103-1148 | **5 of 8 enterprise overrides from Plan Phase 9.2 are MISSING.** Only `convergence.max_cycles=25` is implemented. Missing: `verification.min_test_count=10`, `convergence.escalation_threshold=6`, `audit_team.score_healthy_threshold=95.0`, `audit_team.score_degraded_threshold=85.0`, `audit_team.fix_severity_threshold="LOW"`. | Enterprise builds run with default min_test_count=0 (no test enforcement), escalation_threshold=3 (too eager), and audit thresholds at 90/70 instead of 95/85. Quality gates materially weaker than plan intends. | Add all 5 missing `_gate()` calls to the `elif depth == "enterprise"` block. |
| 12 | CONFIG-GAP-2 | config, sim | fix_prd_agent.py:136-142 | **LLM confidence threshold is declared but NEVER applied.** `LLM_CONFIDENCE_THRESHOLD=0.8` exists, `filter_findings_for_fix()` accepts `confidence_threshold` param, but the filter body is `pass` with a comment admitting Finding has no confidence field. ALL LLM findings pass through unfiltered. | Low-confidence LLM findings bloat fix PRDs, causing scope creep and fix cycles chasing phantom issues. | Either add a `confidence: float = 1.0` field to Finding and populate from Claude responses, or remove the dead parameter. |
| 13 | CONFIG-GAP-3 | config | config.py:760-765 | **`AgentScalingConfig` is defined but NEVER READ.** `max_requirements_per_coder=15`, `max_requirements_per_reviewer=25`, `max_requirements_per_tester=20` exist only as config values. No code reads these to scale agent counts. | Agent scaling is purely cosmetic. The orchestrator deploys agents based on `DEPTH_AGENT_COUNTS` dict, ignoring per-agent requirement caps. A single coder can still receive 50+ requirements. | Wire into task assignment logic in agents.py or coordinated_builder.py. |

---

## HIGH Findings (Fix Before EVS Rebuild)

| # | ID | Reviewer(s) | File:Line | Finding | Impact | Recommended Fix |
|---|-----|-------------|-----------|---------|--------|-----------------|
| 1 | CONTRACT-SPLIT | flow, conflict | cli.py:1862-1879 vs agents.py:1585 | **CLI injects `API_CONTRACTS.json` but prompts reference `ENDPOINT_CONTRACTS.md`.** Two different contract files with potentially different content. Frontend code-writers receive one format (JSON) in prompt context but are instructed to read a different format (Markdown) from disk. | Potential for contract misalignment between injected and on-disk contracts. | Unify on one contract file, or ensure both are generated and kept consistent. |
| 2 | CONTRACT-ENFORCE | flow, sim | agents.py:461-483 | **Milestone sequencing is PROMPT-ONLY.** No Python gate prevents frontend milestones from running before backend completes. `_detect_milestone_type()` in cli.py classifies milestones but doesn't enforce ordering. | The keystone contract-first protocol has ZERO Python enforcement. Claude can ignore the sequencing instruction (~70% reliability). | Add a Python gate in the CLI milestone loop that checks milestone type ordering and blocks frontend milestones until backend completes. |
| 3 | DEPTH-GLOB | gate | quality_checks.py:8113-8118 | **`check_implementation_depth()` DEPTH-001 glob `*.service.ts` matches `.service.spec.ts` files.** Spec files flagged for not having a spec file (circular). `with_suffix("").with_suffix(".spec.ts")` on `.service.spec.ts` produces `.service.spec.spec.ts`. | Even if wired, spec files would generate false positives. | Add filter: `if svc.name.endswith(".spec.ts"): continue` |
| 4 | DEPTH-GLOB-2 | gate | quality_checks.py:8120-8126 | **DEPTH-002 same glob issue** — spec files flagged for missing try/catch. | Nonsensical violations on test files. | Same fix: skip `.spec.ts` files. |
| 5 | CONTRACT-REGEX | gate, conflict | quality_checks.py:8030-8034 | **`verify_endpoint_contracts()` path normalization is buggy.** `method_path[1].replace(":id", "/:id")` can produce `//` in paths, and the `or normalized in method_path[1]` check is backwards. | Even if wired, contract matching would produce false negatives for parameterized routes. | Fix normalization: strip leading slashes before comparison, use proper route-pattern matching. |
| 6 | TEAM-ORCH-GAP | prompt | agents.py:1625-1786 | **TEAM_ORCHESTRATOR_SYSTEM_PROMPT lacks most perfection plan additions.** No Section 16 (contract-first), no milestone sequencing rules, no test co-location mandate, no stub handler prohibition. | Builds using team mode miss all perfection plan orchestrator improvements. | Mirror key additions into TEAM_ORCHESTRATOR_SYSTEM_PROMPT. |
| 7 | THOUGHT-BUDGET | config | config.py:1145-1146 | **Enterprise thought budgets computed as 2x defaults yielding {1:16, 2:20, 3:24, 4:16, 5:16}.** Plan specifies {1:20, 2:25, 3:25, 4:20, 5:20}. Values are 20-25% lower than plan targets. | Orchestrator reasoning at enterprise depth gets fewer thought steps than intended. | Replace `v * 2` with explicit dict from plan. |
| 8 | FIELD-BLIND | sim, conflict | quality_checks.py:291-375 | **Contract compliance scoring checks URL paths but NOT field names.** TruthScorer matches API endpoints but never validates request/response field shapes. | The exact ArkanPM failure mode (correct endpoints, wrong field names) is invisible to scoring. | Add field-name matching from ENDPOINT_CONTRACTS.md response shapes. |
| 9 | AUDIT-SWR | audit | audit_prompts.py:355-596 | **INTERFACE_AUDITOR_PROMPT missing `useSWR` pattern.** One of the most popular React/Next.js data-fetching libraries is uncovered. | Interface auditor will miss API calls in SWR-based projects. | Add `useSWR(`, `useSWRMutation(`, `mutate(` to Step 1 JS/TS patterns. |
| 10 | AUDIT-SPRING | audit | audit_prompts.py:355-596 | **INTERFACE_AUDITOR_PROMPT missing Spring Boot patterns.** `@GetMapping`, `@PostMapping`, etc. completely absent from Step 2 backend route grep patterns. | Spring Boot projects get zero backend route extraction. | Add Spring Boot annotations to Step 2 patterns. |
| 11 | AUDIT-PRD-PATH | audit | audit_prompts.py:53-312 | **REQUIREMENTS_AUDITOR_PROMPT has no `{prd_path}` placeholder.** Auditor told to read PRD but never given its path. Relies on `task_text` being provided, which may be None. | Requirements auditor may have no PRD reference, producing incomplete AC mapping. | Add `{prd_path}` placeholder and inject in `build_auditor_agent_definitions()`. |
| 12 | REGEX-INCOMPLETE | conflict | quality_checks.py:8014-8016 | **Two different API call detection regexes in same file.** `verify_endpoint_contracts()` uses a narrow pattern missing Angular/Nuxt/Python. TruthScorer at line 352-354 has a broader pattern. | `verify_endpoint_contracts()` would miss API calls in non-standard frameworks. | Unify into a single shared regex constant. |
| 13 | DEDUP-THRESHOLD | config | audit_agent.py:1376 | **Dedup similarity `> 0.80` (exclusive), plan says "80%".** Findings at exactly 80% similarity slip through. | Edge case: near-duplicate findings survive dedup. | Change to `>= 0.80`. |
| 14 | PRIORITY-ORDER | config | fix_prd_agent.py:58-84 | **SECURITY category check before WIRING keywords.** Auth-related wiring bugs classified as AUTH(1) instead of WIRING(0). Also: CRITICAL security findings can be deprioritized behind MEDIUM wiring fixes due to impact-before-severity sort. | Security vulns deprioritized behind cosmetic wiring fixes in fix PRDs. | Check wiring keywords FIRST regardless of category. Consider severity as primary sort, impact as secondary. |
| 15 | EXPORT-BUG | audit | audit_team.py:365 | **`__all__` exports `compute_convergence_plateau` but function is named `detect_convergence_plateau`.** | `AttributeError` if imported by exported name. | Fix the name in `__all__`. |

---

## MEDIUM Findings (Fix When Convenient)

| # | ID | Reviewer(s) | File:Line | Finding | Impact | Recommended Fix |
|---|-----|-------------|-----------|---------|--------|-----------------|
| 1 | AGENT-FLOOR | gate | quality_checks.py:8067-8069 | `check_agent_deployment()` uses `max(2, total_reqs // 15)` — for enterprise the plan says MINIMUM 8, not 2. | Dynamic formula contradicts hard minimum. | Use `max(8, total_reqs // 15)` for enterprise. |
| 2 | DEPTH-NEXTJS | gate | quality_checks.py:8129-8148 | DEPTH-003/004 checks ALL page.tsx including layout-adjacent pages. Doesn't check for sibling `loading.tsx`/`error.tsx` files (which ARE the loading/error states in Next.js). | False positives for pages using Next.js file-based loading/error patterns. | Check for sibling loading.tsx / error.tsx as alternatives. |
| 3 | CONTRACT-DEFAULT | gate | quality_checks.py:291-375 | `_score_contract_compliance()` returns 0.0 when no contracts file exists (common for new builds). | Contract dimension drags down truth score for all builds pre-contract-generation. | Return neutral score (0.5 or skip dimension) when no contracts exist. |
| 4 | PROMPT-POSITION | prompt | agents.py:1580 | Section 16 (contract-first) sits in the middle-to-end of ~22K token orchestrator prompt. LLM attention is strongest at beginning and end. | May receive weaker attention. | Move higher or add cross-reference in Section 4. |
| 5 | DUAL-CONTRACT | prompt | agents.py:2948-2959 | Code-writer has BOTH "API CONTRACT COMPLIANCE for SVC-xxx items" (line 2728) and "CONTRACT CONSUMPTION RULES" (line 2948). Overlapping sources. | Code-writers confused about whether REQUIREMENTS.md SVC-xxx table or ENDPOINT_CONTRACTS.md is source of truth. | Consolidate or clarify precedence. |
| 6 | TEST-COLOC-GAP | prompt | agents.py:4130 | Test co-location is in orchestrator and task-assigner but NOT in coding-lead. Plan Phase 3.2 explicitly says add to CODING_LEAD_PROMPT. | Coding-lead may assign waves separating implementation from tests. | Add test co-location rule to CODING_LEAD_PROMPT. |
| 7 | PROMPT-SIZE | prompt | agents.py:67-1615 | ORCHESTRATOR_SYSTEM_PROMPT is ~22,358 tokens. AUDIT_LEAD_PROMPT is ~20,871 tokens. Risk of context overflow in large enterprise builds. | Important instructions in positions 10K-20K tokens may receive reduced attention. | Consider splitting into core + appendix, or tighten check_context_budget threshold. |
| 8 | FIX-NO-AFTER | config | fix_prd_agent.py:532-533 | Plan Phase 8.3 calls for "before/after code diffs". Function shows "CURRENT CODE (broken)" but generates NO "AFTER" code block. Only text fix_suggestion. | Fix PRDs describe WHAT to change but not the exact target code. | Generate hypothetical "REQUIRED CODE (after)" block. |
| 9 | ESCALATION-GAP | config | config.py:1130 | Enterprise sets max_cycles=25 but escalation_threshold stays at default 3. Plan says escalation=6 for enterprise. | Premature escalation at cycle 3 defeats the purpose of 25 cycles. | Add `_gate("convergence.escalation_threshold", 6, ...)`. |
| 10 | SCORE-DUAL | audit | audit_prompts.py:1163-1211 | Two scoring systems: Scorer Agent (per-requirement %) vs Comprehensive Auditor (1000-point weighted). `should_terminate_reaudit()` uses `healthy_threshold=90.0` (scorer's scale), NOT 850/1000 (comprehensive scale). | Competing scoring systems could produce contradictory termination decisions. | Document which score is authoritative. Use comprehensive 1000-point as definitive. |
| 11 | AC-HYBRID | config | audit_agent.py:846-848 | Fallback to `_extract_numbered_criteria()` only triggers when ZERO ACs found. PRDs mixing AC-N format with plain numbered lists lose the numbered items. | Partial extraction for hybrid PRDs. | Run numbered extraction as supplementary pass, not just fallback. |
| 12 | TECH-MATCH | audit | audit_prompts.py:1340-1354 | Tech-stack matching uses substring `if key in stack_lower`. "react" matches "react-native", "next" matches "nextauth". | False tech-stack matches possible. | Use word boundary matching. |
| 13 | CATEGORY-KEYS | conflict | audit_prompts.py:771-1009 vs quality_checks.py:560-568 | Category names are PROSE in audit_prompts.py ("Frontend-Backend Wiring") vs snake_case in quality_checks.py (`frontend_backend_wiring`). Currently separate paths, but any integration would fail silently on key mismatch. | Future integration risk. | Define canonical category key constants in one place. |
| 14 | SECURITY-DEPRI | sim | fix_prd_agent.py:58-84 | Impact prioritization puts MEDIUM wiring before CRITICAL security. A CRITICAL SQL injection (impact=1) sorts AFTER MEDIUM field mismatch (impact=0). | Dangerous: security vulns deprioritized behind cosmetic wiring. | Consider severity as primary tiebreak within impact groups, or exempt CRITICAL severity from impact ordering. |

---

## LOW / INFO Findings

| # | Reviewer | File:Line | Finding |
|---|---------|-----------|---------|
| 1 | gate | quality_checks.py:570 | Comment says ">= 850" but never enforced in code. Misleading. |
| 2 | gate | quality_checks.py:8172-8183 | `verify_review_integrity()` treats absence of review_cycles metadata as suspicious, but format is LLM-determined. |
| 3 | gate | audit_prompts.py:1013 | LLM prompt 850 stop condition disagrees with Python `evaluate_stop_conditions()`. |
| 4 | prompt | agents.py:988 | One remaining "should" in instruction context — inside a quoted test name, not an instruction. Acceptable. |
| 5 | prompt | agents.py:459 | "(More as needed)" escape hatch in PRD analyzer fleet description. |
| 6 | prompt | agents.py (multiple) | Redundant content between ORCHESTRATOR_SYSTEM_PROMPT and phase lead prompts (intentional for self-contained context). |
| 7 | audit | audit_prompts.py:319-348 | TECHNICAL_AUDITOR_PROMPT (~30 lines) significantly shorter than other methodology prompts (~250+ lines). |
| 8 | audit | audit_prompts.py:602-639 | TEST_AUDITOR_PROMPT (~38 lines) similarly short. |
| 9 | config | audit_agent.py:1359-1364 | Dedup severity_order missing Severity.REQUIRES_HUMAN. Returns same priority as ACCEPTABLE_DEVIATION. |
| 10 | config | fix_prd_agent.py:671-679 | Regression guard truncates test file candidates from 3 to 2. Minor coverage loss. |

---

## Prompt Coherence Assessment

### Cross-Section Conflicts Found

1. **Contract-first blocking gate (CRITICAL GAP):** Orchestrator Section 16 (line 1582) says "Frontend milestones CANNOT start until ENDPOINT_CONTRACTS.md exists." Task-assigner (line 3605) enforces this. But CODING_LEAD_PROMPT (line 4130) — the actual agent driving wave execution — has ZERO mention of this gate. The coding-lead can assign frontend tasks without contracts.

2. **Dual contract sources in code-writer:** "API CONTRACT COMPLIANCE for SVC-xxx items" (line 2728) and "CONTRACT CONSUMPTION RULES" (line 2948) give slightly different instructions for the same problem. No clear precedence.

3. **Test co-location gap:** Orchestrator (line 536) and task-assigner (line 3585) have it. Coding-lead does not.

4. **Milestone sequencing not consolidated:** Ordering spread across Section 4 (line 466), Section 7 (line 817), and Section 16 (line 1582). No single canonical block in Section 7 as the plan specified.

5. **Review checklist alignment (PASS):** Code-writer implementation checklists (lines 2904-2934) and code-reviewer review checklists (lines 3295-3324) cover the SAME items. Properly aligned.

### Language Hardening Audit

- **Total "should" in instruction contexts remaining:** 1 (in quoted test name — acceptable)
- **Total escape hatches remaining:** 2 ("More as needed" at line 459; "attempt to" at line 5649 — both descriptive, not instructional)
- **Sentences mangled by blind replacement:** 0 (hardening was done carefully)
- **Quantified expectations present:** YES ("reject at least 40%", "minimum 3 test cases", "minimum 5 findings", "Check ALL 15 OWASP categories")

### Prompt Engineering Quality

| Prompt | Size | Rules at Top? | Checklists? | Terminology? | BAD/GOOD? | Negative? | Score |
|--------|------|--------------|-------------|-------------|-----------|-----------|-------|
| ORCHESTRATOR | ~22K tok | YES | YES | FAIR (M5 issue) | YES | YES | 8/10 |
| PLANNER | ~1.5K tok | YES | YES | GOOD | YES | YES | 9/10 |
| CODE_WRITER | ~4.8K tok | YES | EXCELLENT (4 checklists) | FAIR (dual sources) | YES | YES | 8/10 |
| CODE_REVIEWER | ~5.4K tok | YES | EXCELLENT (3 checklists) | GOOD | YES | YES | 9/10 |
| TASK_ASSIGNER | ~4K tok | YES | YES | GOOD | YES | PARTIAL | 8/10 |
| **CODING_LEAD** | **~0.7K tok** | **POOR** | **NO** | **N/A** | **NO** | **NO** | **4/10** |
| REVIEW_LEAD | ~4.5K tok | YES | YES | GOOD | NO | NO | 7/10 |
| TEAM_ORCHESTRATOR | ~7.9K tok | YES | YES | FAIR | NO | NO | 6/10 |

> **Key finding:** CODING_LEAD_PROMPT is the weakest prompt at ~728 tokens. It is the most under-specified phase lead despite driving the actual implementation. It lacks: contract-first gate, test co-location, agent count minimums, enterprise scaling, and mock data prohibition.

---

## Quality Gate Integration Map

| Gate Function | Defined | Called | Result Used | Verdict |
|--------------|---------|-------|-------------|---------|
| `check_implementation_depth()` | quality_checks.py:8102 | NOWHERE (only tests) | N/A | **ORPHAN** |
| `verify_review_integrity()` | quality_checks.py:8158 | NOWHERE (only tests) | N/A | **ORPHAN** |
| `verify_endpoint_contracts()` | quality_checks.py:7988 | NOWHERE (only tests) | N/A | **ORPHAN** |
| `check_agent_deployment()` | quality_checks.py:8050 | NOWHERE (only tests) | N/A | **ORPHAN** |
| `compute_weighted_score()` | quality_checks.py:573 | NOWHERE (only tests) | N/A | **ORPHAN** |
| `compute_quality_score()` | quality_checks.py:7637 | NOWHERE | N/A | **ORPHAN** |
| `TruthScorer.score()` | quality_checks.py:235 | coordinated_builder.py:447 | Logged, passed to skills | **CONNECTED** (but does NOT block convergence) |
| `evaluate_stop_conditions()` | config_agent.py:243 | coordinated_builder.py:524 | Controls STOP/CONTINUE | **CONNECTED** (the REAL gate) |
| `run_spot_checks()` | quality_checks.py:2256 | cli.py, verification.py, audit_agent.py | Fed to violation pipeline | **CONNECTED** |
| `run_full_audit()` | audit_agent.py:1495 | CLI audit-team path ONLY | NOT from coordinated_builder | **PARTIALLY CONNECTED** |

> **6 of 6 new perfection-plan gate functions are ORPHANED.** The builder will produce identical output with or without them.

---

## Contract-First Protocol Assessment

| Check | Python-Enforced? | Prompt-Only? | Evidence |
|-------|-----------------|--------------|---------|
| ENDPOINT_CONTRACTS.md generation | | **YES** | agents.py:1584 — prompt tells orchestrator to deploy integration agent. No Python function generates it. |
| Frontend blocked without contracts | | **YES** | agents.py:1594 — prompt says "BLOCKING GATE". No Python gate checks for file before frontend milestones. |
| Code-writers receive contract entries | **PARTIAL (wrong file)** | **YES** | cli.py:1862 injects API_CONTRACTS.json. Prompts reference ENDPOINT_CONTRACTS.md. Two different files. |
| Contract compliance verified post-build | **YES (exists, never called)** | | quality_checks.py:7988 defined, functional, but never called from production. |
| Contract staleness detected | | **YES** | Prompt says "contract MUST be updated". No staleness detection in Python. |
| Field-level compliance checked | | **NO** | TruthScorer checks URL paths only, not field names. The exact ArkanPM failure mode is invisible. |

> **Verdict: The contract-first protocol is almost entirely PROMPT-INSTRUCTED with ~70% reliability. The one Python function that could enforce it is ORPHANED.**

---

## Execution Flow Verification

| Step | Expected (from plan) | Actual (from code) | Match? |
|------|--------------------|--------------------|--------|
| Planner produces atomic requirements | YES | Prompt-only instruction (agents.py:2359). No Python validation. | **PARTIAL** — prompt present, no enforcement |
| Milestones sequenced BACKEND→CONTRACT→FRONTEND | YES | Prompt-only (agents.py:461-483). `_detect_milestone_type()` classifies but doesn't enforce order. | **PARTIAL** — prompt present, no enforcement |
| Contract generated from actual controllers | YES | Prompt-only (agents.py:1584). No Python function generates it. | **PARTIAL** — prompt present, no enforcement |
| Frontend blocked without contracts | YES | Prompt-only (agents.py:1594). No Python gate. | **NO** — no enforcement at all |
| 8+ code-writers deployed at enterprise | YES | Not in coding-lead prompt. `check_agent_deployment()` exists but orphaned. | **NO** — neither prompt nor Python |
| 4 specialized reviewers deployed | YES | In review-lead prompt (agents.py:4248). Not enforced by Python. | **PARTIAL** — prompt present, no enforcement |
| Audit uses new methodology prompts | YES | `run_full_audit()` uses them, but coordinated_builder imports `run_audit()` instead. | **NO** — bypassed in main build loop |
| Audit uses 1000-point weighted scoring | YES | `compute_weighted_score()` exists but is orphaned. `_run_comprehensive_gate()` exists but only called from `run_full_audit()` which is not used by coordinated_builder. | **NO** — dead code |
| Fix PRD includes before/after diffs | YES | `_enrich_findings_with_code()` adds "CURRENT CODE (broken)" but no "AFTER" block. | **PARTIAL** — before only, no after |
| Fix PRD prioritized by impact | YES | `_get_impact_priority()` sorts WIRING > AUTH > MISSING > QUALITY. Works. | **YES** |

---

## Orphaned Code

| Function/Prompt | File | Defined | Called | Effect on Builder |
|----------------|------|---------|-------|-------------------|
| `check_implementation_depth()` | quality_checks.py | Line 8102 | Tests only | **ORPHAN** — depth checks never run |
| `verify_endpoint_contracts()` | quality_checks.py | Line 7988 | Tests only | **ORPHAN** — contract verification never runs |
| `check_agent_deployment()` | quality_checks.py | Line 8050 | Tests only | **ORPHAN** — agent counts never enforced |
| `compute_weighted_score()` | quality_checks.py | Line 573 | Tests only | **ORPHAN** — 850 stop condition never checked |
| `verify_review_integrity()` | quality_checks.py | Line 8158 | Tests only | **ORPHAN** — review gaming never detected |
| `compute_quality_score()` | quality_checks.py | Line 7637 | Nowhere | **ORPHAN** — regression guardrail dead |
| `AgentScalingConfig` | config.py | Line 760 | Nowhere | **ORPHAN** — scaling config never read |
| `LLM_CONFIDENCE_THRESHOLD` | fix_prd_agent.py | Line 40 | Declared, filter is `pass` | **DEAD** — confidence filtering is no-op |
| `run_full_audit()` | audit_agent.py | Line 1495 | CLI audit-team only | **PARTIALLY ORPHAN** — not used by coordinated_builder |

---

## Simulation Readiness

### MiniBooks Validation Checklist

| # | Check Point | How to Verify | Risk Level |
|---|------------|---------------|-----------|
| 1 | REQUIREMENTS.md has atomic requirements (5-15/feature) | Count checkbox items per feature, verify single-file scope | LOW — prompt present, planner usually follows |
| 2 | ENDPOINT_CONTRACTS.md exists after backend milestones | Check file existence and entry count vs controllers | **HIGH** — no Python gate, prompt-only |
| 3 | Frontend milestones blocked until contracts exist | Check TASKS.md timestamps vs contract file creation | **CRITICAL** — completely unenforced |
| 4 | Frontend API calls match contract field names | Run `verify_endpoint_contracts()` manually (it works, just isn't wired) | **CRITICAL** — orphaned code, field names unchecked |
| 5 | 4 specialized reviewer types ran with rejections | Check REQUIREMENTS.md for reviewer metadata | MEDIUM — prompt-instructed to review-lead |
| 6 | Audit uses 1000-point weighted scoring | Check for COMPREHENSIVE_SCORE in audit output | **CRITICAL** — coordinated builder uses old `run_audit()` |
| 7 | Fix PRD includes before/after code diffs | Check fix PRD output for code blocks | MEDIUM — "before" present, "after" missing |

### Priority-Ordered Bypass Risks

1. **ALL 6 GATE FUNCTIONS ARE DEAD CODE** — The entire enforcement layer (Phases 3-6) is non-functional. Functions exist, tests pass, but nothing in the production pipeline calls them.
2. **Coordinated builder bypasses new audit methodology** — imports `run_audit` instead of `run_full_audit`. The 1000-point scoring, comprehensive auditor, and implementation quality checks are unreachable in the main build loop.
3. **Contract-first protocol has zero Python enforcement** — LLM may ignore milestone ordering (~30% failure rate for complex multi-step instructions).
4. **Implementation depth checks are substring-only** — Even if wired, empty test files pass (`file.exists()` only), empty catch blocks pass (`"catch" in content`), comments about loading pass (`"loading" in content.lower()`).
5. **Coding-lead is the weakest link** — At 728 tokens, it lacks every major perfection plan addition (contract gate, agent minimums, test co-location).

---

## Verdict

| Aspect | Status | Confidence |
|--------|--------|-----------|
| Prompts are coherent | **MOSTLY YES** — but CODING_LEAD_PROMPT has critical gaps | MEDIUM |
| Quality gates are connected | **NO** — all 6 new gates are orphaned | **HIGH** |
| Contract-first is enforced | **NO** — prompt-only, zero Python enforcement | **HIGH** |
| Audit methodology is complete | **YES** — prompts are thorough and well-wired to audit_team.py | HIGH |
| Audit methodology is used in builds | **NO** — coordinated_builder bypasses `run_full_audit()` | **HIGH** |
| No orphaned code | **NO** — 6 functions + 2 configs + 1 threshold are dead | **HIGH** |
| Ready for MiniBooks simulation | **NO** — 3 critical checks would fail | **HIGH** |
| Ready for EVS rebuild | **NO** — enforcement layer is non-functional | **HIGH** |

### Recommendation

**[x] FIX CRITICAL ISSUES FIRST — specific items to fix before any build:**

#### Tier 1: Fix These First (unlocks the entire enforcement layer)

1. **Wire the 6 orphaned gate functions** into `coordinated_builder.py` or `cli.py` milestone loop:
   - `check_implementation_depth()` → post-milestone verification
   - `verify_endpoint_contracts()` → post-frontend-milestone gate
   - `check_agent_deployment()` → pre-phase-lead dispatch
   - `compute_weighted_score()` → convergence stop condition (supplement `evaluate_stop_conditions()`)
   - `verify_review_integrity()` → post-review verification
   - `compute_quality_score()` → post-build quality prediction (or remove if not needed)

2. **Change `coordinated_builder.py:32`** to import and use `run_full_audit` instead of `run_audit`. This single change activates the comprehensive auditor, 1000-point scoring, and all audit methodology prompts in the build loop.

3. **Unify contract file naming** — standardize on `ENDPOINT_CONTRACTS.md` everywhere or ensure `API_CONTRACTS.json` and `ENDPOINT_CONTRACTS.md` are kept in sync.

#### Tier 2: Fix These Next (completes the prompt layer)

4. **Add agent count minimums** to CODING_LEAD_PROMPT and REVIEW_LEAD_PROMPT (Plan Phase 6.5.1).
5. **Add GATE 7** to orchestrator Section 3 (Plan Phase 6.5.2).
6. **Add contract-first frontend blocking** to CODING_LEAD_PROMPT (Plan Phase 4.3).
7. **Add the 5 missing enterprise config overrides** (Plan Phase 9.2).
8. **Fix enterprise thought budgets** to match plan values {1:20, 2:25, 3:25, 4:20, 5:20}.

#### Tier 3: Fix Before EVS (hardens the gates)

9. **Fix depth check globs** to exclude .spec.ts files.
10. **Fix `verify_endpoint_contracts()` path normalization** and unify API call detection regex.
11. **Add field-level contract compliance** (not just URL path matching).
12. **Mirror perfection plan additions** into TEAM_ORCHESTRATOR_SYSTEM_PROMPT.
13. **Implement or remove** LLM confidence threshold (currently dead code).
14. **Fix impact prioritization** so CRITICAL security findings are never deprioritized below MEDIUM wiring.

---

## Appendix: Plan Phase Implementation Status

| Phase | Item | Implemented? | Wired? | Effective? |
|-------|------|-------------|--------|-----------|
| 1.1 | Pattern memory SQL fix | Needs verification | — | — |
| 1.2 | Skills float crash fix | Needs verification | — | — |
| 1.3 | Contract path fix (`_score_contract_compliance`) | YES | YES (TruthScorer) | YES — but scores 0.0 when no contracts |
| 1.4 | AC extraction patterns expanded | YES | YES (audit_agent) | YES |
| 1.5 | Finding deduplication | YES | YES (audit_agent) | YES — threshold `> 0.80` vs plan's `80%` |
| 2.1 | Atomic requirement rules | YES (prompt) | N/A | PROMPT-ONLY (~80% reliable) |
| 2.2 | Milestone sequencing | YES (prompt) | NO gate | PROMPT-ONLY (~70% reliable) |
| 2.3 | PRD reading depth | YES (prompt) | N/A | PROMPT-ONLY |
| 3.1 | Implementation checklists (4x) | YES (prompt) | N/A | PROMPT-ONLY |
| 3.2 | Test co-location | PARTIAL (missing from coding-lead) | N/A | PROMPT-ONLY, incomplete |
| 3.3 | Enterprise depth scaling | YES (prompt) | N/A | PROMPT-ONLY (not depth-gated) |
| 4.1 | Contract-first Section 16 | YES (prompt) | NO gate | PROMPT-ONLY |
| 4.2 | Contract consumption rules | YES (prompt) | N/A | PROMPT-ONLY |
| 4.3 | Coding-lead contract gate | **MISSING** | — | — |
| 5.1 | Specialized reviewers (4 types) | YES (prompt) | N/A | PROMPT-ONLY |
| 5.2 | Review checklists (3x) | YES (prompt) | N/A | PROMPT-ONLY |
| 6.1 | Comprehensive auditor prompt | YES | YES (audit_team.py) | YES — but bypassed by coordinated_builder |
| 6.2 | Interface auditor prompt | YES | YES (audit_team.py) | YES — missing SWR, Spring patterns |
| 6.3 | 1000-point weighted scoring | YES (code) | **ORPHANED** | **NO** |
| 6.4 | Requirements auditor prompt | YES | YES (audit_team.py) | YES — missing prd_path placeholder |
| 6.5.1 | Agent count minimums (prompts) | **MISSING** | — | — |
| 6.5.2 | GATE 7 (fleet scaling) | **MISSING** | — | — |
| 7.1 | AC extraction regex (table format) | YES | YES | YES |
| 7.2 | Finding deduplication | YES | YES | YES |
| 8.1 | Impact-based prioritization | YES | YES | YES (but security deprioritization risk) |
| 8.2 | Before/after code diffs | PARTIAL (before only) | YES | PARTIAL |
| 8.3 | Regression guards | YES | YES | YES |
| 8.4 | Contract references in fixes | PARTIAL ("see contracts" pointer) | YES | PARTIAL |
| 9.1 | Language hardening | YES | N/A | YES — clean execution |
| 9.2 | Enterprise config overrides | PARTIAL (1 of 6) | YES | **MOSTLY MISSING** |
| 9.3 | Enterprise thought budgets | YES (computed) | YES | WRONG VALUES (20-25% low) |

**Implementation score: 29/43 items implemented, 8/43 wired and effective, 6/43 missing entirely.**

The fundamental problem: the plan's enforcement layer (quality gates, weighted scoring, agent count checks, contract verification) was **implemented as code** but **never connected to the pipeline**. The prompt-layer improvements are present and well-crafted, but the Python-enforcement layer that would make them reliable is entirely dead code.
