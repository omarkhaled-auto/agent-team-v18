# Builder Architecture Map

Generated: 2026-04-01
Purpose: Complete map of the agent-team-v15 builder system for upgrade planning.
Scope: All injection points where new validators and gates can prevent the 62-bug class observed in the Facilities Management build.

---

## 1. Pipeline Flow

The builder operates in two primary modes. Both share the same post-orchestration scan infrastructure.

### 1A. Single-Shot / Interactive Mode (`cli.py:_run_single`, `cli.py:_run_interactive`)

```
main() (cli.py:5210)
  |
  +-- Phase 0: Interview (cli.py:5457-5511)
  |     run_interview() -> INTERVIEW.md
  |
  +-- Phase 0.25: Constraint Extraction (cli.py:5519-5527)
  |     extract_constraints() -> list[ConstraintEntry]
  |
  +-- Phase 0.5: Codebase Map (cli.py:5562-5611)
  |     generate_codebase_map() -> summary string
  |
  +-- Phase 0.5b: Contract Registry Loading from MCP (cli.py:5620-5670)
  |
  +-- Phase 0.6: Design Reference Extraction (cli.py:5675-5800+)
  |     run_design_extraction_with_retry() -> UI_REQUIREMENTS.md
  |
  +-- Orchestrator Session (cli.py:603-736)
  |     build_orchestrator_prompt() -> single ClaudeSDKClient session
  |     _process_response() handles streaming
  |
  +-- Post-Orchestration Scans (cli.py:6274-8424)
       [see Section 1C below]
```

### 1B. PRD Milestone Mode (`cli.py:_run_prd_milestones`)

```
main() (cli.py:5210)
  |
  +-- Phases 0 through 0.6: [identical to single-shot]
  |
  +-- Phase 1: PRD Decomposition (cli.py:1074-1186)
  |     build_decomposition_prompt() -> MASTER_PLAN.md
  |     parse_master_plan() -> MasterPlan with milestones
  |
  +-- Phase 1.5: Tech Stack Research (cli.py:1227-1255)
  |     _run_tech_research() -> TECH_RESEARCH.md via Context7 MCP
  |
  +-- Phase 2: Milestone Execution Loop (cli.py:1279-2098)
  |     FOR EACH milestone in dependency order:
  |       |
  |       +-- Build milestone context (cli.py:1357-1486)
  |       |     _build_completed_milestones_context() -> predecessor summaries
  |       |     build_milestone_execution_prompt() -> scoped prompt
  |       |
  |       +-- Orchestrator Session (cli.py:1497-1503)
  |       |     Fresh ClaudeSDKClient per milestone
  |       |
  |       +-- Health Gate (cli.py:1559-1626)
  |       |     mm.check_milestone_health() -> ConvergenceReport
  |       |     _run_review_only() recovery if needed
  |       |
  |       +-- Handoff Documentation (cli.py:1628-1707)
  |       |     generate_milestone_handoff_entry()
  |       |     _generate_handoff_details() sub-orchestrator
  |       |     validate_handoff_completeness()
  |       |
  |       +-- API Contract Extraction (cli.py:1710-1732)
  |       |     extract_api_contracts() -> API_CONTRACTS.json
  |       |
  |       +-- Wiring Completeness Check (cli.py:1735-1754)
  |       |     compute_wiring_completeness()
  |       |
  |       +-- Mock Data Scan (cli.py:1757-1785)
  |       |     run_mock_data_scan() -> violations
  |       |     _run_mock_data_fix() if violations found
  |       |
  |       +-- UI Compliance Scan (cli.py:1788-1816)
  |       |     run_ui_compliance_scan() -> violations
  |       |     _run_ui_compliance_fix() if violations found
  |       |
  |       +-- Final Health Gate Decision (cli.py:1819-1863)
  |       |     Audit score override check
  |       |
  |       +-- Wiring Verification (cli.py:1866-1894)
  |       |     mm.verify_milestone_exports() -> wiring issues
  |       |     _run_milestone_wiring_fix() if issues found
  |       |
  |       +-- Integration Verification Gate (cli.py:1900-1965)
  |       |     verify_integration() -> IntegrationReport
  |       |     Block or warn based on config mode
  |       |
  |       +-- Per-Milestone Audit (cli.py:1967-1985)
  |       |     _run_audit_loop() if audit_team enabled
  |       |
  |       +-- Mark Complete + Cache (cli.py:1988-2007)
  |       +-- Update Interface Registry (cli.py:2009-2021)
  |       +-- Contract Verification Checkpoint (cli.py:2023-2045)
  |       +-- Phase-Boundary Docker Checkpoint (cli.py:2068-2091)
  |
  +-- Cross-Milestone Integration Audit (cli.py:2100-2123)
  |
  +-- Post-Orchestration Scans (cli.py:6274-8424)
       [see Section 1C below]
```

