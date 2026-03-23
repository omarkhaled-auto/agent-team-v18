# V17 Coordinated Builder System — Design Document

> **Version:** 1.0 | **Date:** 2026-03-20 | **Status:** Implementation Ready
> **Evidence Base:** EVS Customer Portal Run 1 ($62, 84.6%) → Run 2 ($72, 93.5%, zero regressions)

---

## Architecture Overview

```
                    ┌─────────────────────────────────┐
                    │        ORIGINAL PRD              │  ← NEVER CHANGES
                    │    (Source of Truth)              │
                    └──────────┬──────────────────────┘
                               │
                    ┌──────────▼──────────────────────┐
                    │     RUN 1: INITIAL BUILD         │
                    │  Standard pipeline (PRD mode)    │
                    └──────────┬──────────────────────┘
                               │
                    ┌──────────▼──────────────────────┐
              ┌────►│     AUDIT AGENT                  │
              │     │  Reads original PRD + codebase   │
              │     │  Checks every AC + business rule │
              │     │  Produces structured findings    │
              │     └──────────┬──────────────────────┘
              │                │
              │     ┌──────────▼──────────────────────┐
              │     │     CONFIGURATION AGENT          │
              │     │  Evaluates 4 stop conditions     │
              │     │  Circuit breaker check           │
              │     │  Triages findings by severity    │
              │     └──────────┬──────────────────────┘
              │                │
              │          STOP? ◄── YES ──► FINAL REPORT
              │                │
              │               NO
              │                │
              │     ┌──────────▼──────────────────────┐
              │     │     FIX PRD AGENT                │
              │     │  Generates parser-valid fix PRD  │
              │     │  References existing codebase    │
              │     │  Regression prevention section   │
              │     └──────────┬──────────────────────┘
              │                │
              │     ┌──────────▼──────────────────────┐
              │     │     BUILDER (Standard Pipeline)  │
              │     │  PRD mode on fix PRD             │
              │     │  Targets existing code           │
              │     └──────────┬──────────────────────┘
              │                │
              └────────────────┘  Back to AUDIT AGENT
```

**Every run uses PRD mode.** The fix PRD is a complete, parser-valid PRD document that the builder processes through the standard pipeline — parser, contracts, milestones, scans, runtime verification. No special "fix mode." The PRD itself is what makes it targeted.

---

## Agent 1: Audit Agent

### Purpose
Compare the built codebase against the original PRD. Produce structured findings with severity classification for every acceptance criterion, business rule, entity spec, and non-functional requirement.

### Inputs
| Input | Source | Required |
|-------|--------|----------|
| `original_prd_path` | User-provided | Yes |
| `codebase_path` | Build output directory | Yes |
| `previous_report` | Previous run's AuditReport | No (None for Run 1) |
| `config` | Audit configuration dict | No (defaults) |

### Methodology — Three-Tier Inspection

**Tier 1: Static Checks (grep/file-based, ~30% of ACs)**
- File existence: "Has a Dockerfile" → `Path(codebase / "Dockerfile").exists()`
- String presence: "uses httpOnly cookie" → grep for `httpOnly` in auth code
- Constant values: "expires after 15 minutes" → grep for `15 * 60`, `900`, `'15m'`
- Import checks: "uses bcrypt" → grep for `import.*bcrypt`
- Entity field presence: check schema/model files for field names
- **Cost:** $0 (no API calls)

**Tier 2: Claude-Assisted Behavioral Checks (~50% of ACs)**
- Logic flow verification: send relevant code + AC to Claude Sonnet
- State transition checks: send state machine code + transition AC
- Business rule verification: send calculation logic + rule spec
- Error handling: send validation code + error AC
- **Cost:** ~$0.003 per check × 50 checks = ~$0.15

**Tier 3: Classification Only (~20% of ACs)**
- Runtime performance: "loads in < 2 seconds" → `REQUIRES_HUMAN`
- Visual/UX: "responsive design" → `REQUIRES_HUMAN`
- External integration: "syncs with Odoo" → `REQUIRES_HUMAN`
- **Cost:** $0

