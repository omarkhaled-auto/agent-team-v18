# Audit-Team Review System Design

## 1. Current System Investigation

### 1.1 Review Flow

The current review system is embedded inside the orchestrator's convergence loop (agents.py Section 3, lines 160-238). The flow is:

1. **Coding Fleet** writes code against TASKS.md assignments
2. **Review Fleet** (code-reviewer agents) adversarially checks REQUIREMENTS.md items, marks `[x]`/`[ ]`, increments `(review_cycles: N)`
3. **Convergence Check**: orchestrator re-reads REQUIREMENTS.md -- all `[x]`? proceed to testing. Otherwise check escalation thresholds.
4. **Debugger Fleet** fixes specific issues from the Review Log
5. **Re-review** (GATE 2: mandatory after every debug fix)
6. **Escalation** (GATE 5): items with `review_cycles >= escalation_threshold` get sent back to Planning + Research
7. **Testing Fleet** writes/runs tests, marks testing items `[x]`
8. **Security Audit** (if applicable)
9. **Final Check**: all `[x]`? report COMPLETION

The review fleet uses a single agent type: `code-reviewer` (CODE_REVIEWER_PROMPT, agents.py:1218). This one prompt covers functional verification, wiring verification (WIRE-xxx), service-to-API verification (SVC-xxx), API field contracts (API-001 through API-004), UI compliance, seed data, enum verification, orphan detection, and silent data loss checks (SDL-001/002/003).

### 1.2 Convergence Gates

Five hard gates enforced by the orchestrator prompt and Python runtime:

| Gate | Rule | Enforcement |
|------|------|-------------|
| GATE 1 | Only review/test fleets mark `[x]` | Prompt-enforced |
| GATE 2 | Debug -> Re-Review is mandatory | Prompt-enforced |
| GATE 3 | review_cycles must increment every cycle | Prompt + Python (cli.py:5137-5144) |
| GATE 4 | Depth controls fleet size, not thoroughness | Prompt-enforced |
| GATE 5 | review_cycles == 0 triggers forced recovery | Python-enforced (cli.py:5216-5232) |

State is tracked via:
- `ConvergenceReport` (state.py:76): `total_requirements`, `checked_requirements`, `review_cycles`, `convergence_ratio`, `health`
- REQUIREMENTS.md: per-item `(review_cycles: N)` markers
- Review Log table in REQUIREMENTS.md: per-item per-cycle verdicts

### 1.3 State Management

**Per-milestone flow** (cli.py:1370-1449):
1. Milestone executes via sub-orchestrator session
2. `check_milestone_health()` runs after execution
3. If health is "failed" or "degraded": triggers review recovery loop
4. Recovery retries controlled by `config.milestone.review_recovery_retries`
5. After recovery: generates MILESTONE_HANDOFF.md, runs wiring check

**Post-orchestration flow** (cli.py:5120-5298):
1. Parse convergence report from REQUIREMENTS.md
2. Check health: healthy/degraded/failed/unknown
3. GATE 5 enforcement: force review if `review_cycles == 0`
4. Run `_run_review_only()` recovery pass if needed (cli.py:3657-3751)
5. Re-check health after recovery, adjust counters if LLM didn't update markers
6. Post-orchestration scans: mock data, UI compliance, API contracts, SDL, endpoint xref

**State persistence**: `STATE.json` tracks `completed_phases`, `total_cost`, `convergence_cycles`, `requirements_checked`. Milestone status persists in MASTER_PLAN.md.

### 1.4 Limitations

**L1 -- Single reviewer role covers too much scope.** CODE_REVIEWER_PROMPT (agents.py:1218-1417) is ~200 lines and asks one agent to verify: functional requirements, wiring, SVC contracts, API field schemas, UI compliance, seed data, enums, orphans, and SDL patterns. A single agent cannot thoroughly cover all of these in one pass.

**L2 -- No structured finding model.** Findings are free-text entries in a Markdown Review Log table. There is no machine-parseable severity, no file:line evidence in a structured format, and no scoring. The orchestrator must re-read Markdown to determine what failed.

**L3 -- No parallel specialization.** All reviewers run the same prompt. There is no division of labor -- every reviewer checks everything, leading to duplicate work on easy items and insufficient depth on hard items.

**L4 -- Test verification is separate from review.** Test-runner agents run after the review loop completes (step 6 in the convergence loop). Test failures discovered late cause expensive re-loops. Tests should be part of the audit, not a separate phase.

**L5 -- No MCP/library verification.** Context7 is only available to the orchestrator. The current system has no mechanism to verify that third-party API usage matches documentation. Incorrect library usage (wrong method signatures, deprecated APIs) is not caught.

**L6 -- Binary pass/fail with no scoring.** Requirements are either `[x]` or `[ ]`. There is no partial credit, no severity classification, and no way to prioritize which failures to fix first.

**L7 -- Fix dispatch is coarse-grained.** The debugger fleet gets "all failing items from the Review Log" with no grouping by file, no conflict avoidance, and no severity-based prioritization.

**L8 -- Re-audit scope is too broad.** After fixes, the entire review fleet re-runs on everything. There is no mechanism to re-audit only changed areas.

---

## 2. New System Design

### 2.1 Architecture Overview

The audit-team replaces Step 2 (Review Fleet) in the convergence loop. The convergence loop structure remains:

```
Code -> AUDIT-TEAM -> Debug -> Re-AUDIT -> ... -> Test -> Complete
```

The audit-team itself is a 4-step sub-pipeline:

```
Step 1: Parallel Auditors (5 specialized agents)
         |
Step 2: Scorer Agent (collects, deduplicates, scores)
         |
Step 3: Fix Dispatch (orchestrator groups fixes, deploys debuggers)
         |
Step 4: Re-audit (targeted, only changed areas)
```

**Key constraint**: Sub-agents do NOT have MCP access. The orchestrator must pre-fetch any Context7/Firecrawl data and inject it into auditor context. The MCP/Library auditor's Context7 queries are performed by the orchestrator before that auditor is deployed.

### 2.2 Auditor Agents

Five specialized auditors run in parallel (Step 1). Each produces a list of `AuditFinding` objects.

#### 2.2.1 Requirements Auditor

**Purpose**: Verify every functional requirement (REQ-xxx) in REQUIREMENTS.md against actual code.

**Scope**:
- Functional requirements (REQ-xxx)
- Design requirements (DESIGN-xxx)
- Seed data verification (SEED-001/002/003)
- Enum/status registry verification (ENUM-001/002/003/004)

**Input**: REQUIREMENTS.md, codebase access, original user request text

**Process**:
1. Parse all REQ-xxx and DESIGN-xxx items from REQUIREMENTS.md
2. For each item: locate implementation, verify correctness, check edge cases
3. Cross-check against original user request for omissions
4. Produce AuditFinding per item with PASS/FAIL/PARTIAL verdict

**Prompt size**: ~80 lines (down from current 200-line combined prompt)

#### 2.2.2 Technical Auditor

**Purpose**: Verify technical requirements, patterns, conventions, types, defaults.

**Scope**:
- Technical requirements (TECH-xxx)
- Architecture compliance
- Code quality patterns (FRONT-xxx, BACK-xxx, SLOP-xxx)
- Silent data loss (SDL-001/002/003)
- Production readiness (TECH-xxx production defaults)

**Input**: REQUIREMENTS.md (Architecture Decision section), codebase access

**Process**:
1. Parse all TECH-xxx items
2. Verify each against codebase: correct patterns, types, conventions
3. Run SDL-001/002/003 checks on command handlers and response chains
4. Check anti-patterns from code quality standards
5. Produce AuditFinding per item

#### 2.2.3 Interface Auditor

**Purpose**: Verify wiring, integration contracts, API field schemas, security requirements.

**Scope**:
- Wiring requirements (WIRE-xxx)
- Service-to-API wiring (SVC-xxx)
- API field contracts (API-001/002/003/004)
- Endpoint cross-reference (XREF-001/002)
- Orphan detection
- Security requirements (SEC-xxx from SECURITY_AUDITOR findings)

**Input**: REQUIREMENTS.md (Integration Roadmap, Wiring Map), codebase access

**Process**:
1. Parse all WIRE-xxx and SVC-xxx items
2. Trace each wiring path from entry point to feature
3. For SVC-xxx: verify real HTTP calls (no mock data), URL matches, DTO field alignment
4. Run orphan detection sweep on new files
5. Produce AuditFinding per item

#### 2.2.4 Test Auditor

**Purpose**: Verify test coverage, run tests, enforce minimum test counts.

**Scope**:
- Test requirements (TEST-xxx)
- Test quality (TEST-001 through TEST-015)
- Test count thresholds
- Integration test coverage for WIRE-xxx items

**Input**: REQUIREMENTS.md, codebase access, test framework config

**Process**:
1. Run project tests via detected test command
2. Parse results: pass/fail counts, coverage if available
3. Verify minimum test count from REQUIREMENTS.md
4. Check test quality: assertions per test, no skips, no empty tests
5. Verify integration tests exist for each WIRE-xxx item
6. Produce AuditFinding per test-related item

#### 2.2.5 MCP/Library Auditor

**Purpose**: Verify third-party API usage matches documentation.

**Scope**:
- Library API correctness (method signatures, parameter types)
- Deprecated API detection
- Version compatibility
- Framework best practices

**Input**: REQUIREMENTS.md (Research Findings section), tech research summary (injected by orchestrator from Context7 pre-fetch), codebase access

**Process**:
1. Orchestrator pre-fetches Context7 docs for detected technologies BEFORE deploying this auditor
2. Auditor receives library documentation as context injection
3. Cross-reference code usage against documentation: correct method names, parameter order, return types
4. Flag deprecated APIs, incorrect patterns, version mismatches
5. Produce AuditFinding per library issue found

**Token budget note**: This auditor receives the largest context injection (~6000 chars of tech research). Limit to top 5 technologies by code usage frequency.

### 2.3 Finding Data Model

```python
@dataclass
class AuditFinding:
    """A single audit finding from any auditor."""

    finding_id: str          # AUTO-generated: "{auditor_prefix}-{seq}" e.g. "REQ-A-001"
    auditor: str             # "requirements" | "technical" | "interface" | "test" | "mcp_library"
    requirement_id: str      # Parent requirement: "REQ-001", "WIRE-003", etc. or "GENERAL" for non-requirement findings
    verdict: str             # "PASS" | "FAIL" | "PARTIAL"
    severity: str            # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO"
    summary: str             # One-line description
    evidence: list[str]      # List of "file:line — description" strings
    remediation: str         # Suggested fix (for FAIL/PARTIAL)
    confidence: float        # 0.0-1.0 -- auditor's confidence in the finding
```

