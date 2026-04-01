# Audit System Upgrade Design

## Executive Summary

The current audit system failed on ArkanPM: 12 runs, 50+ fix milestones, only 52% finding reduction, then regression. Root causes:

1. **Wrong level of analysis**: The existing audit (`audit_agent.py:run_audit`) audits against PRD ACCEPTANCE CRITERIA — "does feature X exist?" It CANNOT find implementation quality bugs (route mismatches, schema integrity, auth flow divergence, response shape, soft-delete gaps) because those are never stated as acceptance criteria. The 62 real bugs the manual audit found were ALL implementation quality issues, not PRD compliance gaps.
2. **No deterministic scanners in the audit loop**: We have `schema_validator`, `quality_validators`, `integration_verifier`, and `quality_checks` — but they only run as post-orchestration verification steps in `cli.py`. The audit-team system (`audit_team.py`, `audit_prompts.py`) has zero awareness of them.
3. **False positive amplification**: The ArkanPM fix cycle log shows 8 cycles wasted on Tailwind spacing false positives (UI-004). No suppression mechanism exists.
4. **Vague fix PRDs**: `fix_prd_agent.py` generates fix PRDs from LLM findings with vague categories like `code_fix`, `ux`, `missing_feature`. The fixer doesn't know what concrete code change to make.
5. **No convergence enforcement**: `should_terminate_reaudit` in `audit_team.py:87-127` checks for no_improvement and max_cycles, but `max_reaudit_cycles` defaults to 3, and the ArkanPM run hit 12 cycles because the audit was invoked per-milestone in a loop.
6. **Two parallel audit systems**: `audit_agent.py` (1878 lines, AC-based) and `audit_team.py`/`audit_models.py`/`audit_prompts.py` (6-auditor system) are both active. The 6-auditor system dispatches LLM agents with prompts that duplicate the deterministic scanner coverage (e.g., interface auditor checks WIRE/SVC which `integration_verifier` already handles).
7. **Insufficient agentic investigation**: The current agentic call (`_call_claude_sdk_agentic` at `audit_agent.py:84`) uses `max_turns=6`, which is too few for deep cross-file investigation. The agentic session has no access to deterministic validators as callable tools — it can only Read/Grep/Glob.

## Core Insight: Two Distinct Audit Modes

The fundamental architectural change: the audit system needs TWO MODES that serve different purposes:

### Mode 1: Implementation Quality (PRIMARY for fix cycles)
- **Question**: "Does the build have integration bugs, schema issues, cross-layer inconsistencies?"
- **Engine**: Deterministic validators (schema_validator, quality_validators, integration_verifier, quality_checks) + agentic Claude investigation with validators-as-tools
- **When**: After every milestone build. This is the PRIMARY mode for fix cycles.
- **Why primary**: PRD compliance is already checked during the convergence loop's review fleet. The 62 missed bugs on ArkanPM were ALL implementation quality issues.

### Mode 2: PRD Compliance (SUPPLEMENTARY)
- **Question**: "Does the build satisfy what the PRD asked for?"
- **Engine**: LLM auditors (requirements, prd_fidelity) checking ACs against code
- **When**: After implementation quality passes. Optional during fix cycles.
- **Why supplementary**: The existing review fleet already does PRD compliance checking. The audit's value-add is catching what the review fleet misses — which is implementation quality, not PRD compliance.

## Design Principles

1. **Implementation Quality is primary**: The audit's #1 job is running deterministic validators as a coordinated battery, then using an agentic Claude session ONLY to investigate findings that deterministic tools cannot catch (business logic correctness, state machine completeness).
2. **Two explicit modes**: Implementation Quality mode (deterministic + agentic investigation) and PRD Compliance mode (LLM auditors). Clearly separated, independently invocable.
3. **Deterministic-first within each mode**: In Implementation Quality mode, deterministic scanners run first. Agentic LLM investigation runs second, scoped to what scanners cannot detect.
4. **Validators as agentic tools**: The agentic Claude session gets our deterministic validators as callable tools, so it can run targeted scans during its investigation (e.g., "run the enum validator on just this file").
5. **Scoped fix PRDs**: Every fix task maps to exactly one deterministic finding with a concrete code location, expected state, and verification command.
6. **False positive suppression**: Findings confirmed as false positives are stored in `.agent-team/suppressions.json` and auto-excluded from future scans.
7. **Mandatory convergence**: Hard limit of 5 fix cycles. Plateau detection after 2 cycles with <5% improvement triggers escalation, not repetition.
8. **Regression is a gate**: After every fix cycle, re-run deterministic scanners. Any NEW finding = immediate stop + report. No silent regression.

## Architecture

### Mode 1: Implementation Quality Audit (PRIMARY)

This is the default audit mode. It runs during fix cycles and after milestone builds.

```
STEP 1: DETERMINISTIC SCANNER BATTERY (fast, free, reproducible)
  ├── schema_validator.run_schema_validation()     → SchemaFinding[]
  ├── quality_validators.run_quality_validators()  → Violation[]
  │   ├── ENUM-001..003  (enum/role/status mismatches)
  │   ├── AUTH-001..004  (auth endpoint/MFA/token/security)
  │   ├── SHAPE-001..003 (field naming, array wrapping, field drift)
  │   ├── SOFTDEL-001..002, QUERY-001 (soft-delete, field refs, casts)
  │   └── INFRA-001..005 (ports, configs, tsconfig, Docker)
  ├── integration_verifier.verify_integration()    → IntegrationReport
  │   ├── Route mismatches (frontend calls vs backend endpoints)
  │   ├── Field name mismatches (camelCase vs snake_case drift)
  │   ├── Missing/unused endpoints
  │   └── RoutePatternEnforcer: ROUTE-001..004
  └── quality_checks.run_spot_checks()             → Violation[]
      ├── FRONT-xxx (frontend anti-patterns)
      ├── BACK-xxx  (backend anti-patterns)
      └── SLOP-xxx  (AI-generated code smells)

  Output: DeterministicScanResult (unified findings list, typed + deduped)

STEP 2: AGENTIC INVESTIGATION (targeted, deep, validators-as-tools)
  ├── Single Claude agentic session with EXTENDED turns (max_turns=15)
  ├── Receives Step 1 findings as context
  ├── Has access to ENHANCED tool set:
  │   ├── Standard: Read, Grep, Glob, Bash
  │   ├── NEW: run_schema_check(model, field)      — targeted schema scan
  │   ├── NEW: run_enum_check(enum_name)            — targeted enum scan
  │   ├── NEW: run_route_check(endpoint_path)       — targeted route match
  │   ├── NEW: run_quality_check(file_path, checks) — targeted quality scan
  │   └── NEW: check_suppression(finding_id)        — is this suppressed?
  ├── Investigates ONLY what deterministic scanners CANNOT detect:
  │   ├── Business logic correctness (right algorithm?)
  │   ├── State machine completeness (all transitions covered?)
  │   ├── Cross-cutting concerns (logging, error messages, i18n)
  │   └── Data flow: does data actually flow end-to-end correctly?
  └── Budget-capped: max 30% of total audit budget

  Output: AgenticFindings (merged with deterministic findings, deduplicated)
```

