# Task: Optimize Department Skill Generation for Actionable, High-Impact Prompts

## Context

You are working on `agent-team-v15`, a multi-agent builder system that uses Claude to build full applications from PRDs. The builder has a **self-learning pipeline** where build outcomes (truth scores, audit findings, gate results) are distilled into **skill files** that get injected into department agent prompts on subsequent builds.

The skill files currently work end-to-end (verified in production builds), but the content they produce is **generic and passive**. The coding and review agents receive vague statistical summaries instead of sharp, actionable instructions. This directly impacts build quality — the client build is next.

## Current State

### Where skills are generated
- `src/agent_team_v15/skills.py` — `update_skills_from_build()` reads audit data and writes skill markdown files
- `load_skills_for_department(skills_dir, department_name)` returns skill content for prompt injection

### Where skills are injected
- `src/agent_team_v15/department.py:197-220` — injects into department agent prompts (coding-dept-head, review-dept-head)
- `src/agent_team_v15/cli.py:801-815` — injects into orchestrator prompt

### Current skill output (from real V4 build)

**coding_dept.md:**
```markdown
# Coding Department Skills
<!-- Auto-updated by agent-team. Do not edit manually. -->
<!-- Last updated: 2026-04-03T19:21:55Z | Builds analyzed: 2 -->

## Quality Targets
- requirement_coverage: historically 0.59 -- cross-reference every PRD requirement
- contract_compliance: historically 0.00 -- define API contracts BEFORE coding
- error_handling: historically 0.58 -- wrap ALL async route handlers in try/catch
- test_presence: historically 0.20 -- test files must exist for all source files
- security_patterns: historically 0.25
- post-orchestration: historically 0.47
```

**review_dept.md:**
```markdown
# Review Department Skills
<!-- Auto-updated by agent-team. Do not edit manually. -->
<!-- Last updated: 2026-04-03T19:21:55Z | Builds analyzed: 2 -->

## Weak Quality Dimensions (review these first)
- requirement_coverage: avg 0.59 -- every PRD item must map to code
- contract_compliance: avg 0.00 -- verify all contracts have implementations
- error_handling: avg 0.58
- test_presence: avg 0.20 -- reject submissions without tests
- security_patterns: avg 0.25
- post-orchestration: avg 0.47

## Gate History
- GATE_REQUIREMENTS: PASS -- REQUIREMENTS.md found with 29 requirement items
- GATE_ARCHITECTURE: FAIL -- No Architecture Decision or Integration Roadmap section
- GATE_PSEUDOCODE: PASS -- Found 22 pseudocode file(s)
- GATE_CONVERGENCE: PASS -- Convergence 100.0% >= 90.0% threshold
- GATE_TRUTH_SCORE: FAIL -- 1 score(s) below 0.95 threshold
- GATE_E2E: FAIL -- E2E tests not fully passing
- GATE_INDEPENDENT_REVIEW: PASS
```

### What's wrong with this

1. **Generic advice** — "wrap ALL async route handlers in try/catch" is vague. The agent doesn't know where, how, or what pattern to follow.
2. **No actionable examples** — "contract_compliance: historically 0.00" states the problem but gives no solution template.
3. **No severity prioritization** — dimensions at 0.00 (contract_compliance, test_presence) are listed alongside 0.59 (requirement_coverage) with equal weight. The agent should attack zeros FIRST.
4. **Review skills are passive** — "reject submissions without tests" is advice the review agent may ignore. It needs to be framed as a hard rule with specific rejection criteria.
5. **Gate history is raw data dump** — listing gate pass/fail results doesn't tell the agent what corrective action to take.
6. **No concrete file/pattern examples** — the agents are building real code. They need to see "create `src/contracts/task.contract.ts` with zod schemas", not "define API contracts."
7. **Missing trend data** — "historically 0.00" across 2 builds is more alarming than a single bad build, but the urgency isn't conveyed.

## What You Need To Build

Rewrite the skill generation in `skills.py` so that `update_skills_from_build()` produces **sharp, prioritized, actionable** skill content. The injection points in `department.py` and `cli.py` should NOT change — only the content that `update_skills_from_build()` writes to the markdown files.

### Target Output — Coding Department

The coding_dept.md should look something like this (adapt based on actual data):