**Cross-Cutting Review (one Claude call after all individual checks)**
- Catches middleware wiring gaps, relationship errors, pattern inconsistencies
- Sends: findings summary + codebase structure + key files (entry point, routes, schema)
- **Cost:** ~$0.015

**Total audit cost: ~$0.20–$0.35**

### AC Extraction from PRD

Multi-pattern regex extraction:
```python
AC_PATTERNS = [
    r'- \[[ x]\]\s*AC[-\s]?(\d+)\s*:\s*(.+?)(?=\n- \[|\n\n|\n#|\Z)',   # checkbox
    r'\*\*AC[-\s]?(\d+):\*\*\s*(.+?)(?=\n\*\*AC|\n\n|\n#|\Z)',          # bold
    r'(?:^|\n)AC[-\s]?(\d+)\s*:\s*(.+?)(?=\nAC[-\s]?\d+|\n\n|\n#|\Z)',  # plain
    r'Acceptance\s+Criter(?:ion|ia)\s+(\d+)\s*:\s*(.+?)(?=\nAcceptance|\n\n|\n#|\Z)',
]
```

Each AC is associated with its parent feature via heading tracking:
```python
FEATURE_PATTERNS = [
    r'#{2,3}\s+(?:Feature\s+)?F[-\s]?(\d+)',
    r'#{2,3}\s+(F-\d+)',
]
```

### Code Inspection Strategy

For behavioral checks, the audit agent finds relevant code via:
1. **Keyword extraction** from AC text (entity names, action words, quoted terms)
2. **File discovery** via grep (find files containing keywords)
3. **Section extraction** (extract enclosing function/class, capped at 200 lines)
4. **Claude evaluation** (AC + relevant code → PASS/FAIL/PARTIAL with evidence)

### Severity Classification Rules

| Severity | When Applied | Examples |
|----------|-------------|---------|
| `CRITICAL` | Security vulnerability, data loss risk, complete feature missing | No auth on protected endpoint, missing migration |
| `HIGH` | Feature partially working, wrong behavior, significant deviation | Endpoint exists but wrong validation, missing state transition |
| `MEDIUM` | Minor logic errors, missing edge cases, wrong constants | Off-by-one, wrong default value, naming mismatch |
| `LOW` | Cosmetic, suboptimal patterns, extra features | Styling differences, minor naming conventions |
| `ACCEPTABLE_DEVIATION` | Builder made a better choice than PRD | Used modern pattern instead of PRD's specific approach |
| `REQUIRES_HUMAN` | Needs external systems or business judgment | External API testing, visual evaluation, performance benchmarks |

**Preventing Leniency:** Default to FAIL unless Claude explicitly says PASS with file:line evidence.
**Preventing Strictness:** Allow ACCEPTABLE_DEVIATION; group micro-findings into single findings.

### Output Format

```python
@dataclass
class AuditReport:
    run_number: int
    timestamp: str
    original_prd_path: str
    codebase_path: str
    total_acs: int                      # All ACs extracted from PRD
    passed_acs: int                     # PASS verdict
    failed_acs: int                     # FAIL verdict
    partial_acs: int                    # PARTIAL verdict (counted as 0.5)
    skipped_acs: int                    # REQUIRES_HUMAN (excluded from score)
    score: float                        # (passed + 0.5*partial) / (total - skipped) × 100
    findings: list[Finding]
    previously_passing: list[str]       # AC IDs that passed in previous run
    regressions: list[str]              # AC IDs that regressed (passed→failed)
    audit_cost: float                   # Claude API cost for this audit
```

---

## Agent 2: Configuration Agent

### Purpose
Evaluate stop conditions, calculate scores, detect regressions, triage findings by severity and budget, decide whether to STOP or CONTINUE.

### Inputs
| Input | Source | Required |
|-------|--------|----------|
| `state` | LoopState (cross-run tracking) | Yes |
| `current_report` | AuditReport from latest audit | Yes |