### 1C. Post-Orchestration Scans (Both Modes)

All scans run after the main orchestration completes. Each scan follows the pattern: detect violations -> optionally run fix pass -> re-scan. The `max_scan_fix_passes` config controls multi-pass.

```
Post-Orchestration Phase (cli.py:6274-8424)
  |
  +-- TASKS.md Diagnostic (cli.py:6320)
  +-- Artifact Verification Gate (cli.py:6356-6400)
  |     Checks REQUIREMENTS.md exists
  |     _run_artifact_recovery() if missing
  |
  +-- Contract Health Check (cli.py:6401-6453)
  |     Verifies CONTRACTS.json exists
  |     _run_contract_generation() recovery if missing
  |
  +-- Convergence Health Check (cli.py:6454-6735)
  |     _check_convergence_health() -> ConvergenceReport
  |     _run_review_only() recovery if failed/degraded
  |
  +-- Mock Data Scan (cli.py:6736-6782)           [MOCK-001]
  +-- UI Compliance Scan (cli.py:6784-6830)       [UI-001..004]
  +-- Integrity Scans (cli.py:6832-6965)
  |     +-- Deployment scan                        [DEPLOY-001..004]
  |     +-- Asset scan                             [ASSET-001..003]
  |     +-- PRD Reconciliation (LLM-based)
  |
  +-- Database Integrity Scans (cli.py:6967-7120)
  |     +-- Dual ORM scan                          [DB-001..003]
  |     +-- Default value scan                     [DB-004..005]
  |     +-- Relationship scan                      [DB-006..008]
  |
  +-- API Contract Scan (cli.py:7121-7170)         [API-001..003]
  +-- Contract Compliance Scans (cli.py:7172-7244) [CONTRACT-001..004]
  +-- Contract Report Population (cli.py:7246-7308)
  +-- Contract Compliance Matrix (cli.py:7309-7337)
  +-- Artifact Registration via MCP (cli.py:7339-7375)
  +-- Silent Data Loss Scan (cli.py:7377-7423)     [SDL-001]
  +-- Endpoint XREF Scan (cli.py:7425-7479)        [XREF-001..002, API-004]
  +-- Handler Completeness Scan (cli.py:7481-7545)  [STUB-001]
  +-- Entity Coverage Scan (cli.py:7547-7581)       [ENTITY-001..003]
  +-- Cross-Service Event Scan (cli.py:7583-7604)   [XSVC-001..002]
  +-- API Completeness Scan (cli.py:7606-7621)      [API-001..002]
  +-- Runtime Verification (cli.py:7623-7671)       [Docker build+start+test]
  +-- E2E Testing Phase (cli.py:7673-7965)          [Backend API + Playwright]
  +-- E2E Quality Scan (cli.py:7966-7987)
  +-- Browser MCP Interactive Testing (cli.py:7989-8325)
  +-- Post-Orchestration Verification (cli.py:8347-8424)
       verify_task_completion() from verification.py
```

---

## 2. Gate Points

Every existing gate/checkpoint with file:line references.

### Hard Gates (Blocking -- halt pipeline on failure)