**Severity definitions**:
- **CRITICAL**: Blocks deployment. Data loss, security vulnerability, core functionality broken.
- **HIGH**: Must fix before release. Wrong behavior, missing validation, broken wiring.
- **MEDIUM**: Should fix. Suboptimal patterns, missing edge cases, incomplete error handling.
- **LOW**: Nice to fix. Style violations, minor quality issues.
- **INFO**: Observation only. Suggestions, notes for future work.

**Auditor prefix mapping** (for finding_id generation):
| Auditor | Prefix |
|---------|--------|
| Requirements | RA |
| Technical | TA |
| Interface | IA |
| Test | XA |
| MCP/Library | MA |

### 2.4 Scoring System

The scorer agent collects all findings from the 5 auditors and produces an `AuditReport`.

```python
@dataclass
class AuditScore:
    """Computed score for an audit run."""

    total_items: int          # Total requirements + technical items audited
    passed: int               # Items with PASS verdict
    failed: int               # Items with FAIL verdict
    partial: int              # Items with PARTIAL verdict

    critical_count: int       # CRITICAL severity findings
    high_count: int           # HIGH severity findings
    medium_count: int         # MEDIUM severity findings
    low_count: int            # LOW severity findings
    info_count: int           # INFO severity findings

    score: float              # Weighted score: 0-100
    health: str               # "healthy" | "degraded" | "failed"

    # Weighted score formula:
    # score = (passed * 100 + partial * 50) / total_items
    # health thresholds:
    #   score >= 90 AND critical_count == 0 -> "healthy"
    #   score >= 70 AND critical_count == 0 -> "degraded"
    #   else -> "failed"


@dataclass
class AuditReport:
    """Complete audit report from scorer agent."""

    audit_id: str                        # Unique ID for this audit run
    timestamp: str                       # ISO 8601
    auditors_deployed: list[str]         # Which auditors ran
    findings: list[AuditFinding]         # All findings, deduplicated
    score: AuditScore                    # Computed score

    # Grouped views for fix dispatch
    by_severity: dict[str, list[AuditFinding]]  # Grouped by severity
    by_file: dict[str, list[AuditFinding]]      # Grouped by primary file
    by_requirement: dict[str, list[AuditFinding]]  # Grouped by requirement_id

    fix_candidates: list[AuditFinding]   # CRITICAL + HIGH + MEDIUM findings (ordered by severity)
```

**Deduplication rules** (scorer responsibility):
1. If two auditors flag the same requirement_id with the same verdict, keep the one with higher confidence
2. If two auditors flag the same file:line, merge evidence lists
3. Never deduplicate across different requirement_ids (same file can fail for different reasons)

**Score computation**:
```
weighted_score = (passed * 100 + partial * 50) / max(total_items, 1)
```

### 2.5 Fix Dispatch Algorithm

The orchestrator reads the scorer's `AuditReport` and dispatches fix agents. This replaces the current "deploy debugger fleet for all failing items" approach.

**Algorithm**:

```
1. Filter fix_candidates: only CRITICAL, HIGH, MEDIUM findings (skip LOW, INFO)

2. Group by primary file:
   file_groups = group(fix_candidates, key=primary_evidence_file)

3. For each file group, create one fix task:
   FixTask {
     target_files: [primary_file, ...related_files]
     findings: [finding1, finding2, ...]  # All findings for this file group
     priority: max(finding.severity for finding in findings)
   }

4. Sort fix tasks by priority: CRITICAL > HIGH > MEDIUM

5. Conflict detection:
   - If two fix tasks share a target file, serialize them (add dependency)
   - Otherwise, fix tasks can run in parallel

6. Deploy debugger agents:
   - Each debugger gets: its FixTask (target files + findings + remediation hints)
   - Plus: REQUIREMENTS.md for full context
   - Plus: the specific Review Log entries for its findings

7. After all debuggers complete: trigger re-audit (Step 4)
```

**Fix task size limit**: Max 5 findings per fix task. If a file has more than 5 findings, split into multiple fix tasks (by severity group).

### 2.6 Re-audit Loop

After fixes, only the relevant auditors re-run on changed files.

**Re-audit scope determination**:
1. Collect all files modified by fix agents
2. Map modified files to affected requirement_ids (from the original findings)
3. Determine which auditors need to re-run:
   - If REQ-xxx findings were fixed -> re-deploy Requirements Auditor (scoped to affected REQ-xxx items)
   - If WIRE-xxx/SVC-xxx findings were fixed -> re-deploy Interface Auditor (scoped)
   - If TECH-xxx findings were fixed -> re-deploy Technical Auditor (scoped)
   - Test Auditor always re-runs (tests must pass after fixes)
   - MCP/Library Auditor only re-runs if library usage code was modified

**Re-audit prompt injection**: Each re-auditing agent receives:
- Only the subset of requirements that had findings
- Only the files that were modified
- The original findings (for comparison: did the fix resolve the issue?)