### Stop Condition Evaluation

**Evaluated in order (first triggered wins):**

#### Condition 1: Convergence
```
IF len(runs) >= 2
   AND (current_score - previous_score) < min_improvement_threshold  (default: 3%)
   AND critical_count == 0
   AND high_count == 0
THEN STOP("CONVERGED")
```

#### Condition 2: Zero Actionable
```
IF actionable_count == 0  (where actionable = CRITICAL + HIGH + MEDIUM)
THEN STOP("COMPLETE")
```

#### Condition 3: Budget Exhausted
```
IF total_cost >= initial_build_cost × 3
THEN STOP("BUDGET")
```

#### Condition 4: Max Iterations
```
IF current_run >= max_iterations  (default: 4)
THEN STOP("MAX_ITERATIONS")
```

### Circuit Breaker (3 Levels)

| Level | Condition | Action |
|-------|-----------|--------|
| L1 (WARNING) | Score dropped from previous run | Log warning, continue |
| L2 (STOP) | Score dropped in 2 consecutive runs | STOP("OSCILLATING") |
| L3 (STOP) | Single run: regression count > fix count | STOP("REGRESSION_SPIRAL") |

### Finding Triage

Priority order for fix run inclusion:
1. All CRITICAL findings (always included)
2. All HIGH findings (included if budget allows)
3. MEDIUM CODE_FIX and MISSING_FEATURE findings (budget permitting)
4. MEDIUM TEST_GAP and PERFORMANCE findings (deferred unless budget surplus)
5. LOW, ACCEPTABLE_DEVIATION, REQUIRES_HUMAN → always deferred

**Batching strategy:** Group by FEATURE, prioritize features containing CRITICAL findings.

**Cap:** Maximum 15 findings per fix PRD (prevents context window overflow).

### Score Calculation

```
score = (passed_count + 0.5 × partial_count) / (total_acs - skipped_count) × 100
```