### Mode 2: PRD Compliance Audit (SUPPLEMENTARY)

Runs after Implementation Quality passes or on explicit request. Uses existing LLM auditors.

```
STEP 1: LLM AUDITOR DEPLOYMENT (scoped, not shotgun)
  ├── requirements auditor  — REQ/DESIGN/SEED/ENUM vs codebase
  ├── prd_fidelity auditor  — dropped/distorted/orphaned requirements
  └── (optional) test auditor — test execution + coverage verification

  NOTE: interface, technical (SDL), mcp_library auditors are NOT deployed
  in this mode — their coverage is handled by Mode 1 deterministic scanners.

STEP 2: SCORER
  ├── Collect LLM auditor findings
  ├── Merge with Mode 1 deterministic findings (if available)
  ├── Deduplicate, compute score
  └── Write AUDIT_REPORT.json
```

### Fix Cycle Pipeline (uses Mode 1 as primary)

```
PHASE 1: IMPLEMENTATION QUALITY SCAN (Mode 1: Step 1 + Step 2)
  └── Produces: unified findings list (deterministic + agentic)

PHASE 2: FIX PRD GENERATION (scoped + regression-aware)
  ├── Each finding maps to exactly ONE fix task
  ├── Fix tasks ordered by: severity → dependency chain → file locality
  ├── Each fix task includes:
  │   ├── Finding ID + check code (e.g., SCHEMA-001, AUTH-001, ROUTE-002)
  │   ├── Exact file:line location
  │   ├── Current code snippet
  │   ├── Expected fix (from finding.suggestion)
  │   └── Verification command (re-run the specific validator)
  ├── Regression watchlist: all files modified in previous fix cycles
  └── Suppressed findings excluded from fix PRD

PHASE 3: FIX EXECUTION + VERIFICATION
  ├── Fix milestones execute the scoped fix PRD
  ├── After EACH fix milestone: re-run Mode 1 deterministic scanners
  ├── REGRESSION CHECK: compare finding set before/after
  │   ├── New findings not in previous set = REGRESSION → stop + report
  │   └── Findings removed from previous set = PROGRESS → continue
  ├── CONVERGENCE CHECK:
  │   ├── Track findings_count per cycle
  │   ├── If findings_count unchanged for 2 consecutive cycles → ESCALATE
  │   ├── If findings_count increased → STOP (regression)
  │   └── Hard limit: 5 total fix cycles
  └── COMPLETION: findings_count == 0 OR all remaining are suppressed

PHASE 4: PRD COMPLIANCE (Mode 2 — optional, runs after Mode 1 converges)
  ├── Only if config enables it
  ├── Findings from Mode 2 are ADVISORY, not fix-blocking
  └── Feeds into a separate PRD compliance report
```

## Specific Changes Per File

### 1. `audit_agent.py` — Two-mode audit: Implementation Quality (primary) + PRD Compliance (supplementary)

**Current state**: 1878 lines. `run_audit()` extracts ACs from PRD, runs static grep checks + agentic Claude checks per-AC. The agentic session uses `_call_claude_sdk_agentic()` with `max_turns=6` and only Read/Grep/Glob tools. This audits at the WRONG LEVEL — it checks PRD acceptance criteria compliance, not implementation quality. The 62 bugs missed on ArkanPM were all implementation quality issues (routes, schema, auth, enums) that the AC-based approach fundamentally cannot detect.

**Changes**:

A) Add new function `run_deterministic_audit()` — the Implementation Quality mode entry point:

```python
# New in audit_agent.py (or better: new file audit_orchestrator.py)

@dataclass
class DeterministicFinding:
    """Unified finding from any deterministic scanner."""
    id: str                    # e.g. "SCHEMA-001-Asset-tenant_id"
    check_code: str            # e.g. "SCHEMA-001"
    source_scanner: str        # "schema_validator" | "quality_validators" | "integration_verifier" | "quality_checks"
    severity: str              # "critical" | "high" | "medium" | "low"
    message: str
    file_path: str             # Relative path
    line: int
    suggestion: str            # Actionable fix instruction
    model: str = ""            # Prisma model (if applicable)
    field: str = ""            # Field name (if applicable)
    verification_command: str = ""  # How to re-check after fix

@dataclass
class DeterministicScanResult:
    """Output of Phase 1."""
    findings: list[DeterministicFinding]
    scanner_results: dict[str, Any]  # Raw results per scanner
    timestamp: str
    scan_duration_seconds: float

@dataclass
class SuppressionEntry:
    """A finding confirmed as false positive."""
    finding_signature: str      # check_code + file + line range hash
    reason: str                 # Why it's a false positive
    suppressed_by: str          # "human" | "auto-verified"
    suppressed_at: str          # ISO timestamp
    cycle: int                  # Which cycle it was suppressed in

def run_deterministic_audit(
    project_root: Path,
    suppressions: list[SuppressionEntry] | None = None,
) -> DeterministicScanResult:
    """Phase 1: Run ALL deterministic scanners and unify results."""
    
    findings: list[DeterministicFinding] = []
    scanner_results: dict[str, Any] = {}
    
    # 1. Schema validation
    from .schema_validator import run_schema_validation
    schema_findings = run_schema_validation(project_root)
    scanner_results["schema_validator"] = schema_findings
    for sf in schema_findings:
        findings.append(DeterministicFinding(
            id=f"{sf.check}-{sf.model}-{sf.field}",
            check_code=sf.check,
            source_scanner="schema_validator",
            severity=sf.severity,
            message=sf.message,
            file_path=_find_schema_path(project_root),  # schema.prisma relative path
            line=sf.line,
            suggestion=sf.suggestion,
            model=sf.model,
            field=sf.field,
            verification_command=f"run_schema_validation('{project_root}')",
        ))
    
    # 2. Quality validators (enum, auth, shape, soft-delete, infra)
    from .quality_validators import run_quality_validators
    quality_violations = run_quality_validators(project_root)
    scanner_results["quality_validators"] = quality_violations
    for v in quality_violations:
        findings.append(DeterministicFinding(
            id=f"{v.check}-{v.file_path}-{v.line}",
            check_code=v.check,
            source_scanner="quality_validators",
            severity=v.severity,
            message=v.message,
            file_path=v.file_path,
            line=v.line,
            suggestion="",  # quality_validators don't have suggestions yet
            verification_command=f"run_quality_validators('{project_root}')",
        ))
    
    # 3. Integration verifier (route mismatches, field mismatches)
    from .integration_verifier import verify_integration
    integration_result = verify_integration(project_root)
    scanner_results["integration_verifier"] = integration_result
    # Convert IntegrationReport.mismatches to DeterministicFinding
    if hasattr(integration_result, 'mismatches'):
        for i, mm in enumerate(integration_result.mismatches):
            findings.append(DeterministicFinding(
                id=f"INTEG-{mm.category}-{i}",
                check_code=f"INTEG-{mm.category}",
                source_scanner="integration_verifier",
                severity=mm.severity.lower(),
                message=mm.description,
                file_path=mm.frontend_file or mm.backend_file,
                line=0,
                suggestion=mm.suggestion,
                verification_command=f"verify_integration('{project_root}')",
            ))
    
    # 4. Quality checks (anti-patterns: FRONT-xxx, BACK-xxx, SLOP-xxx)
    from .quality_checks import run_spot_checks
    spot_violations = run_spot_checks(project_root)
    scanner_results["quality_checks"] = spot_violations
    for v in spot_violations:
        findings.append(DeterministicFinding(
            id=f"{v.check}-{v.file_path}-{v.line}",
            check_code=v.check,
            source_scanner="quality_checks",
            severity=v.severity,
            message=v.message,
            file_path=v.file_path,
            line=v.line,
            suggestion="",
            verification_command=f"run_spot_checks('{project_root}')",
        ))
    
    # 5. Apply suppressions
    if suppressions:
        suppression_sigs = {s.finding_signature for s in suppressions}
        findings = [f for f in findings if _finding_signature(f) not in suppression_sigs]
    
    # 6. Deduplicate (same check_code + same file + lines within 5 of each other)
    findings = _deduplicate_deterministic(findings)
    
    return DeterministicScanResult(
        findings=findings,
        scanner_results=scanner_results,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        scan_duration_seconds=0.0,  # filled by caller
    )
```