**Termination conditions**:
- Score >= 90 AND critical_count == 0 -> PASS (exit audit loop)
- No improvement after a re-audit cycle -> escalate (per existing escalation protocol)
- Max 3 re-audit cycles per audit-team invocation (prevents infinite loops)

---

## 3. Integration Plan

### 3.1 Per-Milestone Integration

The audit-team replaces the "Review Fleet" deployment in milestone execution (agents.py Section 4, MILESTONE EXECUTION step e).

**Current flow** (cli.py:1370-1449):
```
milestone execute -> health check -> review recovery -> handoff -> wiring check
```

**New flow**:
```
milestone execute -> AUDIT-TEAM -> health check -> fix dispatch -> re-audit -> handoff -> wiring check
```

**Integration point in orchestrator prompt** (agents.py Section 3, step 2):
Replace "Deploy REVIEW FLEET (ADVERSARIAL)" with "Deploy AUDIT-TEAM" instruction block.

**Milestone health check adaptation**: `check_milestone_health()` currently reads `review_cycles` from REQUIREMENTS.md. The audit-team writes a structured `AUDIT_REPORT.json` instead. The health check function must be updated to read from either source (backwards-compatible).

### 3.2 End-of-Run Integration

Post-orchestration (cli.py:5120-5298) currently runs `_run_review_only()` as recovery. The audit-team replaces this.

**Current flow**:
```
orchestration -> convergence check -> review recovery -> post-orchestration scans
```

**New flow**:
```
orchestration -> convergence check -> AUDIT-TEAM (if needed) -> post-orchestration scans
```

**Post-orchestration scan overlap**: Several current post-orchestration scans overlap with audit-team auditors:
- Mock data scan -> Interface Auditor (SVC-xxx mock data check)
- UI compliance scan -> Requirements Auditor (DESIGN-xxx check)
- API contract scan -> Interface Auditor (API-001 through API-004)
- SDL scan -> Technical Auditor (SDL-001/002/003)
- Endpoint xref scan -> Interface Auditor (XREF-001/002)

When the audit-team runs, these overlapping post-orchestration scans can be skipped (the audit-team already covered them). Non-overlapping scans (database scans, integrity scans) continue to run.

### 3.3 Existing Pipeline Compatibility

**Backwards compatibility requirements**:
1. REQUIREMENTS.md `[x]`/`[ ]` markers and `(review_cycles: N)` must still be updated. The scorer agent writes these after computing the report. This keeps GATE 5 enforcement working.
2. Review Log table in REQUIREMENTS.md must still be populated. The scorer agent appends audit findings as Review Log entries.
3. `ConvergenceReport` dataclass remains the same. The audit-team's `AuditScore.health` maps to `ConvergenceReport.health`.
4. `config.convergence.escalation_threshold` still applies. Items with `review_cycles >= threshold` still escalate.

**Config additions** (new `AuditTeamConfig` dataclass):
```python
@dataclass
class AuditTeamConfig:
    enabled: bool = False               # Opt-in (default: use legacy review fleet)
    max_parallel_auditors: int = 5      # All 5 by default
    max_reaudit_cycles: int = 3         # Max re-audit iterations
    fix_severity_threshold: str = "MEDIUM"  # Fix CRITICAL through this level
    score_healthy_threshold: float = 90.0
    score_degraded_threshold: float = 70.0
    context7_prefetch: bool = True      # Pre-fetch docs for MCP/Library auditor
    max_findings_per_fix_task: int = 5
    skip_overlapping_scans: bool = True # Skip post-orch scans that audit-team covers
```

**Depth gating**:
- **quick**: `enabled: False` (use legacy review fleet)
- **standard**: `enabled: True`, `max_parallel_auditors: 3` (skip MCP/Library auditor and Test auditor runs tests only, no quality analysis)
- **thorough**: `enabled: True`, all 5 auditors, `max_reaudit_cycles: 2`
- **exhaustive**: `enabled: True`, all 5 auditors, `max_reaudit_cycles: 3`

### 3.4 Token Budget Management

**Token cost estimate per audit-team invocation**:

| Component | Input tokens | Output tokens | Instances | Total |
|-----------|-------------|---------------|-----------|-------|
| Requirements Auditor | ~8K (REQUIREMENTS.md + code reads) | ~2K (findings) | 1 | ~10K |
| Technical Auditor | ~8K | ~2K | 1 | ~10K |
| Interface Auditor | ~10K (larger due to wiring maps) | ~3K | 1 | ~13K |
| Test Auditor | ~6K (test output + code) | ~2K | 1 | ~8K |
| MCP/Library Auditor | ~12K (includes Context7 docs) | ~2K | 1 | ~14K |
| Scorer Agent | ~11K (all findings from 5 auditors) | ~3K (report + REQUIREMENTS.md updates) | 1 | ~14K |
| **Total per audit cycle** | | | | **~69K** |

**Comparison with current system**: A single code-reviewer agent with the full 200-line prompt + code reads uses ~15-20K tokens per invocation. At "thorough" depth (3-5 reviewers), that is 45-100K tokens. The audit-team at ~69K is comparable but produces structured, scored output.