| Gate | Location | What It Checks | Consequence of Failure |
|------|----------|----------------|----------------------|
| Spec Validation Gate | agents.py:516-518 (prompt) | REQUIREMENTS.md matches user request | Re-deploy planner until PASS |
| Contract Generator Gate | agents.py:681-685 (prompt) | CONTRACTS.json created | Retry once, then warn |
| Review Fleet Gate (GATE 5) | agents.py:217 (prompt) | review_cycles > 0 | Python runtime forces recovery pass |
| Health Gate (milestone) | cli.py:1559-1626 | convergence_ratio >= threshold | _run_review_only() recovery, then FAIL |
| Integration Gate (block mode) | cli.py:1927-1942 | No HIGH severity mismatches | Mark milestone FAILED |
| Convergence Health Check | cli.py:6454-6735 | review_cycles > 0 AND ratio >= threshold | _run_review_only() recovery |
| Artifact Verification Gate | cli.py:6356-6400 | REQUIREMENTS.md exists | _run_artifact_recovery() |
| Contract Health Check | cli.py:6401-6453 | CONTRACTS.json exists | _run_contract_generation() recovery |
| E2E Pass Rate Gate | config.py:369 | e2e_pass_rate >= 0.7 | Skip browser testing |
| Wiring Completeness Gate | config.py:430 | wiring_ratio >= threshold | Warning only |

### Soft Gates (Advisory -- warn but continue)

| Gate | Location | What It Checks |
|------|----------|----------------|
| Mock Data Scan | cli.py:1757, 6740 | No of()/delay()/mockData in services |
| UI Compliance Scan | cli.py:1788, 6788 | No hardcoded colors/fonts |
| Integration Verification (warn mode) | cli.py:1900-1965 | Frontend calls match backend endpoints |
| All Integrity Scans | cli.py:6832-7120 | Deployment, asset, database checks |
| All Contract Scans | cli.py:7172-7244 | CONTRACT-001 through CONTRACT-004 |
| Handoff Completeness | cli.py:1672-1703 | Milestone handoff sections filled |
| Context Budget Warning | agents.py:30-60 | Prompt < 25% of context window |

### Orchestrator-Level Gates (Prompt-Enforced, Not Python-Enforced)

| Gate | Location | What It Controls |
|------|----------|-----------------|
| GATE 1: Review Authority | agents.py:205-209 | Only reviewers/testers mark [x] |
| GATE 2: Mandatory Re-Review | agents.py:211-212 | Debug fix -> re-review always |
| GATE 3: Cycle Tracking | agents.py:213-214 | review_cycles increment |
| GATE 4: Depth != Thoroughness | agents.py:215-216 | Review quality independent of depth |
| Mock Data Gate (coding wave) | agents.py:446-449 | Scan between coding and review |
| Stub Handler Prohibition | agents.py:289-332 | No log-only event handlers |

---

## 3. Prompt Sections (Orchestrator System Prompt)

The orchestrator system prompt in `agents.py` is the largest single piece of the system. Every section with what it controls:

| Section | Lines (approx) | Purpose | Controls |
|---------|------|---------|----------|
| SECTION 0: Codebase Map | 73-83 | Use codebase map for file assignment | Agent file targeting |
| SECTION 1: Requirements Document Protocol | 85-176 | REQUIREMENTS.md structure and lifecycle | Planning output format, review process |
| SECTION 2: Depth Detection & Fleet Scaling | 178-197 | Agent counts per depth level | Fleet sizes |
| SECTION 3: The Convergence Loop | 199-282 | Core build-review-fix loop with 5 gates | Quality enforcement, completion criteria |
| SECTION 3a: Stub Handler Prohibition | 289-332 | Zero-tolerance for log-only handlers | Handler implementation quality |
| SECTION 3b: Task Assignment Phase | 335-358 | TASKS.md creation and lifecycle | Work decomposition |
| SECTION 3c: Smart Task Scheduling | 362-377 | Wave-based parallel execution | Task parallelism, conflict detection |
| SECTION 3d: Progressive Verification | 379-387 | Per-task verification after completion | Continuous quality checks |
| SECTION 4: PRD Mode | 390-472 | Two-phase PRD decomposition + execution | Milestone workflow |
| SECTION 5: Adversarial Review Protocol | 474-496 | Review fleet instructions | Review quality |
| SECTION 6: Fleet Deployment Instructions | 498-620 | Per-agent-type deployment rules | Agent behavior |
| SECTION 6b: Display & Budget Configuration | 627-643 | Display and budget controls | Cost management |
| SECTION 7: Workflow Execution | 645-720 | Step-by-step workflow (steps 0-9) | Pipeline sequencing |
| SECTION 8: Constraint Enforcement | 732-748 | User constraint compliance | Prohibition/requirement enforcement |
| SECTION 9: Cross-Service Standards (v16) | 750-848 | Implementation quality standards | Code quality rules |
| SECTION 10: Serialization Convention | 850-898 | camelCase/snake_case handling | Data format consistency |
| Orchestrator ST Instructions | (injected) | Sequential thinking at decision points | Reasoning quality |