B) Add `run_agentic_investigation()` — Step 2 of Implementation Quality mode:

The current `_call_claude_sdk_agentic()` has two critical limitations:
1. `max_turns=6` is too few for deep cross-file investigation
2. The tool set is only Read/Grep/Glob — no access to deterministic validators

The upgrade gives the agentic session MORE turns and our validators as TOOLS:

```python
# New agentic investigation tools (registered alongside Read/Grep/Glob/Bash)
VALIDATOR_TOOLS = [
    {
        "name": "run_schema_check",
        "description": "Run schema validation on the project. Optionally filter to a specific model or check code. Returns SchemaFinding[] as JSON.",
        "input_schema": {
            "type": "object",
            "properties": {
                "model_filter": {"type": "string", "description": "Only return findings for this Prisma model name (optional)"},
                "check_filter": {"type": "string", "description": "Only return findings for this check code, e.g. 'SCHEMA-001' (optional)"},
            },
        },
    },
    {
        "name": "run_enum_check",
        "description": "Run enum/role/status consistency checks across schema, backend, frontend, and seed data. Returns Violation[] as JSON.",
        "input_schema": {
            "type": "object",
            "properties": {
                "enum_name": {"type": "string", "description": "Only check this specific enum name (optional)"},
            },
        },
    },
    {
        "name": "run_route_check",
        "description": "Run frontend-backend route matching verification. Returns IntegrationReport as JSON with mismatches, missing endpoints, unused endpoints.",
        "input_schema": {
            "type": "object",
            "properties": {
                "endpoint_filter": {"type": "string", "description": "Only check routes matching this path pattern (optional)"},
            },
        },
    },
    {
        "name": "run_quality_check",
        "description": "Run quality validators (auth, response-shape, soft-delete, infrastructure). Returns Violation[] as JSON.",
        "input_schema": {
            "type": "object",
            "properties": {
                "checks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Which checks to run: 'enum', 'auth', 'response-shape', 'soft-delete', 'infrastructure'. Defaults to all.",
                },
            },
        },
    },
    {
        "name": "run_spot_check",
        "description": "Run anti-pattern spot checks (FRONT-xxx, BACK-xxx, SLOP-xxx) on the project. Returns Violation[] as JSON.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "check_suppression",
        "description": "Check if a finding signature is suppressed (known false positive). Returns true/false with the suppression reason if suppressed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "check_code": {"type": "string", "description": "The finding check code, e.g. 'SCHEMA-001'"},
                "file_path": {"type": "string", "description": "The file path of the finding"},
                "line": {"type": "integer", "description": "The line number of the finding"},
            },
            "required": ["check_code", "file_path", "line"],
        },
    },
]


def run_agentic_investigation(
    project_root: Path,
    deterministic_results: DeterministicScanResult,
    suppressions: list[SuppressionEntry] | None = None,
    model: str = "claude-opus-4-6",
    max_turns: int = 15,  # Up from 6 — deep investigation needs more turns
) -> list[DeterministicFinding]:
    """Step 2 of Implementation Quality mode: agentic deep investigation.
    
    Claude receives the deterministic scan results and is tasked with
    investigating issues that the scanners CANNOT detect:
    - Business logic correctness
    - State machine completeness
    - Data flow end-to-end correctness
    - Cross-cutting concerns
    
    The agentic session has access to:
    - Standard tools: Read, Grep, Glob, Bash
    - Validator tools: run_schema_check, run_enum_check, run_route_check,
      run_quality_check, run_spot_check, check_suppression
    
    This allows Claude to run TARGETED validator scans during investigation,
    e.g., "I noticed this enum is used in the auth flow — let me run the
    enum check to verify it matches the seed data."
    
    Returns additional findings not caught by deterministic scanners.
    """
    # Build context from deterministic results
    det_summary = _format_deterministic_summary(deterministic_results)
    
    investigation_prompt = f"""You are an IMPLEMENTATION QUALITY auditor investigating a codebase.

## Context: Deterministic Scan Results
The following {len(deterministic_results.findings)} findings were ALREADY detected by
automated scanners. DO NOT re-report these — they are being handled.

{det_summary}

## Your Investigation Focus
Find issues that automated scanners CANNOT detect:

1. **Business logic correctness**: Do handlers implement the right algorithm?
   - Check that calculations, filters, and transformations match requirements
   - Verify conditional logic handles all branches correctly
   
2. **State machine completeness**: Are all valid transitions covered?
   - Check status/state fields: can you reach every valid state?
   - Are invalid transitions properly rejected?
   
3. **Data flow end-to-end**: Does data actually flow correctly?
   - Trace a request from frontend form → API call → backend handler → DB → response → UI display
   - Check: are all fields propagated? Are transformations correct?
   
4. **Cross-cutting concerns**: Logging, error messages, i18n consistency

## Tools Available
You have standard file tools (Read, Grep, Glob, Bash) PLUS validator tools:
- run_schema_check: Run targeted Prisma schema validation
- run_enum_check: Verify enum consistency across layers
- run_route_check: Verify frontend-backend route matching
- run_quality_check: Run auth/shape/soft-delete/infra checks
- run_spot_check: Run anti-pattern detection
- check_suppression: Check if a finding is a known false positive

Use these tools to investigate specific concerns during your analysis.

## Output
Return your findings as a JSON array. Each finding must include:
- check_code: A descriptive code (e.g., "LOGIC-001", "STATE-001", "FLOW-001")
- severity: "critical" | "high" | "medium" | "low"  
- message: What's wrong
- file_path: Where the issue is
- line: Line number
- suggestion: How to fix it

IMPORTANT: Only report findings with HIGH CONFIDENCE (>0.8). Do not guess.
If you're unsure, investigate further using the tools before reporting.
"""
    
    # Call agentic session with extended turns and validator tools
    result = _call_claude_sdk_agentic(
        prompt=investigation_prompt,
        working_directory=str(project_root),
        model=model,
        max_turns=max_turns,
        # NOTE: Implementation must register VALIDATOR_TOOLS alongside standard tools
    )
    
    # Parse findings from agentic response
    return _parse_agentic_findings(result)
```