**Budget optimization strategies**:
1. **Scope injection**: Each auditor receives only the requirements in its domain, not the full REQUIREMENTS.md. Requirements Auditor gets REQ-xxx + DESIGN-xxx. Interface Auditor gets WIRE-xxx + SVC-xxx. This reduces input tokens by ~30%.
2. **Re-audit scoping**: Re-audit cycles only deploy affected auditors with affected requirements (typically 1-2 auditors, not all 5). Re-audit cost: ~15-25K per cycle.
3. **MCP/Library Auditor skip**: If no tech research was performed (tech_research.enabled: false), skip this auditor entirely. Saves ~14K tokens.
4. **Finding cap**: Each auditor caps output at 30 findings. Beyond that, only CRITICAL and HIGH findings are reported.

---

## 4. Implementation Plan

### 4.1 New Files

| File | Purpose | Size estimate |
|------|---------|---------------|
| `src/agent_team/audit_team.py` | Core audit-team orchestration: parallel auditor dispatch, scorer invocation, fix dispatch algorithm, re-audit loop | ~400 lines |
| `src/agent_team/audit_prompts.py` | 5 auditor prompts + scorer prompt (extracted from CODE_REVIEWER_PROMPT) | ~500 lines |
| `src/agent_team/audit_models.py` | `AuditFinding`, `AuditScore`, `AuditReport`, `FixTask` dataclasses + JSON serialization | ~150 lines |
| `tests/test_audit_team.py` | Unit tests for audit_team.py | ~300 lines |
| `tests/test_audit_models.py` | Unit tests for data models + scoring | ~200 lines |
| `tests/test_audit_prompts.py` | Tests that audit prompts contain required sections | ~100 lines |

### 4.2 Modified Files

| File | Changes |
|------|---------|
| `src/agent_team/config.py` | Add `AuditTeamConfig` dataclass, wire into `AgentTeamConfig`, add depth gating, add YAML parsing |
| `src/agent_team/agents.py` | Add audit-team deployment instructions to ORCHESTRATOR_SYSTEM_PROMPT Section 3 (convergence loop step 2) and Section 6 (fleet deployment). Add agent definitions for 5 auditors + scorer. |
| `src/agent_team/cli.py` | In `_run_prd_milestones()`: call `audit_team.run_audit()` instead of deploying review fleet. In post-orchestration: call `audit_team.run_audit()` instead of `_run_review_only()`. Skip overlapping scans when audit-team ran. |
| `src/agent_team/verification.py` | Add `_check_audit_report()` function that reads `AUDIT_REPORT.json` as an alternative health source |
| `src/agent_team/milestone_manager.py` | Update `check_milestone_health()` to read from `AUDIT_REPORT.json` when available |
| `src/agent_team/state.py` | Add `audit_score` field to `ConvergenceReport` for structured score tracking |

### 4.3 Test Plan

**Unit tests** (tests/test_audit_models.py):
- AuditFinding construction and serialization
- AuditScore computation: healthy/degraded/failed thresholds
- AuditReport deduplication logic
- FixTask grouping by file
- Score formula edge cases: 0 items, all pass, all fail, mixed

**Unit tests** (tests/test_audit_team.py):
- `group_findings_by_file()`: correct grouping, conflict detection
- `compute_reaudit_scope()`: maps modified files to affected auditors
- `should_skip_scan()`: correctly identifies overlapping scans
- Fix task serialization: max 5 findings per task
- Re-audit termination: max cycles, no improvement detection
- Backwards compatibility: REQUIREMENTS.md markers still written

**Integration tests** (tests/test_audit_team.py):
- Full audit-team invocation with mock auditor responses
- Score computation from multi-auditor findings
- Fix dispatch with file conflicts (serialization)
- Re-audit scoping after fix

**Prompt tests** (tests/test_audit_prompts.py):
- Each auditor prompt contains its required verification sections
- No auditor prompt exceeds 100 lines (token budget)
- Scorer prompt contains deduplication and scoring instructions
- All prompts reference `AuditFinding` output format

---

## 5. Data Structures

### 5.1 AuditFinding

```python
@dataclass
class AuditFinding:
    """A single audit finding from any auditor.

    Auditors produce these as structured output. The scorer collects
    and deduplicates them into an AuditReport.
    """

    finding_id: str
    """Auto-generated: "{auditor_prefix}-{seq}" e.g. "RA-001", "IA-003"."""

    auditor: str
    """Source auditor: "requirements" | "technical" | "interface" | "test" | "mcp_library"."""

    requirement_id: str
    """Parent requirement ID from REQUIREMENTS.md: "REQ-001", "WIRE-003", "TECH-005".
    Use "GENERAL" for findings not tied to a specific requirement."""

    verdict: str
    """Per-requirement verdict: "PASS" | "FAIL" | "PARTIAL"."""

    severity: str
    """Finding severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO"."""

    summary: str
    """One-line human-readable description of the finding."""

    evidence: list[str]
    """List of evidence strings in "file_path:line_number -- description" format.
    At least one evidence entry is required for FAIL/PARTIAL verdicts."""

    remediation: str
    """Suggested fix for FAIL/PARTIAL verdicts. Empty string for PASS/INFO."""

    confidence: float
    """Auditor's confidence in this finding: 0.0 (uncertain) to 1.0 (certain)."""

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "auditor": self.auditor,
            "requirement_id": self.requirement_id,
            "verdict": self.verdict,
            "severity": self.severity,
            "summary": self.summary,
            "evidence": self.evidence,
            "remediation": self.remediation,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AuditFinding":
        return cls(
            finding_id=data["finding_id"],
            auditor=data["auditor"],
            requirement_id=data["requirement_id"],
            verdict=data["verdict"],
            severity=data["severity"],
            summary=data["summary"],
            evidence=data.get("evidence", []),
            remediation=data.get("remediation", ""),
            confidence=data.get("confidence", 1.0),
        )
```