---

## 4. Validator Inventory

Every existing validator/checker with what it checks.

### Static Analysis Scanners (quality_checks.py)

| Scanner | Function | Violation Codes | What It Checks |
|---------|----------|-----------------|----------------|
| Spot Checks | `run_spot_checks()` :1815 | FRONT-001..021, BACK-001..010, SLOP-001..005 | Anti-pattern regex checks on all source files |
| Mock Data Scan | `run_mock_data_scan()` :1869 | MOCK-001 | of(), delay(), mockData, fakeData in service files |
| Handler Completeness | `run_handler_completeness_scan()` :2105 | STUB-001 | Log-only event handlers with no business logic |
| UI Compliance Scan | `run_ui_compliance_scan()` :2439 | UI-001..004 | Hardcoded colors, default palettes, generic fonts, non-grid spacing |
| API Contract Scan | `run_api_contract_scan()` :4435 | API-001..003 | Backend/frontend field mismatches vs REQUIREMENTS.md |
| Silent Data Loss | `run_silent_data_loss_scan()` :4416 | SDL-001 | CQRS handlers missing SaveChangesAsync() |
| Endpoint XREF | `run_endpoint_xref_scan()` :5258 | XREF-001..002, API-004 | Frontend calls missing backend endpoints |

### Contract Scanners (contract_scanner.py)

| Scanner | Violation Codes | What It Checks |
|---------|-----------------|----------------|
| Endpoint Schema | CONTRACT-001 | Response DTO fields match contract |
| Missing Endpoint | CONTRACT-002 | All contracted routes have handlers |
| Event Schema | CONTRACT-003 | Event payloads match contracted schema |
| Shared Model | CONTRACT-004 | Shared model fields match across languages |

### Integration Verifier (integration_verifier.py)

| Component | What It Checks |
|-----------|----------------|
| Frontend Call Parser | Parses fetch(), axios, api.*, useQuery, useMutation calls |
| Backend Route Parser | Parses NestJS decorators, Express routes, FastAPI routes, Django paths |
| Mismatch Detector | Diffs frontend calls vs backend endpoints by path + method |
| Field Mismatch | Compares request/response field names across layers |
| Parameter Mismatch | Compares query/path parameters |

### API Contract Extractor (api_contract_extractor.py)

| Component | What It Checks |
|-----------|----------------|
| NestJS Parser | Extracts controllers, decorators, DTOs, return types |
| Express Parser | Extracts router/app route definitions |
| FastAPI Parser | Extracts @app/@router decorated routes |
| Django Parser | Extracts path() URL patterns |
| Prisma Parser | Extracts models, fields, enums |
| DTO Field Parser | Extracts decorated class properties |
| Naming Convention | Detects snake_case vs camelCase convention |

### Contract Verifier (contract_verifier.py)

| Component | What It Checks |
|-----------|----------------|
| Endpoint Verification | Contract endpoints vs actual route definitions |
| Entity Verification | Contract entity names vs actual class/type definitions |
| Deviation Detection | Missing endpoints, extra endpoints, signature mismatches |

### Verification Pipeline (verification.py)

| Phase | What It Checks |
|-------|----------------|
| Phase 0: Requirements compliance | Checked vs unchecked items ratio |
| Phase 0b: Test file existence | Test files exist for the project |
| Phase 1: Contract check | CONTRACTS.json validation |
| Phase 1.5: Build check | Project builds successfully |
| Phase 2: Lint | Lint passes (auto-detected command) |
| Phase 3: Type check | Type checker passes (auto-detected) |
| Phase 4: Tests | Test suite passes (auto-detected) |
| Phase 4.5: Test quality | Assertion depth in test files |
| Phase 5: Security audit | Dependency/secret checks |
| Phase 6: Spot checks | Anti-pattern regex checks (quality_checks.py) |

### Wiring Checker (wiring.py)

| Component | What It Checks |
|-----------|----------------|
| WIRE-xxx Parser | Parses wiring tasks from TASKS.md |
| Dependency Builder | Builds wiring dependency DAG |
| Schedule Hint | Generates wiring schedule for orchestrator |

### Milestone Manager (milestone_manager.py)