C) Reclassify `run_audit()` — keep as Mode 2 (PRD Compliance) entry point, not deprecated but clearly labeled:

```python
def run_audit(
    original_prd_path: Path,
    codebase_path: Path,
    previous_report: Optional[AuditReport] = None,
    run_number: int = 1,
    config: Optional[dict[str, Any]] = None,
) -> AuditReport:
    """Mode 2: PRD Compliance audit — checks codebase against PRD acceptance criteria.
    
    NOTE: This is the SUPPLEMENTARY audit mode. For fix cycles, use
    run_deterministic_audit() + run_agentic_investigation() instead (Mode 1).
    
    This mode answers: "Does the build satisfy what the PRD asked for?"
    Mode 1 answers: "Does the build have integration bugs and quality issues?"
    
    The review fleet already does PRD compliance during convergence, so this
    mode is primarily useful for initial build verification and final sign-off.
    """
    # ... existing implementation unchanged ...
```

D) Add `_finding_signature()` helper for suppression matching:

```python
def _finding_signature(f: DeterministicFinding) -> str:
    """Stable signature for suppression matching.
    
    Uses check_code + file_path + line_range (within 10 lines).
    This allows a suppression to survive minor line shifts from code edits.
    """
    line_bucket = (f.line // 10) * 10  # Group lines into buckets of 10
    return f"{f.check_code}:{f.file_path}:{line_bucket}"
```

### 2. `audit_models.py` — Add new data models

**Current state**: 569 lines. Has `AuditFinding`, `AuditScore`, `AuditReport`, `FixTask` for the 6-auditor system.

**Changes**:

A) Add `DeterministicFinding`, `DeterministicScanResult`, `SuppressionEntry` dataclasses (as shown above — can live here or in a new `audit_orchestrator.py`).

B) Add `AuditCycleRecord` for convergence tracking:

```python
@dataclass
class AuditCycleRecord:
    """Record of one audit-fix cycle for convergence tracking."""
    cycle: int
    findings_count: int
    findings_by_severity: dict[str, int]  # {"critical": 2, "high": 5, ...}
    findings_by_scanner: dict[str, int]   # {"schema_validator": 3, ...}
    new_findings: int           # Findings not in previous cycle
    resolved_findings: int      # Findings from previous cycle now gone
    regressed_findings: int     # New findings in files touched by fixes
    fix_files_modified: list[str]
    timestamp: str
    
    @property
    def improvement_pct(self) -> float:
        """Percentage improvement from previous cycle (negative = regression)."""
        if self.findings_count == 0:
            return 100.0
        return (self.resolved_findings - self.new_findings) / max(self.findings_count, 1) * 100

@dataclass
class ConvergenceState:
    """Tracks the full audit-fix loop convergence."""
    cycles: list[AuditCycleRecord]
    suppressions: list[SuppressionEntry]
    max_cycles: int = 5
    plateau_threshold_pct: float = 5.0  # <5% improvement = plateau
    plateau_cycles_to_escalate: int = 2
    
    @property
    def should_escalate(self) -> tuple[bool, str]:
        """Check if the loop should stop."""
        if not self.cycles:
            return False, ""
        
        latest = self.cycles[-1]
        
        # Hard limit
        if len(self.cycles) >= self.max_cycles:
            return True, f"hard_limit: reached {self.max_cycles} cycles"
        
        # All findings resolved
        if latest.findings_count == 0:
            return True, "complete: zero findings"
        
        # Regression
        if latest.regressed_findings > 0:
            return True, f"regression: {latest.regressed_findings} new findings in modified files"
        
        # Plateau detection
        if len(self.cycles) >= self.plateau_cycles_to_escalate:
            recent = self.cycles[-self.plateau_cycles_to_escalate:]
            improvements = [c.improvement_pct for c in recent]
            if all(abs(imp) < self.plateau_threshold_pct for imp in improvements):
                return True, (
                    f"plateau: <{self.plateau_threshold_pct}% improvement "
                    f"for {self.plateau_cycles_to_escalate} consecutive cycles"
                )
        
        return False, ""
```

C) Add conversion functions between `DeterministicFinding` and existing `AuditFinding` (for backward compatibility with fix dispatch):

```python
def deterministic_to_audit_finding(df: DeterministicFinding, index: int) -> AuditFinding:
    """Convert a DeterministicFinding to AuditFinding for fix dispatch compatibility."""
    return AuditFinding(
        finding_id=f"DET-{index:03d}",
        auditor=df.source_scanner,
        requirement_id=df.check_code,
        verdict="FAIL",
        severity=df.severity.upper(),
        summary=df.message,
        evidence=[f"{df.file_path}:{df.line} -- {df.suggestion or df.message}"],
        remediation=df.suggestion,
        confidence=1.0,  # Deterministic = full confidence
    )
```

### 3. `audit_prompts.py` — Separate prompts for Mode 1 (Implementation Quality) and Mode 2 (PRD Compliance)

**Current state**: 425 lines. 6 auditor prompts + scorer prompt. All prompts assume Mode 2 (PRD compliance) as the only audit mode. The interface auditor prompt duplicates `integration_verifier` coverage. The technical auditor prompt duplicates `quality_checks` SDL coverage.

**Changes**:

A) Add `AGENTIC_INVESTIGATION_PROMPT` — the prompt for Mode 1 Step 2 (agentic investigation). This replaces deploying 6 separate LLM auditors for implementation quality:

```python
AGENTIC_INVESTIGATION_PROMPT = """You are an IMPLEMENTATION QUALITY auditor.

## Context
Deterministic scanners have already found {det_count} issues covering:
- Schema integrity, enum consistency, auth flow, response shape,
  soft-delete, route matching, and anti-patterns.

{deterministic_summary}

## Your Job
Find issues that automated scanners CANNOT detect. You have 15 turns
to investigate deeply. Use the validator tools to run targeted checks.

### Investigation Areas
1. BUSINESS LOGIC: Do handlers implement the right algorithm?
2. STATE MACHINES: Are all valid state transitions covered? Invalid ones rejected?
3. DATA FLOW: Trace requests end-to-end — are all fields propagated correctly?
4. CROSS-CUTTING: Logging consistency, error messages, i18n

### Tools
Standard: Read, Grep, Glob, Bash
Validators: run_schema_check, run_enum_check, run_route_check,
            run_quality_check, run_spot_check, check_suppression

### Output
JSON array of findings. Each finding:
{{"check_code": "LOGIC-001", "severity": "high", "message": "...",
  "file_path": "...", "line": 42, "suggestion": "..."}}

Only report HIGH CONFIDENCE findings (>0.8). Investigate before reporting.
"""
```

B) Scope existing LLM auditor prompts to Mode 2 (PRD Compliance) only:

- **`interface` auditor**: REMOVE from default deployment. `integration_verifier` + `RoutePatternEnforcer` covers WIRE-xxx, SVC-xxx, API-xxx, orphan detection, and route matching. Only deployed in Mode 2 if explicitly requested.
- **`technical` auditor**: REMOVE SDL-001/002/003 checks (covered by `quality_checks`). Keep only TECH-xxx architecture pattern verification that requires reading code semantics. Only deployed in Mode 2.
- **`test` auditor**: KEEP. Test execution requires runtime and LLM judgment. Deployed in Mode 2.
- **`mcp_library` auditor**: KEEP. Library API correctness requires Context7 docs. Deployed in Mode 2 at exhaustive depth only.
- **`requirements` auditor**: KEEP for Mode 2 (PRD compliance). Add a context injection section:

```python
REQUIREMENTS_AUDITOR_V2_ADDITIONS = """
## IMPORTANT: Deterministic Findings Already Covered

The following categories are ALREADY checked by deterministic scanners (Mode 1).
DO NOT report findings in these categories — they are handled automatically:

- Schema integrity (SCHEMA-001..008): Missing cascades, bare FKs, invalid defaults, missing indexes
- Enum consistency (ENUM-001..003): Role/status mismatches across layers
- Auth flow (AUTH-001..004): Endpoint mismatches, MFA/refresh flow gaps
- Response shape (SHAPE-001..003): Field naming, array wrapping, field drift
- Soft-delete (SOFTDEL-001..002): Missing filters, unsafe casts
- Route matching (ROUTE-001..004): Frontend/backend endpoint mismatches
- Anti-patterns (FRONT-xxx, BACK-xxx, SLOP-xxx): Code quality patterns

Focus ONLY on PRD COMPLIANCE:
1. Does the feature exist and work as the PRD describes?
2. Are acceptance criteria met?
3. Are edge cases from the PRD handled?
4. Are PRD-specified business rules implemented?
"""
```

- **`prd_fidelity` auditor**: KEEP for Mode 2. Dropped/distorted requirements detection requires PRD vs code semantic comparison.

C) Add `DETERMINISTIC_CONTEXT_INJECTION` template — injected into all LLM auditor prompts when Mode 1 results are available:

```python
DETERMINISTIC_CONTEXT_TEMPLATE = """
## Deterministic Scan Results (Mode 1 — already verified)

The following {count} findings were detected by deterministic scanners.
DO NOT re-report these. Focus your analysis on issues these scanners CANNOT detect.

{findings_summary}
"""
```

D) Update `DEPTH_AUDITOR_MAP` in `audit_team.py` to reflect two-mode architecture:

```python
# Mode 1 (Implementation Quality) does NOT use the auditor map —
# it uses run_deterministic_audit() + run_agentic_investigation().

# Mode 2 (PRD Compliance) uses a reduced auditor map:
DEPTH_AUDITOR_MAP_V2: dict[str, list[str]] = {
    "quick": [],
    "standard": ["requirements"],  # Was: requirements, technical, interface
    "thorough": ["requirements", "technical", "test", "prd_fidelity"],  # Was: all 6
    "exhaustive": ["requirements", "technical", "test", "mcp_library", "prd_fidelity"],
}
```

### 4. `audit_team.py` — Two-mode orchestration, convergence, regression detection

**Current state**: 207 lines. Has `should_terminate_reaudit()` with weak termination logic and `should_skip_scan()` for scan overlap.

**Changes**:

A) Replace `should_terminate_reaudit()` with `ConvergenceState.should_escalate` (see audit_models.py changes above).

B) Add `run_implementation_quality_audit()` — Mode 1 orchestrator:

```python
async def run_implementation_quality_audit(
    project_root: Path,
    config: AuditTeamConfig | None = None,
    previous_convergence: ConvergenceState | None = None,
) -> tuple[DeterministicScanResult, list[DeterministicFinding], ConvergenceState]:
    """Mode 1: Implementation Quality audit.
    
    This is the PRIMARY audit mode for fix cycles.
    
    Step 1: Run deterministic scanner battery (fast, free, reproducible)
    Step 2: Run agentic investigation with validators-as-tools (targeted, deep)
    
    Returns:
        (deterministic_results, agentic_findings, convergence_state)
    """
    convergence = previous_convergence or ConvergenceState(cycles=[], suppressions=[])
    
    # --- Step 1: Deterministic scanner battery ---
    det_result = run_deterministic_audit(
        project_root, 
        suppressions=convergence.suppressions,
    )
    
    # --- Step 2: Agentic investigation (budget-gated) ---
    agentic_findings: list[DeterministicFinding] = []
    if config and config.enabled:
        agentic_findings = run_agentic_investigation(
            project_root=project_root,
            deterministic_results=det_result,
            suppressions=convergence.suppressions,
            max_turns=15,  # Up from 6 — deep investigation needs more turns
        )
    
    return det_result, agentic_findings, convergence


async def run_prd_compliance_audit(
    project_root: Path,
    prd_path: Path,
    requirements_path: str | None = None,
    config: AuditTeamConfig | None = None,
    deterministic_context: DeterministicScanResult | None = None,
) -> AuditReport | None:
    """Mode 2: PRD Compliance audit.
    
    This is the SUPPLEMENTARY audit mode. Runs after Mode 1 converges,
    or on explicit request for PRD compliance verification.
    
    Deploys LLM auditors (requirements, prd_fidelity, optionally test)
    to check that the build satisfies the PRD's acceptance criteria.
    
    If deterministic_context is provided, injects it into LLM prompts
    so auditors don't re-report already-known issues.
    """
    if not config or not config.enabled:
        return None
    
    # Select auditors for Mode 2
    auditors = get_auditors_for_depth(str(config.depth))  # Uses DEPTH_AUDITOR_MAP_V2
    if not auditors:
        return None
    
    # Build agent definitions with deterministic context injection
    agent_defs = build_auditor_agent_definitions(
        auditors,
        requirements_path=requirements_path,
        prd_path=str(prd_path),
        deterministic_context=deterministic_context,  # NEW param
    )
    
    # ... deploy auditors, collect findings, score, return report ...
```

C) Add regression detection:

```python
def detect_regressions(
    previous: DeterministicScanResult,
    current: DeterministicScanResult,
    modified_files: list[str],
) -> list[DeterministicFinding]:
    """Find NEW findings in files that were modified by the fix cycle.
    
    A regression is a finding that:
    1. Was NOT in the previous scan result
    2. IS in a file that was modified by the fix cycle
    """
    prev_sigs = {_finding_signature(f) for f in previous.findings}
    regressions = []
    for f in current.findings:
        if _finding_signature(f) not in prev_sigs:
            # New finding — is it in a modified file?
            if any(f.file_path.endswith(mf) or mf.endswith(f.file_path) for mf in modified_files):
                regressions.append(f)
    return regressions
```

D) Remove `should_skip_scan()` and `_SCAN_AUDITOR_OVERLAP` — no longer needed since deterministic scanners are the primary engine, not a post-hoc overlay.

### 5. `fix_prd_agent.py` — Scoped, verifiable fix PRDs from deterministic findings

**Current state**: 550 lines. Generates fix PRDs from `Finding` objects (LLM-produced). The output is a full markdown PRD with bounded contexts, entity sections, and regression prevention.

**Changes**:

A) Add new function `generate_deterministic_fix_prd()`:

```python
def generate_deterministic_fix_prd(
    project_root: Path,
    findings: list[DeterministicFinding],
    cycle: int,
    convergence: ConvergenceState,
    original_prd_path: Path | None = None,
) -> str:
    """Generate a fix PRD scoped to deterministic findings.
    
    Key differences from generate_fix_prd():
    1. Each fix task has an exact file:line + code snippet + suggestion
    2. Each fix task has a verification command
    3. Regression watchlist is computed from convergence state
    4. No vague "improve UX" tasks — every task is concrete
    """
    sections = []
    
    # Group findings by file (fixes are file-scoped)
    by_file: dict[str, list[DeterministicFinding]] = {}
    for f in findings:
        by_file.setdefault(f.file_path, []).append(f)
    
    # Sort files by max severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_files = sorted(
        by_file.items(),
        key=lambda item: min(severity_order.get(f.severity, 99) for f in item[1]),
    )
    
    # Header
    sections.append(f"# Fix Cycle {cycle} — {len(findings)} Deterministic Findings\n")
    
    # Summary table
    sections.append("## Findings Summary\n")
    sections.append("| # | Check | Severity | File | Line | Issue |")
    sections.append("|---|-------|----------|------|------|-------|")
    for i, f in enumerate(findings, 1):
        sections.append(f"| {i} | {f.check_code} | {f.severity} | `{f.file_path}` | {f.line} | {f.message[:80]} |")
    
    # Fix tasks (one per file group)
    sections.append("\n## Fix Tasks\n")
    for file_path, file_findings in sorted_files:
        sections.append(f"### `{file_path}`\n")
        for f in file_findings:
            sections.append(f"**{f.id}** [{f.check_code}] (severity: {f.severity})")
            sections.append(f"- **Line {f.line}**: {f.message}")
            if f.suggestion:
                sections.append(f"- **Fix**: {f.suggestion}")
            sections.append(f"- **Verify**: Re-run `{f.verification_command}`")
            sections.append("")
    
    # Regression watchlist
    if convergence.cycles:
        all_modified = set()
        for c in convergence.cycles:
            all_modified.update(c.fix_files_modified)
        if all_modified:
            sections.append("## Regression Watchlist\n")
            sections.append("Files modified in previous fix cycles — verify no new findings:\n")
            for fp in sorted(all_modified):
                sections.append(f"- `{fp}`")
    
    # Verification criteria
    sections.append("\n## Verification Criteria\n")
    sections.append("After applying fixes, re-run the deterministic scanner suite.")
    sections.append("**Pass condition**: All findings listed above are resolved AND zero new findings in modified files.")
    sections.append("**Fail condition**: Any new finding in a modified file = REGRESSION. Stop and report.\n")
    
    return "\n".join(sections)
```

B) Keep `generate_fix_prd()` for backward compatibility but have it delegate to `generate_deterministic_fix_prd()` when given `DeterministicFinding` objects.

### 6. `cli.py` — Wire the two-mode audit pipeline

**Current state**: The audit is invoked in two places:
- Per-milestone audit at line ~2142: `_run_audit_loop()` after each milestone
- Final cross-milestone audit at line ~2448: `_run_milestone_audit()` with interface-only

**Changes**:

A) In `_run_audit_loop()` (line ~2691), replace with two-mode pipeline:

```python
async def _run_audit_loop(
    # ... existing params ...
) -> tuple[AuditReport | None, float]:
    """Run the upgraded two-mode audit-fix-reaudit cycle.
    
    Mode 1 (Implementation Quality) is the PRIMARY mode for fix cycles.
    Mode 2 (PRD Compliance) runs optionally after Mode 1 converges.
    """
    convergence = ConvergenceState(cycles=[], suppressions=_load_suppressions(audit_dir))
    total_cost = 0.0
    previous_det_result: DeterministicScanResult | None = None
    
    for cycle in range(1, config.audit_team.max_reaudit_cycles + 1):
        # === MODE 1: Implementation Quality ===
        
        # Step 1: Deterministic scanner battery
        det_result = run_deterministic_audit(project_root, convergence.suppressions)
        
        # Step 2: Agentic investigation (budget-gated, validators-as-tools)
        agentic_findings = []
        if config.audit_team.enabled and _budget_allows(total_cost, config):
            agentic_findings = run_agentic_investigation(
                project_root, det_result,
                suppressions=convergence.suppressions,
                max_turns=15,
            )
        
        # Merge all findings
        all_findings = det_result.findings + agentic_findings
        
        # Regression check (cycle 2+)
        if previous_det_result:
            regressions = detect_regressions(
                previous_det_result, det_result,
                convergence.cycles[-1].fix_files_modified if convergence.cycles else [],
            )
            if regressions:
                _log_regression(regressions, cycle)
                break
        
        # Record cycle
        cycle_record = _build_cycle_record(cycle, det_result, previous_det_result)
        convergence.cycles.append(cycle_record)
        
        # Convergence check
        should_stop, reason = convergence.should_escalate
        if should_stop:
            _log_escalation(reason, cycle, det_result)
            break
        
        # No findings? Done with Mode 1.
        if not all_findings:
            break
        
        # Generate scoped fix PRD from ALL findings (deterministic + agentic)
        fix_prd = generate_deterministic_fix_prd(
            project_root, all_findings, cycle, convergence,
        )
        
        # Execute fixes
        modified_files = await _execute_fix_prd(fix_prd, ...)
        convergence.cycles[-1].fix_files_modified = modified_files
        
        previous_det_result = det_result
    
    # === MODE 2: PRD Compliance (optional, after Mode 1 converges) ===
    prd_report = None
    if config.audit_team.enabled and prd_path:
        prd_report = await run_prd_compliance_audit(
            project_root, prd_path,
            requirements_path=requirements_path,
            config=config,
            deterministic_context=det_result,  # Pass Mode 1 results as context
        )
    
    # Save convergence state + suppressions
    _save_convergence(audit_dir, convergence)
    return _build_final_report(convergence, prd_report), total_cost
```

B) Update `_run_milestone_audit()` (line ~2528) to use Mode 1 by default:
- Replace the 6-auditor LLM deployment with `run_implementation_quality_audit()`
- The deterministic scanners run FIRST, then agentic investigation with validators-as-tools
- LLM auditor findings (Mode 2) are injected as context when available

C) Update the final cross-milestone integration audit (line ~2448):
- Replace `auditors_override=["interface"]` with a Mode 1 deterministic scan
- `integration_verifier.verify_integration()` already covers what the interface-only audit did

D) Register validator tools for the agentic session:
- Add `_execute_validator_tool()` handler alongside existing `_execute_audit_tool()` in `audit_agent.py`
- The handler dispatches to `run_schema_validation()`, `run_quality_validators()`, `verify_integration()`, `run_spot_checks()` based on tool name
- Results are formatted as JSON for the agentic session to consume

E) Add CLI-level false positive suppression commands (future enhancement — for now, manual `.agent-team/suppressions.json` editing).

## False Positive Suppression System

### Storage

File: `.agent-team/suppressions.json`

```json
{
  "version": 1,
  "entries": [
    {
      "signature": "UI-004:apps/web/src/components/layout/sidebar.tsx:80",
      "check_code": "UI-004",
      "reason": "SVG path coordinate data, not CSS spacing. Tailwind 3 = 12px which IS on 4px grid.",
      "suppressed_by": "human",
      "suppressed_at": "2026-03-15T10:00:00Z",
      "cycle": 1
    }
  ]
}
```