### 5.2 AuditReport

```python
@dataclass
class AuditReport:
    """Complete audit report produced by the scorer agent.

    Persisted as .agent-team/AUDIT_REPORT.json for downstream
    consumption by fix dispatch and health checks.
    """

    audit_id: str
    """Unique ID: "audit-{milestone_id}-{cycle}" or "audit-final-{cycle}"."""

    timestamp: str
    """ISO 8601 timestamp of when the audit completed."""

    cycle: int
    """Audit cycle number within the current convergence loop iteration."""

    auditors_deployed: list[str]
    """Which auditors ran: ["requirements", "technical", "interface", "test", "mcp_library"]."""

    findings: list[AuditFinding]
    """All findings, deduplicated by the scorer."""

    score: "AuditScore"
    """Computed score from findings."""

    by_severity: dict[str, list[int]]
    """Finding indices grouped by severity. Key: severity string, Value: indices into findings list."""

    by_file: dict[str, list[int]]
    """Finding indices grouped by primary evidence file path."""

    by_requirement: dict[str, list[int]]
    """Finding indices grouped by requirement_id."""

    fix_candidates: list[int]
    """Indices into findings list for items that need fixing (CRITICAL + HIGH + MEDIUM, FAIL/PARTIAL verdict)."""

    def to_json(self) -> str:
        """Serialize to JSON for persistence."""
        import json
        return json.dumps({
            "audit_id": self.audit_id,
            "timestamp": self.timestamp,
            "cycle": self.cycle,
            "auditors_deployed": self.auditors_deployed,
            "findings": [f.to_dict() for f in self.findings],
            "score": self.score.to_dict(),
            "by_severity": self.by_severity,
            "by_file": self.by_file,
            "by_requirement": self.by_requirement,
            "fix_candidates": self.fix_candidates,
        }, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "AuditReport":
        """Deserialize from JSON."""
        import json
        data = json.loads(json_str)
        findings = [AuditFinding.from_dict(f) for f in data["findings"]]
        return cls(
            audit_id=data["audit_id"],
            timestamp=data["timestamp"],
            cycle=data.get("cycle", 1),
            auditors_deployed=data["auditors_deployed"],
            findings=findings,
            score=AuditScore.from_dict(data["score"]),
            by_severity=data.get("by_severity", {}),
            by_file=data.get("by_file", {}),
            by_requirement=data.get("by_requirement", {}),
            fix_candidates=data.get("fix_candidates", []),
        )
```

### 5.3 AuditScore

```python
@dataclass
class AuditScore:
    """Computed score for an audit run.

    The score formula weights PASS as 100, PARTIAL as 50, FAIL as 0,
    then divides by total items to get a percentage.

    Health is determined by score thresholds AND critical finding count.
    """

    total_items: int
    """Total distinct requirement IDs audited (excludes GENERAL findings)."""

    passed: int
    """Requirements with PASS verdict."""

    failed: int
    """Requirements with FAIL verdict."""

    partial: int
    """Requirements with PARTIAL verdict."""

    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    info_count: int

    score: float
    """Weighted score: 0.0 to 100.0."""

    health: str
    """Computed health: "healthy" | "degraded" | "failed"."""

    @staticmethod
    def compute(
        findings: list[AuditFinding],
        healthy_threshold: float = 90.0,
        degraded_threshold: float = 70.0,
    ) -> "AuditScore":
        """Compute score from a list of findings."""
        # Group by requirement_id to get per-requirement verdicts
        req_verdicts: dict[str, str] = {}
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}

        for f in findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
            if f.requirement_id == "GENERAL":
                continue
            # Worst verdict wins for each requirement
            current = req_verdicts.get(f.requirement_id, "PASS")
            if f.verdict == "FAIL":
                req_verdicts[f.requirement_id] = "FAIL"
            elif f.verdict == "PARTIAL" and current != "FAIL":
                req_verdicts[f.requirement_id] = "PARTIAL"

        total = len(req_verdicts)
        passed = sum(1 for v in req_verdicts.values() if v == "PASS")
        failed = sum(1 for v in req_verdicts.values() if v == "FAIL")
        partial = sum(1 for v in req_verdicts.values() if v == "PARTIAL")

        score = (passed * 100 + partial * 50) / max(total, 1)

        critical = severity_counts.get("CRITICAL", 0)
        if score >= healthy_threshold and critical == 0:
            health = "healthy"
        elif score >= degraded_threshold and critical == 0:
            health = "degraded"
        else:
            health = "failed"

        return AuditScore(
            total_items=total,
            passed=passed,
            failed=failed,
            partial=partial,
            critical_count=critical,
            high_count=severity_counts.get("HIGH", 0),
            medium_count=severity_counts.get("MEDIUM", 0),
            low_count=severity_counts.get("LOW", 0),
            info_count=severity_counts.get("INFO", 0),
            score=round(score, 1),
            health=health,
        )

    def to_dict(self) -> dict:
        return {
            "total_items": self.total_items,
            "passed": self.passed,
            "failed": self.failed,
            "partial": self.partial,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            "info_count": self.info_count,
            "score": self.score,
            "health": self.health,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AuditScore":
        return cls(
            total_items=data["total_items"],
            passed=data["passed"],
            failed=data["failed"],
            partial=data["partial"],
            critical_count=data["critical_count"],
            high_count=data["high_count"],
            medium_count=data["medium_count"],
            low_count=data["low_count"],
            info_count=data["info_count"],
            score=data["score"],
            health=data["health"],
        )
```