| Component | What It Checks |
|-----------|----------------|
| Health Checker | Per-milestone convergence ratio, review cycles |
| Export Verifier | Cross-milestone wiring completeness |
| Rollup Health | Aggregate health across all milestones |

---

## 5. Injection Points

### 5A. In cli.py: Where NEW Validators Can Be Added

#### Per-Milestone Scan Slots (Inside Milestone Loop)

Location: `cli.py:1757-1965` (after milestone orchestration, before mark-complete)

The existing pattern is:
```python
# Post-milestone <name> scan (if enabled)
if config.<section>.<scan_name>:
    try:
        from .quality_checks import run_<scan_name>
        violations = run_<scan_name>(project_root)
        if violations:
            print_warning(...)
            fix_cost = await _run_<name>_fix(...)
            total_cost += fix_cost
            remaining = run_<scan_name>(project_root)
    except Exception as exc:
        print_warning(f"... failed (non-blocking): {exc}")
```

**INJECTION POINT A1**: After UI compliance scan (cli.py:1816) and before final health gate (cli.py:1819). Add new per-milestone scans here. Low risk -- purely additive, follows existing pattern.

**INJECTION POINT A2**: After integration verification gate (cli.py:1965) and before per-milestone audit (cli.py:1967). Add new cross-milestone validation here. Low risk.

#### Post-Orchestration Scan Slots

Location: `cli.py:7481-7621` (the scan sequence continues linearly)

**INJECTION POINT B1**: After handler completeness scan (cli.py:7545) and before entity coverage scan (cli.py:7547). Best place for new static analysis scans. **LOWEST RISK** -- purely additive, all scans are crash-isolated with try/except.

**INJECTION POINT B2**: After API completeness scan (cli.py:7621) and before runtime verification (cli.py:7623). Add new scans that should run before Docker/E2E testing.

**INJECTION POINT B3**: After E2E quality scan (cli.py:7987) and before browser testing (cli.py:7989). Add new scans that depend on E2E results.

#### Recovery Pass Slots

Each scan can have a corresponding `_run_<name>_fix()` async function. The pattern is established by these existing functions:

| Fix Function | Location | Pattern |
|-------------|----------|---------|
| `_run_mock_data_fix` | cli.py:2538 | Focused prompt + single session |
| `_run_ui_compliance_fix` | cli.py:3114 | Focused prompt + single session |
| `_run_api_contract_fix` | cli.py:2793 | Focused prompt + single session |
| `_run_contract_compliance_fix` | cli.py:2873 | Focused prompt + single session |
| `_run_silent_data_loss_fix` | cli.py:2952 | Focused prompt + single session |
| `_run_endpoint_xref_fix` | cli.py:3030 | Focused prompt + single session |
| `_run_stub_completion` | cli.py:2616 | Per-service focused sessions |
| `_run_integrity_fix` | cli.py:3870 | Typed by scan_type |
| `_run_e2e_fix` | cli.py:3278 | E2E test failure fix |

**INJECTION POINT C**: New `_run_<name>_fix()` functions follow the exact same pattern. Add as module-level async functions alongside the existing ones. Low risk.

#### Pre-Orchestration Gate Slots

Location: `cli.py:5457-5800` (Phase 0 through Phase 0.6)

**INJECTION POINT D**: After Phase 0.6 design extraction (cli.py:~5800) and before the orchestration call. Add new pre-flight validation here (e.g., PRD completeness check, tech stack compatibility check). Medium risk -- adds latency before the main build.

### 5B. In agents.py: Where New Rules Can Be Added

#### Orchestrator System Prompt Sections

**INJECTION POINT E1** (SECTION 3, after GATE 5, line ~218): Add new convergence gates. The orchestrator prompt currently has 5 gates. New gates (GATE 6, GATE 7, etc.) can be appended. Low risk -- additive prompt text.

**INJECTION POINT E2** (SECTION 5, after line ~496): Extend adversarial review protocol with new review checklist items. The reviewer instructions are a list; new items append naturally. Low risk.

**INJECTION POINT E3** (SECTION 7, workflow steps): Add new mandatory steps. Currently steps 0-9. New steps can be inserted (e.g., step 5.5 for new validation). Medium risk -- changing workflow order could confuse the orchestrator.