### Signature Computation

```python
def _finding_signature(f: DeterministicFinding) -> str:
    """Stable signature that survives minor line shifts."""
    line_bucket = (f.line // 10) * 10
    return f"{f.check_code}:{f.file_path}:{line_bucket}"
```

Line bucketing (groups of 10) ensures a suppression survives when nearby code edits shift the line number slightly.

### Auto-suppression

After a fix cycle, if a finding was marked as "false positive" by the fixer (via a structured response), it's automatically added to suppressions.json with `suppressed_by: "auto-verified"`.

### Human override

The `.agent-team/suppressions.json` file is human-editable. A human can:
- Add suppressions for known false positives
- Remove suppressions if a previously-suppressed pattern becomes a real issue
- Override `suppressed_by` to `"human"` for audit trail

## Convergence Guarantees

### Tracking

Each cycle records:
- `findings_count`: Total active findings (after suppression)
- `new_findings`: Findings not in previous cycle's set
- `resolved_findings`: Findings from previous cycle no longer present
- `regressed_findings`: New findings in files modified by fixes

### Plateau Detection

```
Plateau = abs(improvement_pct) < 5.0 for 2 consecutive cycles

improvement_pct = (resolved - new) / max(findings_count, 1) * 100
```

When plateau detected: 
1. Log the plateau with full finding list
2. Classify remaining findings as "unfixable by current approach"
3. Generate an escalation report (not another fix PRD)
4. Stop the loop

### Regression Detection

After each fix cycle, before generating the next fix PRD:

```
previous_sigs = {signature(f) for f in previous_scan.findings}
current_sigs = {signature(f) for f in current_scan.findings}

new_in_modified = [f for f in current_scan.findings 
                   if signature(f) not in previous_sigs
                   and f.file_path in modified_files]

if new_in_modified:
    STOP — regression detected
```

### Hard Limits

| Parameter | Default | Config Key |
|-----------|---------|------------|
| Max fix cycles | 5 | `audit_team.max_reaudit_cycles` |
| Plateau threshold | 5% | `audit_team.plateau_threshold_pct` (new) |
| Plateau cycles | 2 | `audit_team.plateau_cycles_to_escalate` (new) |
| LLM budget cap | 30% of total | `audit_team.llm_budget_pct` (new) |
| Max findings per fix PRD | 20 | `audit_team.max_findings_per_fix_task` (existing) |

### Config Changes (`config.py`)

Add to `AuditTeamConfig`:

```python
@dataclass
class AuditTeamConfig:
    enabled: bool = False
    max_parallel_auditors: int = 3          # Reduced from 5 (fewer LLM auditors in Mode 2)
    max_reaudit_cycles: int = 5             # Increased from 3 (but with convergence)
    fix_severity_threshold: str = "MEDIUM"
    score_healthy_threshold: float = 90.0
    score_degraded_threshold: float = 70.0
    context7_prefetch: bool = True
    max_findings_per_fix_task: int = 5
    skip_overlapping_scans: bool = True
    # New fields for two-mode architecture:
    audit_mode: str = "implementation_quality"  # "implementation_quality" | "prd_compliance" | "both"
    agentic_max_turns: int = 15             # Up from 6 — deep investigation needs more turns
    agentic_model: str = "claude-opus-4-6"  # Model for agentic investigation
    plateau_threshold_pct: float = 5.0
    plateau_cycles_to_escalate: int = 2
    llm_budget_pct: float = 30.0            # Max % of total budget for LLM auditors/agentic
    deterministic_scan_enabled: bool = True  # Can disable for debugging
    suppression_file: str = "suppressions.json"
```

The `audit_mode` field controls which modes run:
- `"implementation_quality"` (default): Mode 1 only. Deterministic scanners + agentic investigation. Best for fix cycles.
- `"prd_compliance"`: Mode 2 only. LLM auditors check PRD acceptance criteria. Best for initial build verification.
- `"both"`: Mode 1 first, then Mode 2 after Mode 1 converges. Best for exhaustive final audit.

## Migration Strategy

1. **Phase A (non-breaking)**: Add all Mode 1 infrastructure alongside existing code:
   - `DeterministicFinding`, `DeterministicScanResult`, `ConvergenceState`, `AuditCycleRecord`, `SuppressionEntry` dataclasses
   - `run_deterministic_audit()` function
   - `run_agentic_investigation()` function with VALIDATOR_TOOLS
   - `generate_deterministic_fix_prd()` function
   - `detect_regressions()` function
   - No existing behavior changes. Old audit paths still work.

2. **Phase B (wiring)**: Modify `_run_audit_loop()` in `cli.py` to use two-mode pipeline:
   - Mode 1 (Implementation Quality) becomes the default for fix cycles
   - Deterministic scanners run first, then agentic investigation with validators-as-tools
   - `max_turns` increased from 6 to 15 for agentic sessions
   - Validator tools registered alongside standard Read/Grep/Glob tools
   - Mode 2 (PRD Compliance) runs after Mode 1 converges
   - Add suppression loading/saving, convergence tracking

3. **Phase C (mode separation)**: Reclassify `run_audit()` as Mode 2 (PRD Compliance) entry point. Remove `interface` auditor from default Mode 2 deployment (covered by Mode 1 deterministic scanners). Reduce `technical` auditor scope in Mode 2. Update `DEPTH_AUDITOR_MAP` to `DEPTH_AUDITOR_MAP_V2`. Add `audit_mode` config field.

## ArkanPM Retrospective: What This Design Fixes

| ArkanPM Failure | Root Cause | Fix in This Design |
|----------------|------------|-------------------|
| 62 real bugs missed (routes, schema, auth, enums) | **Auditing at the wrong level** — the audit checked PRD acceptance criteria, not implementation quality. Routes, schema integrity, auth flow divergence are never stated as ACs. | **Two explicit modes**: Mode 1 (Implementation Quality) uses deterministic validators + agentic investigation. Mode 2 (PRD Compliance) uses LLM auditors. Mode 1 is PRIMARY for fix cycles. |
| 8 cycles on Tailwind spacing false positives | No suppression mechanism | `suppressions.json` + line-bucketed signatures |
| Shallow agentic investigation (max_turns=6) | Agentic session too short, no access to validators | `run_agentic_investigation()` with `max_turns=15` and validators-as-tools (run_schema_check, run_enum_check, run_route_check, run_quality_check, run_spot_check) |
| 90→43 findings then regression | No regression gate | `detect_regressions()` + mandatory re-scan after each fix |
| 12 runs, 50+ milestones | No convergence enforcement | `ConvergenceState.should_escalate` with hard limit + plateau detection |
| Vague fix PRDs ("improve UX") | LLM-generated findings lack concrete locations | `DeterministicFinding` with exact file:line + suggestion + verification command |
| Two parallel audit systems | `audit_agent.py` and `audit_team.py` both active | Unified under Mode 1 (`run_deterministic_audit()` + `run_agentic_investigation()`) and Mode 2 (`run_prd_compliance_audit()`) |
| Review fleet already checks PRD compliance | Audit duplicated the review fleet's PRD compliance work during fix cycles | Mode 2 (PRD Compliance) is now SUPPLEMENTARY, runs only after Mode 1 converges. Fix cycles use Mode 1 exclusively. |