---

## 6. Agent Prompts (Draft)

### 6.1 Requirements Auditor

```
You are a REQUIREMENTS AUDITOR in the Agent Team audit-team.

Your job is to verify EVERY functional and design requirement against the actual codebase.

## Scope
You audit: REQ-xxx, DESIGN-xxx, SEED-xxx, ENUM-xxx requirements ONLY.
Other requirement types (TECH, WIRE, SVC, TEST) are handled by other auditors.

## Process
For EACH requirement in your scope:
1. Read the requirement text carefully
2. Find the implementation in the codebase (use Glob, Grep, Read)
3. Verify it is FULLY and CORRECTLY implemented:
   - Does the code match the requirement specification?
   - Are edge cases handled?
   - Is input validation present where needed?
   - Does error handling cover failure modes?
4. Cross-check against [ORIGINAL USER REQUEST] for omissions
5. For SEED-xxx: verify all fields explicitly set, seeded values pass API filters, every role has a seed account
6. For ENUM-xxx: verify registry exists, frontend/backend strings match, transitions follow registry

## Output Format
Return your findings as a JSON array. Each finding:
{
  "finding_id": "RA-001",
  "auditor": "requirements",
  "requirement_id": "REQ-001",
  "verdict": "PASS" | "FAIL" | "PARTIAL",
  "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO",
  "summary": "One-line description",
  "evidence": ["src/routes/auth.ts:42 -- missing password validation"],
  "remediation": "Add password length check in validateLogin()",
  "confidence": 0.95
}

## Rules
- Be ADVERSARIAL -- your job is to find gaps, not confirm success
- FAIL means: requirement NOT met. Evidence is mandatory.
- PARTIAL means: partially met but incomplete. Evidence + remediation mandatory.
- PASS means: fully and correctly implemented. Evidence of verification (file:line checked).
- Every requirement in your scope MUST have exactly one finding entry
- Minimum confidence 0.7 for FAIL verdicts (if uncertain, mark PARTIAL)
```

### 6.2 Technical Auditor

```
You are a TECHNICAL AUDITOR in the Agent Team audit-team.

Your job is to verify technical requirements, architecture compliance, and code quality patterns.

## Scope
You audit: TECH-xxx requirements ONLY.
Also check for: SDL-001/002/003 (silent data loss), anti-patterns (FRONT-xxx, BACK-xxx, SLOP-xxx).

## Process
For EACH TECH-xxx requirement:
1. Read the requirement and the Architecture Decision section
2. Verify the implementation follows the specified patterns, conventions, and types
3. Check for production readiness: error handling, logging, configuration
4. Check SDL patterns:
   - SDL-001: Every CommandHandler that modifies data MUST call SaveChangesAsync()
   - SDL-002: Chained API calls must use response from previous call
   - SDL-003: Guard clauses in user-initiated methods must provide feedback

## Output Format
Return findings as JSON array (same schema as Requirements Auditor).
Use prefix "TA-" for finding_id (e.g., "TA-001").

## Rules
- Architecture violations are FAIL (HIGH severity)
- SDL findings are FAIL (CRITICAL severity)
- Anti-pattern matches are PARTIAL (MEDIUM severity) unless they cause runtime issues
- Every TECH-xxx requirement MUST have a finding entry
- GENERAL findings (not tied to a requirement) use requirement_id: "GENERAL"
```

### 6.3 Interface Auditor

```
You are an INTERFACE AUDITOR in the Agent Team audit-team.

Your job is to verify wiring, integration contracts, API field schemas, and detect orphaned code.

## Scope
You audit: WIRE-xxx, SVC-xxx requirements.
Also check: API-001/002/003/004, XREF-001/002, orphan detection.

## Process

### WIRE-xxx Verification
For each WIRE-xxx item:
1. Find the wiring mechanism in code (import, route registration, component render, middleware chain)
2. Trace the connection: entry point -> intermediate modules -> target feature
3. Verify it ACTUALLY EXECUTES (not just defined/imported)
4. FAIL if feature is unreachable from any entry point

### SVC-xxx Verification
For each SVC-xxx item:
1. Open the frontend service file
2. Verify EVERY method makes a REAL HTTP call (HttpClient, fetch, axios)
3. AUTOMATIC FAIL if ANY method contains: of(), delay(), mockData, fakeData, hardcoded arrays
4. Verify URL path matches actual backend endpoint
5. Verify response DTO shape matches frontend expectations
6. Check enum mapping: numeric backend enums need frontend mapper

### API Field Verification
For each SVC-xxx with field schema:
- API-001: Backend DTO has all fields listed in Response DTO column
- API-002: Frontend model uses exact same field names (camelCase for TS reading C#)
- API-003: Type compatibility (int->number, DateTime->string, etc.)
- API-004: Request fields sent by frontend exist in backend Command/DTO

### Orphan Detection
Sweep all NEW application logic files:
- Any new file not imported by another file -> orphan
- Any new export not imported anywhere -> orphan
- Any new component not rendered anywhere -> orphan
Exclude: entry points, test files, config files, assets

## Output Format
Return findings as JSON array. Use prefix "IA-" for finding_id.

## Rules
- Mock data in ANY service method = AUTOMATIC FAIL (CRITICAL severity)
- Wiring that doesn't execute = FAIL (HIGH severity)
- Orphaned code = FAIL (MEDIUM severity)
- API field mismatches = FAIL (HIGH severity)
- Every WIRE-xxx and SVC-xxx MUST have a finding entry
```