**INJECTION POINT E4** (SECTION 9, after line ~848): Add new cross-service implementation standards. Currently covers event handlers, error format, testing, state machines, business logic, browser test readiness, security, database, Dockerfiles, API handler completeness. New standards append naturally. Low risk.

**INJECTION POINT E5** (SECTION 10, after line ~898): Add new serialization/data format mandates. Low risk.

**INJECTION POINT E6** (New SECTION 11+): Add entirely new sections for new categories of standards. Low risk -- appending to prompt.

#### Agent Definition Modifications

Location: `agents.py:build_agent_definitions()` at line 2719.

**INJECTION POINT F**: Modify individual agent system prompts (code-writer, code-reviewer, etc.) to include new standards. Each agent gets `get_standards_for_agent()` from `code_quality_standards.py`. Adding new standards there affects all agents that receive them. Medium risk -- changing agent behavior.

### 5C. In config.py: New Config Options Needed

#### New Scan Config Fields

**INJECTION POINT G1**: Add boolean flags to `PostOrchestrationScanConfig` (config.py:295-309). Pattern:
```python
new_scan_name: bool = True  # Description of what it checks
```
Low risk -- dataclass field addition with default value.

**INJECTION POINT G2**: Add to `ContractScanConfig` (config.py:313-324) for new contract compliance checks. Same pattern. Low risk.

**INJECTION POINT G3**: Add to `IntegrityScanConfig` (config.py:377-389) for new integrity checks. Same pattern. Low risk.

**INJECTION POINT G4**: Add to `DatabaseScanConfig` (config.py:435-447) for new database checks. Same pattern. Low risk.

#### New Config Sections

**INJECTION POINT H**: Add entirely new `@dataclass` config sections and wire them into `AgentTeamConfig` (config.py:611-655). Pattern: create dataclass, add field to `AgentTeamConfig`, add to `load_config()` parser, add to `apply_depth_quality_gating()`. Medium risk -- requires changes across 3 functions.

#### Depth Gating

**INJECTION POINT I**: In `apply_depth_quality_gating()` (config.py:700-838), add `_gate()` calls for new config fields to control which scans are active at each depth level. Low risk -- additive calls.

---

## 6. Test Coverage

### Test File Inventory (112 test files in tests/)

#### Core Pipeline Tests
| File | What It Tests |
|------|---------------|
| `test_cli.py` | CLI argument parsing, depth detection, PRD detection, agent count parsing |
| `test_config.py` | Config loading, validation, defaults, YAML override parsing |
| `test_config_completeness.py` | All config fields have defaults, all agent types defined |
| `test_agents.py` | Orchestrator prompt assembly, agent definition building |
| `test_prompt_integrity.py` | Prompt section presence, template variable substitution |

#### Validator/Scanner Tests
| File | What It Tests |
|------|---------------|
| `test_quality_checks.py` | Spot checks, mock data scan, UI compliance scan patterns |
| `test_verification.py` | Progressive verification pipeline phases |
| `test_integration_verifier.py` | Frontend/backend mismatch detection |
| `test_api_contract_extractor.py` | API contract extraction from code |
| `test_api_contract.py` | API contract scan violations |
| `test_contract_scanner.py` | CONTRACT-001 through CONTRACT-004 |
| `test_contract_verifier.py` | Contract deviation detection |
| `test_contracts.py` | Contract registry, verification |
| `test_scan_pattern_correctness.py` | Regex pattern accuracy |
| `test_scan_scope.py` | Changed-only vs full scan modes |
| `test_database_scans.py` | DB-001 through DB-008 |
| `test_integrity_scans.py` | DEPLOY-001..004, ASSET-001..003 |

#### Milestone/PRD Tests
| File | What It Tests |
|------|---------------|
| `test_milestone_manager.py` | MASTER_PLAN.md parsing, health checks, wiring verification |
| `test_prd_parser.py` | Entity/state machine/event extraction |
| `test_prd_chunking.py` | Large PRD splitting |
| `test_prd_mode_convergence.py` | PRD mode convergence health |

#### Integration Tests
| File | What It Tests |
|------|---------------|
| `test_integration.py` | Cross-module integration |
| `test_integration_gate_config.py` | IntegrationGateConfig validation |
| `test_integration_hardening.py` | Integration gate edge cases |
| `test_pipeline_execution_order.py` | Scan execution ordering |
| `test_cross_mode_matrix.py` | Feature availability across modes |
| `test_wiring_verification.py` | Cross-milestone wiring |