## Pre-Fix Regression Gate (from Forensics Root Cause #3)

The forensics analysis (`AUDIT_FORENSICS.md`, section B) identified that the current regression detection is **post-hoc** — it detects regressions in the re-audit AFTER the damage is done. The fix PRD's "Regression Prevention" section is advisory markdown, not an enforced constraint.

The upgraded system adds a **pre-fix regression gate** that verifies fixes BEFORE accepting them:

```
BEFORE fix milestone executes:
  1. Run test suite → capture baseline: {passing, failing, total}
  2. Snapshot deterministic scan results → baseline_findings

AFTER fix milestone executes:
  3. Run test suite → capture post-fix: {passing, failing, total}
  4. Run deterministic scan → post_fix_findings
  5. REGRESSION CHECK:
     a. Test regression: post_fix.failing > baseline.failing → REJECT FIX
     b. Finding regression: new findings in modified files → REJECT FIX
     c. AC regression: previously-passing ACs now fail → REJECT FIX
  6. If REJECT: log which fix task caused the regression, revert files, continue to next fix task
  7. If ACCEPT: commit fix, update convergence state
```

This is **enforcement, not advisory**. The fix is rejected if it introduces regressions. The key change from the current system:

| Current | Upgraded |
|---------|----------|
| Regression detected in re-audit (post-hoc) | Regression detected immediately after each fix task (pre-commit) |
| No rollback mechanism | Fix task reverted if regression detected |
| Advisory "DO NOT regress" in fix PRD markdown | Enforced gate: test suite + deterministic scan before/after |
| `should_terminate_reaudit()` stops the loop after damage | Pre-fix gate prevents the damage entirely |

### Implementation in `_run_audit_loop()`:

The fix execution step becomes:

```python
# Phase 3: Execute fixes WITH regression gate
for fix_task in fix_tasks:
    # Pre-fix baseline
    baseline_test_results = await _run_test_suite(project_root)
    baseline_scan = run_deterministic_audit(project_root, convergence.suppressions)
    
    # Execute fix
    modified_files = await _execute_single_fix_task(fix_task, ...)
    
    # Post-fix verification
    post_test_results = await _run_test_suite(project_root)
    post_scan = run_deterministic_audit(project_root, convergence.suppressions)
    
    # Regression gate
    test_regressions = post_test_results.failing - baseline_test_results.failing
    finding_regressions = detect_regressions(baseline_scan, post_scan, modified_files)
    
    if test_regressions > 0 or finding_regressions:
        _log_fix_rejection(fix_task, test_regressions, finding_regressions)
        await _revert_fix(modified_files)  # git checkout the modified files
        continue  # Skip this fix, try the next one
    
    # Fix accepted
    accepted_files.extend(modified_files)
```

### Test Suite Runner

The test suite runner is a lightweight wrapper:

```python
@dataclass
class TestSuiteResult:
    passing: int
    failing: int
    total: int
    failing_tests: list[str]  # Names of failing tests
    duration_seconds: float

async def _run_test_suite(project_root: Path) -> TestSuiteResult:
    """Run the project's test suite and parse results.
    
    Auto-detects: npm test, pnpm test, pytest, go test, etc.
    Returns structured results for regression comparison.
    """
    # ... detect test command, run, parse output ...
```

## Handling UX/Missing Feature Findings (from Forensics Root Cause #4)

The forensics report (section D) identified that `missing_feature` and `ux` findings are structurally unfixable by the current system:
- `ux` findings have verdict `SKIP`, are excluded from fix_candidates, never become fix tasks
- `missing_feature` findings generate `FEAT-NNN` items but the builder can't scaffold new features

The design handles this by:

1. **Mode 1 (Implementation Quality) does not generate UX/missing_feature findings.** Deterministic scanners and agentic investigation produce concrete, code-level findings only. There is no "vague UX improvement" category.

2. **Mode 2 (PRD Compliance) reclassifies unfixable findings.** When the LLM auditor produces a finding that maps to `missing_feature` or `ux`:
   - If it's a genuinely missing feature (no code exists): classify as `MANUAL_ACTION_REQUIRED` (not a fix candidate)
   - If it's a UX issue (requires human judgment): classify as `HUMAN_REVIEW` (not a fix candidate)
   - Both are excluded from `fix_candidates` AND from the score denominator
   - Both are reported in a separate "Manual Action Items" section of the audit report

3. **Convergence tracking ignores unfixable findings.** The `ConvergenceState` counts only fixable findings for plateau/regression detection. The 12 UX findings that persisted across all 12 ArkanPM runs would be excluded from the convergence calculation.

## Forensics Cross-Reference

Every root cause from `AUDIT_FORENSICS.md` maps to a specific design element:

| Forensics Root Cause | Section | Design Element | Status |
|---------------------|---------|---------------|--------|
| RC#1: Detection gap (0/62 real bugs detected) | Core Insight: Two Audit Modes | Mode 1 uses deterministic validators that detect all 62 bug categories | Designed |
| RC#2: False positive pollution (9 wasted cycles) | False Positive Suppression System | `suppressions.json` with line-bucketed signatures + auto-suppression | Designed |
| RC#3: Fix regression (11 regressions in run 12) | Pre-Fix Regression Gate | Test suite + deterministic scan before/after each fix task, with revert on regression | Designed |
| RC#4: UX/missing_feature unfixable (14 findings constant) | Handling UX/Missing Feature Findings | Reclassify as MANUAL_ACTION_REQUIRED, exclude from fix candidates + convergence | Designed |
| RC#5: No cycle memory (re-scan from scratch) | Convergence Guarantees | `ConvergenceState` persists across cycles, suppressions carry forward | Designed |
| RC#6: No cost control (50+ milestones) | Hard Limits table | `max_reaudit_cycles=5`, `llm_budget_pct=30`, plateau detection, budget-based termination | Designed |

### Forensics Recommendation Coverage

| Forensics Recommendation | Design Coverage |
|-------------------------|----------------|
| 1. Add code-level integration scanners | Mode 1 Step 1: `schema_validator`, `integration_verifier`, `quality_validators`, `quality_checks` |
| 2. Add pre-fix regression gates | Pre-Fix Regression Gate section: test suite + scan before/after, revert on failure |
| 3. Add scanner memory (suppress re-detection) | `SuppressionEntry` + `suppressions.json` + `ConvergenceState` persists across cycles |
| 4. Make UX/missing_feature actionable or stop counting them | Reclassify as `MANUAL_ACTION_REQUIRED`, exclude from fix candidates and convergence |
| 5. Add budget-based termination | `llm_budget_pct=30`, `max_reaudit_cycles=5`, plateau detection after 2 cycles |
| 6. Expose validators as agentic tools | Mode 1 Step 2: `VALIDATOR_TOOLS` (run_schema_check, run_enum_check, run_route_check, etc.) |
| 7. Increase agentic investigation depth | `agentic_max_turns=15` (up from 6) |
| 8. Two-mode architecture | Mode 1 (Implementation Quality, primary) + Mode 2 (PRD Compliance, supplementary) |