### 6.4 Test Auditor

```
You are a TEST AUDITOR in the Agent Team audit-team.

Your job is to verify test coverage, run tests, and enforce quality standards.

## Scope
You audit: TEST-xxx requirements, test quality, test count thresholds.

## Process
1. Detect and run the project's test command
2. Parse results: total tests, passed, failed, skipped
3. Verify minimum test count from REQUIREMENTS.md (default: 20)
4. For each test file, check quality:
   - Every test MUST have at least one meaningful assertion (not just .toBeDefined())
   - No test.skip / xit / xdescribe
   - Test behavior not implementation
   - One behavior per test case
   - Descriptive test names
5. Verify integration tests exist for each WIRE-xxx item
6. Report test coverage if available

## Output Format
Return findings as JSON array. Use prefix "XA-" for finding_id.

Special findings:
- "XA-SUMMARY": requirement_id="TEST-SUMMARY", summary="X passed, Y failed, Z skipped"
- One finding per TEST-xxx requirement
- One finding per WIRE-xxx item that lacks integration tests

## Rules
- Any test failure = FAIL (HIGH severity)
- Insufficient test count = FAIL (MEDIUM severity)
- Empty/shallow tests = PARTIAL (MEDIUM severity)
- Skipped tests = PARTIAL (LOW severity)
- Missing integration test for WIRE-xxx = FAIL (MEDIUM severity)
```

### 6.5 MCP/Library Auditor

```
You are an MCP/LIBRARY AUDITOR in the Agent Team audit-team.

Your job is to verify that third-party library and API usage is correct.

## Context
You receive library documentation injected by the orchestrator (from Context7 pre-fetch).
This documentation is authoritative -- compare actual code usage against it.

## Process
For each technology in the documentation context:
1. Find all usage sites in the codebase (Grep for import statements + API calls)
2. Cross-reference against documentation:
   - Correct method names and signatures
   - Correct parameter types and order
   - Correct return types
   - No deprecated API usage
   - Version-compatible patterns
3. Check for common mistakes:
   - Using sync version when async is required
   - Missing error handling on library calls
   - Wrong configuration patterns
   - Missing required middleware/plugins

## Output Format
Return findings as JSON array. Use prefix "MA-" for finding_id.
Use requirement_id: "GENERAL" for library findings not tied to a specific requirement.
Use the relevant REQ/TECH-xxx if the finding relates to a specific requirement's implementation.

## Rules
- Deprecated API usage = FAIL (HIGH severity)
- Wrong method signature = FAIL (HIGH severity)
- Missing error handling on library call = PARTIAL (MEDIUM severity)
- Suboptimal pattern (works but not recommended) = INFO
- Only report findings for libraries in your documentation context (don't guess)
```

### 6.6 Scorer Agent

```
You are the SCORER AGENT in the Agent Team audit-team.

Your job is to collect findings from all 5 auditors, deduplicate, compute scores, and produce the final AuditReport.

## Input
You receive the raw finding arrays from each auditor that ran.

## Process

### 1. Deduplication
- If two auditors report on the same requirement_id with the same verdict: keep the one with higher confidence
- If two auditors report on the same file:line: merge evidence lists into one finding
- NEVER deduplicate across different requirement_ids

### 2. Score Computation
For each unique requirement_id (excluding "GENERAL"):
- Take the WORST verdict across all findings for that requirement
- PASS = 100 points, PARTIAL = 50 points, FAIL = 0 points
- Score = sum(points) / (count * 100) * 100

Health determination:
- score >= 90 AND critical_count == 0 -> "healthy"
- score >= 70 AND critical_count == 0 -> "degraded"
- else -> "failed"

### 3. REQUIREMENTS.md Update
For each requirement_id with a finding:
- If verdict is PASS: mark [x] in REQUIREMENTS.md, increment (review_cycles: N+1)
- If verdict is FAIL or PARTIAL: leave [ ], increment (review_cycles: N+1)
- Add Review Log entry: | cycle | audit-team | requirement_id | verdict | summary |

### 4. Report Generation
Produce a complete AuditReport JSON with:
- All deduplicated findings
- Computed score
- Grouped indices (by_severity, by_file, by_requirement)
- fix_candidates list (CRITICAL + HIGH + MEDIUM findings with FAIL/PARTIAL verdict)

Write the report to .agent-team/AUDIT_REPORT.json.

## Output
Write AUDIT_REPORT.json and update REQUIREMENTS.md.
Report the final score and health status.
```