#### Regression Tests
| File | What It Tests |
|------|---------------|
| `test_production_regression.py` | Production regression scenarios |
| `test_mini_build_regression.py` | Mini build regression |
| `test_v10_production_fixes.py`, `test_v10_1_runtime_guarantees.py`, `test_v10_2_bugfixes.py` | Version-specific fixes |
| `test_v11_gap_closure.py`, `test_v12_hard_ceiling.py` | Gap closure tests |
| `test_xref_bug_fixes.py` | XREF scan bug fixes |
| `test_drawspace_critical_fixes.py` | App-specific regression fixes |

### Coverage Gaps

1. **No end-to-end pipeline test**: No test runs main() through the full pipeline with mock SDK responses. Individual phases are tested but not the complete sequence.

2. **No cross-scan interaction tests**: Tests verify each scan independently but do not test what happens when scan A produces violations that scan B should also catch (overlap/conflict).

3. **No prompt regression tests for bug categories**: No test verifies that the orchestrator prompt text would prevent the specific 62-bug categories from the Facilities Management build.

4. **Limited fix-pass effectiveness tests**: Tests verify scans detect violations but rarely verify that the fix pass prompts actually lead to resolution.

5. **No multi-milestone integration test**: Milestone tests use mock data. No test verifies that milestone N's output is correctly consumed by milestone N+1.

6. **No config depth-gating completeness test**: No test verifies that every scan config field is handled in `apply_depth_quality_gating()`.

7. **Limited contract scanner coverage for C#/.NET**: Contract scanners have strong NestJS/Express/FastAPI coverage but limited ASP.NET/C# pattern support (only basic `[Http*]` attribute regex).

---

## 7. Risk Assessment

### LOW RISK (Additive Only -- No Existing Logic Modified)

| Injection Point | Description | Risk Notes |
|----------------|-------------|------------|
| **B1** (Post-orch scan slot) | Add new scan after handler completeness | Crash-isolated; follows exact existing pattern |
| **B2** (Post-orch scan slot) | Add new scan before runtime verification | Same pattern |
| **C** (New fix functions) | Add `_run_<name>_fix()` functions | Standalone async functions; no coupling |
| **G1-G4** (Config flags) | Add boolean fields to existing scan configs | Dataclass defaults ensure backward compat |
| **I** (Depth gating) | Add `_gate()` calls for new fields | Purely additive; existing gating unchanged |
| **E1** (New convergence gates) | Append GATE 6+ to orchestrator prompt | Appending to numbered list |
| **E4** (New standards) | Append to SECTION 9 standards | Appending to existing section |
| **E6** (New sections) | Add SECTION 11+ to prompt | End-of-prompt additions |
| **A1** (Per-milestone scan) | Add scan inside milestone loop | Follows mock data/UI scan pattern exactly |

### MEDIUM RISK (Requires Coordination Across Files)

| Injection Point | Description | Risk Notes |
|----------------|-------------|------------|
| **H** (New config section) | Add new config dataclass + wire into AgentTeamConfig | Requires changes in config.py, load_config(), and apply_depth_quality_gating() |
| **E3** (Workflow steps) | Insert new mandatory workflow steps | Could confuse orchestrator if step numbering changes |
| **F** (Agent definitions) | Modify agent system prompts | Changes agent behavior; could cause unexpected interactions |
| **D** (Pre-orchestration gate) | Add pre-flight validation | Adds latency; could block builds on new criteria |

### HIGHER RISK (Modifying Existing Logic)

| Injection Point | Description | Risk Notes |
|----------------|-------------|------------|
| Modifying SECTION 3 convergence loop | Changing existing gate logic | Core loop; any change affects all builds |
| Modifying `_check_convergence_health()` | Changing health computation | Affects pass/fail decisions for all modes |
| Modifying `verify_task_completion()` | Changing verification pipeline phases | Phase ordering is load-bearing |
| Modifying `_build_options()` | Changing how SDK options are built | Affects all orchestrator sessions |
| Modifying `build_orchestrator_prompt()` | Changing prompt assembly | Central prompt; any template error breaks all builds |

---

## Appendix A: Key File Locations