```markdown
# Coding Department Skills
<!-- Auto-updated by agent-team. Do not edit manually. -->
<!-- Last updated: 2026-04-03T19:21:55Z | Builds analyzed: 2 -->

## CRITICAL — Fix These First (score: 0.00)

### Contract Compliance (0/2 builds passing)
You have NEVER passed this dimension. Before writing ANY route handler:
1. Create a contract file at `src/contracts/{entity}.contract.ts`
2. Define request body, response body, and error response schemas using zod
3. Export a validation middleware that uses the schema
4. Import and use the middleware in the route BEFORE the handler logic
The GATE_TRUTH_SCORE gate WILL fail without contracts.

### Test Presence (0/2 builds passing)
You have NEVER passed this dimension. For EVERY source file you create:
1. Create a corresponding `__tests__/{filename}.test.ts`
2. Include at minimum: 1 happy-path test, 1 error-path test, 1 edge-case test
3. Tests must be runnable with `npm test` — verify before marking complete
Do NOT defer testing to a later phase. Write tests alongside implementation.

## HIGH PRIORITY — Needs Improvement

### Security Patterns (avg 0.25)
- Validate all user input at route boundaries with zod
- Never expose stack traces in error responses (use NODE_ENV check)
- Hash passwords with bcrypt (cost >= 10), never store plaintext
- Use parameterized queries for all DB operations — no string concatenation

### Error Handling (avg 0.58)
- Wrap every async route handler: `router.get('/path', asyncHandler(async (req, res) => { ... }))`
- Create a centralized error handler middleware as the LAST middleware in Express
- Return structured errors: `{ error: string, code: string }` — never raw exceptions

### Requirement Coverage (avg 0.59)
- After coding, re-read the PRD and cross-check every requirement against your implementation
- Create a checklist in REQUIREMENTS.md marking each item as implemented or not

## ON TRACK — Maintain These
- type_safety: 1.00 — keep using TypeScript strict mode
```

### Target Output — Review Department

```markdown
# Review Department Skills
<!-- Auto-updated by agent-team. Do not edit manually. -->
<!-- Last updated: 2026-04-03T19:21:55Z | Builds analyzed: 2 -->

## Hard Rejection Rules (BLOCK merge if violated)
1. **No contracts → REJECT.** Every route must have a zod schema contract. Score: 0.00 across 2 builds.
2. **No tests → REJECT.** Every source file must have a test file. Score: 0.00 across 2 builds.
3. **Raw error exposure → REJECT.** Error responses must use `{ error, code }` format, never stack traces.

## Priority Review Checklist
- [ ] Contract files exist for every entity in `src/contracts/`
- [ ] Test files exist for every source file in `__tests__/`
- [ ] All async route handlers wrapped in error-handling middleware
- [ ] Input validation on every POST/PATCH endpoint
- [ ] No hardcoded secrets (JWT_SECRET must come from env)
- [ ] Every PRD requirement has a corresponding implementation

## Gate Failure Analysis — What To Watch
| Gate | Status | Action Required |
|------|--------|-----------------|
| GATE_ARCHITECTURE | FAIL (2/2) | Ensure REQUIREMENTS.md has Architecture Decision and Integration Roadmap sections |
| GATE_TRUTH_SCORE | FAIL (2/2) | Focus review on contract_compliance and test_presence — these drag the score below threshold |
| GATE_E2E | FAIL (1/2) | Verify E2E test suite runs and all endpoints return expected status codes |

## Trend (2 builds analyzed)
- Overall truth score: 0.46 → 0.44 (declining — quality is getting WORSE, not better)
- contract_compliance: 0.00 → 0.00 (stagnant — this is the #1 priority)
- test_presence: 0.00 → 0.20 (slight improvement, still critical)
```

## Implementation Details

### Files to modify
- **`src/agent_team_v15/skills.py`** — This is the primary file. Rewrite the markdown generation logic in `update_skills_from_build()`.

### Data sources available to you (already passed into the function or readable)
- `AUDIT_REPORT.json` — findings with severity, verdict, file paths, descriptions
- `STATE.json` — truth_scores dict with all 6+ dimensions, gate_results array
- `GATE_AUDIT.log` — chronological gate pass/fail records
- `TRUTH_SCORES.json` — dimension breakdowns
- Previous skill files (for build count, historical averages)