Where `skipped_count` = REQUIRES_HUMAN ACs (excluded from denominator since they can't be evaluated).

### Cost Estimation

```python
BASE_COST = {
    "code_fix": 3.0, "missing_feature": 8.0, "security": 5.0,
    "test_gap": 3.0, "regression": 5.0, "performance": 5.0, "ux": 5.0
}
EFFORT_MULTIPLIER = {"trivial": 0.5, "small": 1.0, "medium": 1.5, "large": 2.5}

estimated_cost = sum(
    BASE_COST[f.category] * EFFORT_MULTIPLIER[f.estimated_effort]
    for f in findings
)
```

### Output

```python
@dataclass
class LoopDecision:
    action: str             # "STOP" or "CONTINUE"
    reason: str             # Human-readable explanation
    findings_for_fix: list  # Scoped findings for PRD agent
    deferred_findings: list # Findings deferred to human/future
    estimated_cost: float   # Estimated cost of fix run
    run_number: int         # Which run this decision is for
```

---

## Agent 3: PRD Agent (Fix Mode)

### Purpose
Generate a parser-valid fix PRD from structured audit findings. The fix PRD is processed by the standard builder pipeline — no special mode needed.

### Inputs
| Input | Source | Required |
|-------|--------|----------|
| `original_prd_path` | User-provided | Yes |
| `codebase_path` | Build output directory | Yes |
| `findings` | Scoped findings from config agent | Yes |
| `run_number` | Current run number | Yes |
| `previous_passing_acs` | ACs that passed in previous audit | Yes |

### Fix PRD Structure

```markdown
# Project: {Original Project Name} — Fix Run {N}

## Product Overview
TARGETED FIX RUN for {project name}.
Existing codebase: {codebase_path}
Original PRD (source of truth): {original_prd_path}
This fix run addresses {count} findings from the post-build audit.
ALL existing functionality MUST be preserved.
Only items listed below should be modified.

## Technology Stack
{VERBATIM COPY from original PRD — required for parser}

## Existing Context (DO NOT REGENERATE)
The following entities exist and are working correctly:
| Entity | Key Fields | Status |
| User | id, email, name, role | Working — DO NOT MODIFY |
| Invoice | id, number, amount, status | Working — DO NOT MODIFY |
...

## Entities (TO MODIFY/CREATE)
| Entity | Field | Type | Notes |
| InvoiceLineItem | unit_price | decimal(10,2) | FIX: Change from integer |
| NewEntity | field1 | type | NEW entity |

## State Machines
{ONLY for modified/new entities, same format as original PRD}

## Events
{ONLY new events being added}

## Bounded Contexts

### {Service Name}
Entities: {list}
Responsibilities:

**FIX-001: {Title}** [SEVERITY: {severity}]
Current code at `{file_path}:{line_number}`:
```{language}
{current_code_snippet}
```
Required change: {description}
PRD specification: {exact text from original PRD}
Test requirement: {what test verifies this fix}

**FEAT-001: {Title}** [NEW FEATURE]
{Full specification copied from original PRD}
PRD reference: {section and AC numbers}
Test requirements:
- {test 1}
- {test 2}

## Regression Prevention
DO NOT modify any file not listed in this PRD.
The following {N} acceptance criteria passed in the previous run and MUST still pass:
{numbered list of previously passing AC IDs and their text}
Run ALL existing tests before and after changes.
Zero regressions allowed.

## Success Criteria
1. FIX-001: {testable success criterion}
2. FEAT-001: {testable success criterion}
...
N. ALL {count} previously passing ACs still pass (regression check)
```

### Entity Handling

**Strategy: Include ALL entities but in different sections.**
- "Existing Context" section: ALL unchanged entities in brief table format → parser extracts them for relationship awareness
- "Entities" section: ONLY modified/new entities in full detail → parser extracts them for code generation
- Prose clearly instructs builder: "DO NOT REGENERATE" existing entities

### Regression Prevention Mechanism

5-layer defense:
1. **Fix PRD language:** Explicit "DO NOT MODIFY" instructions, file scoping
2. **Git snapshot:** `git commit` before each fix run (structural safety)
3. **Previously passing ACs:** Listed in Success Criteria with "MUST STILL PASS"
4. **Current code context:** Surgical code snippets showing exactly what to change
5. **Post-fix audit:** Next audit cycle catches any regressions

### Parser Compatibility

After generation, the fix PRD agent validates:
```python
parsed = parse_prd(fix_prd_text)
assert parsed.project_name != ""          # Has a title
assert len(parsed.technology_hints) > 0   # Has tech stack
# Entities may be empty if fix is pure logic change — OK
```

If validation fails: regenerate with adjusted formatting (max 2 retries).

### Codebase Reference

The fix PRD agent reads the codebase to:
- Find current code snippets for each finding's file_path/line_number
- List project structure for the "Existing Context" section
- Identify which entities exist (from schema/model files)

### Output
A parser-valid markdown file saved to `.agent-team/fix_prd_run{N}.md`.

---

## Orchestrator

### Purpose
Run the complete audit-fix loop. Manage state across runs. Invoke builder, audit, config, and PRD agents in sequence.

### State Management

**Separate state file:** `.agent-team/coordinated_state.json`

The orchestrator does NOT modify the builder's STATE.json. Each builder run creates/overwrites its own STATE.json. The orchestrator archives each run's STATE.json and maintains its own cross-run state.

```json
{
    "schema_version": 1,
    "original_prd_path": "/path/to/original.md",
    "codebase_path": "/path/to/output",
    "config": {
        "max_budget": 300.0,
        "max_iterations": 4,
        "min_improvement": 3.0
    },
    "runs": [
        {
            "run_number": 1,
            "type": "initial",
            "prd_path": "/path/to/original.md",
            "cost": 62.0,
            "audit": {
                "score": 84.6,
                "total_acs": 103,
                "passed_acs": 78,
                "partial_acs": 10,
                "failed_acs": 15,
                "skipped_acs": 0,
                "critical": 2,
                "high": 8,
                "medium": 12,
                "regressions": 0
            },
            "audit_report_path": ".agent-team/audit_run1.json",
            "state_archive_path": ".agent-team/STATE.json.run1",
            "timestamp": "2026-03-20T10:00:00Z"
        }
    ],
    "total_cost": 62.0,
    "current_run": 1,
    "status": "running",
    "stop_reason": null
}
```

### File Organization

```
{output_dir}/
├── .agent-team/
│   ├── coordinated_state.json       # Cross-run loop state
│   ├── audit_run1.json              # Audit report after Run 1
│   ├── audit_run2.json              # Audit report after Run 2
│   ├── audit_run3.json              # Audit report after Run 3
│   ├── fix_prd_run2.md              # Fix PRD for Run 2
│   ├── fix_prd_run3.md              # Fix PRD for Run 3
│   ├── STATE.json                   # Current/latest builder state
│   ├── STATE.json.run1              # Archived: Run 1 state
│   ├── STATE.json.run2              # Archived: Run 2 state
│   ├── MASTER_PLAN.md               # Current builder milestone plan
│   ├── FINAL_REPORT.md              # Summary of all runs
│   └── milestones/                  # Per-milestone data
├── src/                             # Generated source code
├── tests/                           # Generated tests
└── CONTRACTS.md                     # Service contracts
```

### CLI Interface

```bash
# Full coordinated build (initial + audit-fix loop)
python -m agent_team_v15 coordinated-build \
    --prd "path/to/prd.md" \
    --cwd "path/to/output" \
    --max-budget 300 \
    --max-iterations 4 \
    --depth exhaustive

# Just run the audit (standalone)
python -m agent_team_v15 audit \
    --prd "path/to/original_prd.md" \
    --cwd "path/to/existing_build" \
    --output "audit_report.json"

# Just generate a fix PRD from an audit report
python -m agent_team_v15 generate-fix-prd \
    --prd "path/to/original_prd.md" \
    --cwd "path/to/existing_build" \
    --audit-report "audit_report.json" \
    --output "fix_prd.md"
```

### Error Handling

| Failure | Action |
|---------|--------|
| Builder subprocess crashes | Record failed run, STOP with "BUILDER_FAILURE" |
| Audit agent crashes | Retry once, then STOP with "AUDIT_FAILURE" |
| Fix PRD generation fails | STOP with "PRD_GENERATION_FAILURE" |
| Budget exceeded mid-run | Complete run, then STOP (budget checked post-run) |
| Git operations fail | Continue without git safety net, log warning |

```python
class CoordinatedBuildError(Exception): ...
class BuilderRunError(CoordinatedBuildError): ...
class AuditError(CoordinatedBuildError): ...
class PRDGenerationError(CoordinatedBuildError): ...
```

### Builder Invocation

The orchestrator calls the builder as a **subprocess** for clean isolation:
```python
cmd = [sys.executable, "-m", "agent_team_v15",
       "--prd", str(prd_path), "--cwd", str(cwd),
       "--depth", depth, "--no-interview"]
result = subprocess.run(cmd, capture_output=True, text=True)
state = load_state(str(cwd / ".agent-team"))
cost = state.total_cost if state else 0.0
```

Before each run: archive previous STATE.json, clean state for fresh start.

---

## Regression Prevention Strategy

### Layer 1: Fix PRD Language
- "DO NOT MODIFY" instructions for unchanged files
- Explicit file scoping: "Modify ONLY these files: {list}"
- Effectiveness: ~80% (prompt-based, not structurally enforced)

### Layer 2: Git Snapshot
- `git add -A && git commit -m "pre-fix-run-{N}"` before each fix run
- `git diff HEAD~1 --stat` after run to see what changed
- Rollback via `git revert` if catastrophic regression detected
- Effectiveness: 100% detectable, 100% recoverable

### Layer 3: Previously Passing AC List
- Fix PRD's Success Criteria lists ALL previously passing ACs
- Builder's test-engineer milestone verifies them
- Effectiveness: depends on builder's diligence, ~70%

### Layer 4: Surgical Code Context
- Fix PRD includes current code snippets + specific change descriptions
- Prevents builder from rewriting entire files for small changes
- Effectiveness: ~85% for CODE_FIX, N/A for MISSING_FEATURE

### Layer 5: Post-Fix Audit
- Next audit cycle explicitly checks every previously passing AC
- Regressions are flagged with REGRESSION category
- Circuit breaker stops if regressions > fixes
- Effectiveness: 100% detection (the audit runs on the actual code)

### Combined Effectiveness
No single layer is 100% preventive. Together they provide:
- **Prevention:** Layers 1, 3, 4 (~90% of regressions prevented)
- **Detection:** Layers 2, 5 (100% of regressions detected)
- **Recovery:** Layer 2 (git rollback available)

EVS Run 2 achieved zero regressions with only Layer 1. Layers 2–5 add defense in depth.

---

## Stop Conditions — Detailed Logic

### Condition 1: Convergence
```python
if len(runs) >= 2:
    improvement = current_score - runs[-1].score
    if improvement < 3.0 and critical_count == 0 and high_count == 0:
        STOP("CONVERGED: {improvement:.1f}% improvement, zero CRITICAL/HIGH")
```

### Condition 2: Zero Actionable
```python
actionable = sum(1 for f in findings if f.severity in (CRITICAL, HIGH, MEDIUM))
if actionable == 0:
    STOP("COMPLETE: Zero actionable findings")
```

### Condition 3: Budget
```python
initial_cost = runs[0].cost
budget_cap = initial_cost * 3
if total_cost >= budget_cap:
    STOP("BUDGET: ${total_cost:.2f} ≥ ${budget_cap:.2f}")
```

### Condition 4: Max Iterations
```python
if current_run >= max_iterations:  # default 4
    STOP("MAX_ITERATIONS: {current_run} runs")
```

### Circuit Breaker
```python
# Level 1: Score dropped
if len(runs) >= 2 and current_score < runs[-1].score:
    WARNING("Score dropped from {runs[-1].score} to {current_score}")

# Level 2: Consecutive drops
if len(runs) >= 3 and runs[-1].score < runs[-2].score and current_score < runs[-1].score:
    STOP("OSCILLATING: 2 consecutive score drops")

# Level 3: Regression spiral
if len(regressions) > 0 and len(regressions) > new_fixes_count:
    STOP("REGRESSION_SPIRAL: {len(regressions)} regressions > {new_fixes_count} fixes")
```

---

## State Schema

### CoordinatedState (coordinated_state.json)
```json
{
    "schema_version": 1,
    "original_prd_path": "string",
    "codebase_path": "string",
    "config": {
        "max_budget": "float",
        "max_iterations": "int",
        "min_improvement": "float",
        "depth": "string",
        "audit_model": "string"
    },
    "runs": [
        {
            "run_number": "int",
            "type": "initial | fix",
            "prd_path": "string",
            "cost": "float",
            "audit": {
                "score": "float",
                "total_acs": "int",
                "passed_acs": "int",
                "partial_acs": "int",
                "failed_acs": "int",
                "skipped_acs": "int",
                "critical": "int",
                "high": "int",
                "medium": "int",
                "regressions": "int"
            },
            "audit_report_path": "string",
            "fix_prd_path": "string | null",
            "state_archive_path": "string",
            "timestamp": "ISO 8601"
        }
    ],
    "total_cost": "float",
    "current_run": "int",
    "status": "running | converged | stopped | failed",
    "stop_reason": "string | null"
}
```

### Finding (audit report)
```json
{
    "id": "F001-AC10",
    "feature": "F-001",
    "acceptance_criterion": "AC text from PRD",
    "severity": "critical | high | medium | low | acceptable_deviation | requires_human",
    "category": "code_fix | missing_feature | security | regression | test_gap | performance | ux",
    "title": "Short description",
    "description": "Detailed description",
    "prd_reference": "Section/line reference",
    "current_behavior": "What code does now",
    "expected_behavior": "What PRD says",
    "file_path": "string | null",
    "line_number": "int | null",
    "code_snippet": "string | null",
    "fix_suggestion": "What needs to change",
    "estimated_effort": "trivial | small | medium | large",
    "test_requirement": "string | null"
}
```

---

## Estimated Implementation

### Files to Create/Modify

| File | Lines | Purpose |
|------|-------|---------|
| `src/agent_team_v15/audit_agent.py` | ~500 | Audit agent (AC extraction, inspection, findings) |
| `src/agent_team_v15/config_agent.py` | ~250 | Configuration agent (stop conditions, triage) |
| `src/agent_team_v15/fix_prd_agent.py` | ~400 | Fix PRD generator (template + Claude) |
| `src/agent_team_v15/coordinated_builder.py` | ~300 | Orchestrator (the loop) |
| `src/agent_team_v15/cli.py` | ~100 (additions) | New subcommands |
| `tests/test_audit_agent.py` | ~300 | Audit agent tests |
| `tests/test_config_agent.py` | ~150 | Config agent tests |
| `tests/test_fix_prd_agent.py` | ~200 | Fix PRD agent tests |
| `tests/test_coordinated_builder.py` | ~200 | Orchestrator tests |
| **Total** | **~2,400** | |

### Dependencies
- `anthropic` SDK (for Claude Sonnet calls in audit + fix PRD agents)
- Existing: `parse_prd()`, `ParsedPRD`, `RunState`, `load_state()`, `save_state()`
- Existing: `Violation` dataclass (for severity context from quality checks)
- Standard library: `subprocess`, `json`, `re`, `pathlib`, `dataclasses`
- Optional: `git` (for regression snapshots)

### Test Plan
1. **Unit: Audit Agent** — AC extraction on sample PRDs, static check on known codebases, mock Claude for behavioral checks
2. **Unit: Config Agent** — Synthetic audit reports → verify stop conditions, budget calculation, triage logic
3. **Unit: Fix PRD Agent** — Sample findings → verify parser-valid output, entity handling, regression section
4. **Integration: EVS Replay** — Run audit on EVS Run 1 output, verify findings match manual audit
5. **Integration: Parser Compatibility** — Run `parse_prd()` on generated fix PRDs, verify extraction
6. **Stop Condition Matrix** — All 4 conditions + 3 circuit breaker levels with edge cases

---

## User Guide

### Quick Start
```bash
# 1. Write your PRD
# 2. Run coordinated build
python -m agent_team_v15 coordinated-build --prd my_app.md --cwd ./output

# 3. Wait for convergence (2-4 runs, 1-6 hours)
# 4. Read final report
cat ./output/.agent-team/FINAL_REPORT.md
```

### How It Works
The system builds your application, audits it against your PRD, generates a fix PRD for any gaps, rebuilds, re-audits, and repeats — until the application is production-ready or a stop condition is met. No human in the loop between runs.

### Configuration
| Flag | Default | Description |
|------|---------|-------------|
| `--max-budget` | 3× initial cost | Maximum total spend |
| `--max-iterations` | 4 | Maximum runs (1 initial + 3 fix) |
| `--depth` | exhaustive | Build depth |
| `--min-improvement` | 3% | Minimum score improvement to continue |

### Stop Conditions
1. **Convergence:** Score improved < 3% with zero CRITICAL/HIGH
2. **Complete:** Zero actionable findings remain
3. **Budget:** Total spend exceeds cap
4. **Max Iterations:** 4 runs completed
5. **Circuit Breaker:** Regressions exceed fixes, or score drops 2 consecutive runs

### Output Artifacts
| Artifact | Description |
|----------|-------------|
| `.agent-team/audit_run{N}.json` | Structured findings per run |
| `.agent-team/fix_prd_run{N}.md` | Fix PRD per run |
| `.agent-team/coordinated_state.json` | Cross-run state |
| `.agent-team/FINAL_REPORT.md` | Summary with before/after |