| File | Path | Size (approx) | Purpose |
|------|------|-------|---------|
| agents.py | `src/agent_team_v15/agents.py` | ~3000+ lines | Orchestrator prompt + agent definitions |
| cli.py | `src/agent_team_v15/cli.py` | ~8400+ lines | Pipeline execution, all fix passes, main() |
| config.py | `src/agent_team_v15/config.py` | ~900+ lines | All configuration dataclasses |
| quality_checks.py | `src/agent_team_v15/quality_checks.py` | ~7200+ lines | All static analysis scanners |
| verification.py | `src/agent_team_v15/verification.py` | ~400+ lines | Progressive verification pipeline |
| integration_verifier.py | `src/agent_team_v15/integration_verifier.py` | ~500+ lines | Frontend-backend mismatch detection |
| api_contract_extractor.py | `src/agent_team_v15/api_contract_extractor.py` | ~600+ lines | API contract extraction from code |
| contract_verifier.py | `src/agent_team_v15/contract_verifier.py` | ~200+ lines | Contract vs implementation verification |
| contract_scanner.py | `src/agent_team_v15/contract_scanner.py` | ~400+ lines | CONTRACT-001..004 compliance scans |
| code_quality_standards.py | `src/agent_team_v15/code_quality_standards.py` | ~300+ lines | FRONT-xxx, BACK-xxx standards text |
| milestone_manager.py | `src/agent_team_v15/milestone_manager.py` | ~400+ lines | MASTER_PLAN parsing, health, wiring |
| audit_agent.py | `src/agent_team_v15/audit_agent.py` | ~400+ lines | PRD vs build comparison audit |
| prd_parser.py | `src/agent_team_v15/prd_parser.py` | ~400+ lines | Entity/state/event extraction from PRD |
| wiring.py | `src/agent_team_v15/wiring.py` | ~200+ lines | WIRE-xxx task dependency detection |

## Appendix B: Config Hierarchy Quick Reference

```
AgentTeamConfig (config.py:611)
  +-- orchestrator: OrchestratorConfig      (model, max_turns, budget)
  +-- depth: DepthConfig                    (default, auto_detect, keywords)
  +-- convergence: ConvergenceConfig        (max_cycles, thresholds)
  +-- interview: InterviewConfig            (enabled, exchanges)
  +-- design_reference: DesignReferenceConfig (URLs, extraction settings)
  +-- codebase_map: CodebaseMapConfig       (enabled, limits)
  +-- scheduler: SchedulerConfig            (parallel, conflicts)
  +-- verification: VerificationConfig      (lint, type check, tests, build)
  +-- quality: QualityConfig                (production defaults, craft review)
  +-- investigation: InvestigationConfig    (Gemini, ST, hypothesis)
  +-- orchestrator_st: OrchestratorSTConfig (ST decision points)
  +-- milestone: MilestoneConfig            (enabled, health gate, scans)
  +-- prd_chunking: PRDChunkingConfig       (threshold, chunk size)
  +-- e2e_testing: E2ETestingConfig         (enabled, retries, port)
  +-- browser_testing: BrowserTestingConfig (enabled, retries, headless)
  +-- integrity_scans: IntegrityScanConfig  (deployment, asset, PRD)
  +-- runtime_verification: RuntimeVerificationConfig (Docker, smoke test)
  +-- tracking_documents: TrackingDocumentsConfig (coverage, fix log, handoff)
  +-- database_scans: DatabaseScanConfig    (dual ORM, defaults, relationships)
  +-- post_orchestration_scans: PostOrchestrationScanConfig (all scan toggles)
  +-- tech_research: TechResearchConfig     (Context7 research settings)
  +-- integration_gate: IntegrationGateConfig (API contracts, verification)
  +-- agents: dict[str, AgentConfig]        (per-agent model/enabled)
  +-- mcp_servers: dict[str, MCPServerConfig] (firecrawl, context7, ST)
  +-- display: DisplayConfig                (cost, tools, verbose)
  +-- audit_team: AuditTeamConfig           (auditors, reaudit, scoring)
  +-- agent_teams: AgentTeamsConfig          (Claude Code Agent Teams)
  +-- contract_engine: ContractEngineConfig  (MCP contract validation)
  +-- codebase_intelligence: CodebaseIntelligenceConfig (semantic search MCP)
  +-- contract_scans: ContractScanConfig     (CONTRACT-001..004 toggles)
```