### Constraints
- **Token budget**: Keep each skill file under 550 tokens (~400 words). The current files are well under budget so there's room to add detail, but don't write essays.
- **No new dependencies** — only use Python stdlib
- **Backward compatible** — first build (no prior data) must still produce useful output, not crash
- **Preserve the metadata header** — `<!-- Last updated: ... | Builds analyzed: N -->` format must remain for SK6 counter tracking
- **[SKILL] log prefix** — keep the existing `[SKILL]` print statements

### Severity tiers (use these to categorize dimensions)
- **CRITICAL** (score < 0.10): Never passes. Needs concrete step-by-step instructions with file paths.
- **HIGH** (score 0.10 - 0.50): Rarely passes. Needs specific patterns and examples.
- **MODERATE** (score 0.50 - 0.75): Sometimes passes. Needs reminders and checklists.
- **ON TRACK** (score > 0.75): Usually passes. Brief note to maintain.

### Trend detection
- Compare current build scores to historical averages
- If a dimension is declining, flag it with urgency ("getting WORSE, not better")
- If a dimension improved, acknowledge it ("improved from 0.00 to 0.20, keep pushing")

### Gate failure → action mapping
Build a mapping from gate failures to concrete actions:
- `GATE_ARCHITECTURE` FAIL → "Add Architecture Decision and Integration Roadmap sections to REQUIREMENTS.md"
- `GATE_TRUTH_SCORE` FAIL → "Focus on the weakest dimensions: {list dims below threshold}"
- `GATE_E2E` FAIL → "Ensure E2E test suite runs, all endpoints return expected status codes"
- `GATE_INDEPENDENT_REVIEW` FAIL → "Code changes need review by a different agent than the author"
- etc.

### Review department: hard rejection rules
For any dimension scoring 0.00 across 2+ builds, generate a **hard rejection rule** — not a suggestion, a BLOCK instruction. Frame it as: "No X → REJECT. Do not approve the code."

## Testing

### Verify with existing tests
```bash
cd C:/Projects/agent-team-v15 && python -m pytest tests/test_skills.py -v
```

### Manual verification
After your changes, simulate a skill update and inspect the output:
```python
# Create a temp dir with mock audit data, run update_skills_from_build, read the output files
```

### Check token budget
```bash
wc -w test_run/output2/.agent-team/skills/coding_dept.md  # divide by 0.75, must be < 550
wc -w test_run/output2/.agent-team/skills/review_dept.md   # same
```

### Integration check
The injection points in `department.py` and `cli.py` use `load_skills_for_department()` which just reads the file content. As long as the file is valid markdown, injection works. But verify:
```python
from agent_team_v15.skills import load_skills_for_department
content = load_skills_for_department("test_run/output2/.agent-team/skills", "coding")
print(content)  # should show your new format
```

## Reference Files
- `src/agent_team_v15/skills.py` — the file you're modifying
- `src/agent_team_v15/department.py` — injection point (read-only, don't modify)
- `src/agent_team_v15/cli.py:801-815` — injection point (read-only, don't modify)
- `src/agent_team_v15/hooks.py` — calls update_skills_from_build in post_build
- `test_run/output2/.agent-team/AUDIT_REPORT.json` — real audit data for testing
- `test_run/output2/.agent-team/STATE.json` — real state data
- `test_run/output2/.agent-team/GATE_AUDIT.log` — real gate data
- `test_run/output2/.agent-team/TRUTH_SCORES.json` — real truth scores
- `test_run/VERIFICATION_RESULTS_V3.md` — context on features and what they do
- `HANDOFF_DOCUMENT.md` — full project documentation

## Definition of Done
1. `update_skills_from_build()` produces tiered, actionable skill content (not generic stats)
2. Coding dept skills have: CRITICAL section (step-by-step for 0.00 dims), HIGH PRIORITY section (patterns for <0.50), MODERATE section (checklists for <0.75), ON TRACK section (>0.75)
3. Review dept skills have: hard rejection rules for 0.00 dims, priority checklist, gate failure → action table with trend
4. Token budget respected (<550 tokens per file)
5. Backward compatible (first build works, no prior data = sensible defaults)
6. All existing tests pass + new test cases for the tiered output
7. `[SKILL]` log prefix preserved
8. Build counter (`Builds analyzed: N`) preserved
