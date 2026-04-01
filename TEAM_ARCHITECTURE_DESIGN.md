# Phase Lead Team Architecture Design

> Transforms the single-orchestrator bottleneck into a coordinated team of persistent phase leads that communicate via SendMessage, deploy isolated sub-agents for parallel work, and share state through well-defined artifacts.

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Architecture Overview](#architecture-overview)
3. [Phase Lead Definitions](#phase-lead-definitions)
4. [Communication Protocol](#communication-protocol)
5. [Task Handoff Protocol](#task-handoff-protocol)
6. [Shared State](#shared-state)
7. [Teams vs Sub-Agents Decision Framework](#teams-vs-sub-agents-decision-framework)
8. [Implementation Mapping to Current Codebase](#implementation-mapping-to-current-codebase)
9. [Error Handling and Escalation](#error-handling-and-escalation)
10. [Configuration Schema](#configuration-schema)

---

## Problem Statement

The current architecture (`agents.py`, `cli.py`) uses a **single orchestrator** Claude session that deploys isolated sub-agents via `ClaudeSDKClient` `query()` calls. Each sub-agent runs in isolation -- it receives a prompt, produces output, and terminates. Sub-agents cannot communicate with each other. The orchestrator must:

- Serialize all phase transitions (planning -> architecture -> coding -> review -> testing)
- Manually shuttle context between phases by reading artifacts and injecting them into prompts
- Re-derive cross-cutting decisions because sub-agents have no memory of prior phases
- Handle all coordination logic in a single, increasingly large context window

**Evidence from codebase**: The orchestrator prompt in `agents.py` (Sections 1-11, ~3000+ lines) encodes the entire workflow because there is no other place for coordination logic to live. The `cli.py` file has 8000+ lines because every phase transition is manually wired.

**Proven alternative**: In a real Claude Code Teams session, 10 agents exchanged 40+ messages via `SendMessage`, producing dramatically better results through direct coordination.

---

## Architecture Overview

```
Orchestrator (team-lead)
│
├── planning-lead (team member, persistent)
│   Deploys: planner sub-agents, spec-validator sub-agents
│   Produces: REQUIREMENTS.md
│
├── architecture-lead (team member, persistent)
│   Deploys: architect sub-agents, contract-generator sub-agents
│   Produces: CONTRACTS.json, wiring map, file ownership
│
├── coding-lead (team member, persistent)
│   Deploys: code-writer sub-agents (per wave), task-assigner sub-agents
│   Produces: implementation code, TASKS.md updates
│
├── review-lead (team member, persistent)
│   Deploys: code-reviewer sub-agents
│   Produces: REQUIREMENTS.md mark updates, Review Log entries
│
└── testing-lead (team member, persistent)
    Deploys: test-runner sub-agents, security-auditor sub-agents
    Produces: test files, VERIFICATION.md, test results
```

### Key Distinction: Team Members vs Sub-Agents

| Aspect | Phase Lead (Team Member) | Worker (Sub-Agent) |
|--------|------------------------|--------------------|
| Lifecycle | Persistent across entire build | Created per task, destroyed on completion |
| Communication | SendMessage to any teammate | None -- isolated execution |
| State | Maintains context across all waves | Receives scoped context, returns output |
| Role | Coordinates, decides, delegates | Executes a single atomic task |
| Implemented via | Claude Code Teams teammate | `ClaudeSDKClient.query()` call |

---

## Phase Lead Definitions

### 1. planning-lead

**Role**: Explore the codebase, understand the problem space, produce REQUIREMENTS.md as the single source of truth.

**Tools**: Read, Grep, Glob, Write, Bash

**Sub-agents deployed**:
- `planner` sub-agents (parallel): Each explores a different codebase facet (structure, patterns, schemas, routes, components)
- `spec-validator` sub-agent: Validates REQUIREMENTS.md against original user request

**Responsibilities**:
1. Receive the user task from orchestrator
2. Deploy planner sub-agents in parallel to explore the codebase
3. Synthesize findings into `.agent-team/REQUIREMENTS.md`
4. Deploy spec-validator to check fidelity; re-plan if FAIL
5. Send completion signal to `architecture-lead` with REQUIREMENTS.md path

**Persistent context the lead retains**:
- Original user request (verbatim)
- Codebase structure summary
- Detected depth level and agent counts
- User constraints (prohibitions, requirements, scope)
- Design reference URLs (if any)

**Configuration mapping**:
```yaml
phase_leads:
  planning_lead:
    model: opus                    # from config.agents.planner.model
    max_sub_agents: 10             # from DEPTH_AGENT_COUNTS[depth]["planning"]
    tools: [Read, Grep, Glob, Write, Bash]
    sub_agent_types: [planner, spec-validator]
```

---

### 2. architecture-lead

**Role**: Design the solution architecture, produce contracts, define the wiring map and file ownership that coding-lead will follow.

**Tools**: Read, Grep, Glob, Write, Edit

**Sub-agents deployed**:
- `architect` sub-agents (parallel): Design solution approach, file ownership, interface contracts
- `contract-generator` sub-agent: Generates `.agent-team/CONTRACTS.json` from architecture decisions

**Responsibilities**:
1. Receive REQUIREMENTS.md readiness signal from `planning-lead`
2. Read REQUIREMENTS.md and codebase
3. Deploy architect sub-agents to design the solution
4. Synthesize into architecture decision, wiring map, entry points
5. Update REQUIREMENTS.md with WIRE-xxx and TECH-xxx requirements
6. Deploy contract-generator to produce CONTRACTS.json
7. Produce file ownership map (which files each coder handles)
8. Send file assignments + contracts to `coding-lead`
9. If `review-lead` escalates a wiring issue, re-examine and revise

**Persistent context the lead retains**:
- Architecture decisions made
- File ownership map
- Contract definitions
- Wiring map (all cross-file connections)
- Enum/status registry

**Configuration mapping**:
```yaml
phase_leads:
  architecture_lead:
    model: opus
    max_sub_agents: 4              # from DEPTH_AGENT_COUNTS[depth]["architecture"]
    tools: [Read, Grep, Glob, Write, Edit]
    sub_agent_types: [architect, contract-generator]
```

---

### 3. coding-lead

**Role**: Coordinate code-writers, manage the task DAG, resolve file conflicts, ensure wave-by-wave execution with no regressions.

**Tools**: All (Read, Write, Edit, Bash, Glob, Grep)

**Sub-agents deployed**:
- `task-assigner` sub-agent: Decomposes requirements into TASKS.md
- `code-writer` sub-agents (parallel per wave): Each implements assigned tasks
- `integration-agent` sub-agent: Processes integration declarations for shared files
- `debugger` sub-agents: Fix issues reported by review-lead

**Responsibilities**:
1. Receive file assignments + contracts from `architecture-lead`
2. Deploy task-assigner to create `.agent-team/TASKS.md`
3. Use the scheduler (`scheduler.py`) to compute execution waves
4. For each wave:
   a. Deploy code-writer sub-agents with scoped context (their files + contracts only)
   b. Collect results, mark tasks COMPLETE in TASKS.md
   c. Run mock-data gate scan (reject waves with mock data)
   d. If shared files were modified, deploy integration-agent
5. Signal `review-lead` after each wave completes
6. Receive failure reports from `review-lead`, deploy debugger sub-agents
7. Re-enter coding loop for unfixed items
8. Signal `testing-lead` when all TASKS.md items are COMPLETE and review passes

**Persistent context the lead retains**:
- TASKS.md state (which tasks are pending/complete/failed)
- Wave execution history
- File conflict resolutions
- Debug cycle count per item
- Contracts and file ownership from architecture-lead

**Configuration mapping**:
```yaml
phase_leads:
  coding_lead:
    model: opus
    max_sub_agents: 10             # from DEPTH_AGENT_COUNTS[depth]["coding"]
    tools: [Read, Write, Edit, Bash, Glob, Grep]
    sub_agent_types: [task-assigner, code-writer, integration-agent, debugger]
```

---

### 4. review-lead

**Role**: Adversarial review of all code, mark REQUIREMENTS.md items as pass/fail, enforce convergence gates.

**Tools**: Read, Grep, Glob, Write, Edit

**Sub-agents deployed**:
- `code-reviewer` sub-agents (parallel): Each reviews a subset of requirements
- Specialized auditor sub-agents (when audit_team enabled): api-auditor, schema-auditor, etc.

**Responsibilities**:
1. Receive wave-complete signal from `coding-lead`
2. Read REQUIREMENTS.md + generated code
3. Deploy code-reviewer sub-agents -- they are HARSH CRITICS
4. Collect review results
5. Update REQUIREMENTS.md: mark items `[x]` (pass) or leave `[ ]` (fail with notes)
6. Increment `review_cycles` counter on every evaluated item
7. Add entries to Review Log table
8. Calculate convergence ratio
9. Decision routing:
   - All items `[x]` -> send completion to `orchestrator` + signal `testing-lead`
   - Items failing -> send failure report to `coding-lead` with specific issues
   - Items stuck 3+ cycles -> escalate:
     - WIRE-xxx items -> escalate to `architecture-lead`
     - Other items -> escalate to `planning-lead` via orchestrator
10. Perform cross-cutting checks (route alignment, schema, query, enum, auth, serialization)

**Persistent context the lead retains**:
- Review cycle count per requirement
- Failure history (which items failed, why, how many times)
- Cross-cutting check results
- Convergence ratio trend

**Configuration mapping**:
```yaml
phase_leads:
  review_lead:
    model: opus
    max_sub_agents: 8              # from DEPTH_AGENT_COUNTS[depth]["review"]
    tools: [Read, Grep, Glob, Write, Edit]
    sub_agent_types: [code-reviewer]
    # When audit_team.enabled: also deploys specialized auditors
```

---

### 5. testing-lead

**Role**: Write tests, run tests, verify all requirements are tested, report results.

**Tools**: All (Read, Write, Edit, Bash, Glob, Grep)

**Sub-agents deployed**:
- `test-runner` sub-agents (parallel): Write and execute tests per requirement
- `security-auditor` sub-agent: OWASP checks, dependency audit

**Responsibilities**:
1. Receive all-requirements-pass signal from `review-lead`
2. Read REQUIREMENTS.md and CONTRACTS.json
3. Deploy test-runner sub-agents for each requirement category
4. Collect test results
5. Mark testing items `[x]` in REQUIREMENTS.md (only after tests pass)
6. If tests fail -> send specific failures to `coding-lead` for debugger dispatch
7. Deploy security-auditor if applicable
8. Send final results to `orchestrator`

**Persistent context the lead retains**:
- Test execution results
- Coverage information
- Which requirements have passing tests
- Security audit findings

**Configuration mapping**:
```yaml
phase_leads:
  testing_lead:
    model: opus
    max_sub_agents: 5              # from DEPTH_AGENT_COUNTS[depth]["testing"]
    tools: [Read, Write, Edit, Bash, Glob, Grep]
    sub_agent_types: [test-runner, security-auditor]
```

---

## Communication Protocol

### Message Format

All inter-lead messages use SendMessage with structured content. Every message includes:

```
To: <recipient-lead>
Type: <message-type>
Phase: <sender-phase>
---
<body>
```

### Message Types by Phase Transition

#### planning-lead -> architecture-lead: `REQUIREMENTS_READY`

Sent when REQUIREMENTS.md is complete and spec-validated.

```
To: architecture-lead
Type: REQUIREMENTS_READY
Phase: planning
---
REQUIREMENTS.md is complete and spec-validated at:
  .agent-team/REQUIREMENTS.md

Summary:
- Functional requirements: 12
- Technical requirements: 8
- Total checklist items: 20
- Depth: thorough
- Design references: [URLs if any]

Codebase context:
- Framework: NestJS + Angular
- Database: PostgreSQL via Prisma
- Entry points: [list]

Constraints: [user prohibitions/requirements if any]
```

#### architecture-lead -> coding-lead: `ARCHITECTURE_READY`

Sent when architecture decisions, contracts, and file assignments are complete.

```
To: coding-lead
Type: ARCHITECTURE_READY
Phase: architecture
---
Architecture decisions complete. Artifacts:
  .agent-team/REQUIREMENTS.md (updated with WIRE-xxx, TECH-xxx)
  .agent-team/CONTRACTS.json

File Ownership Map:
  code-writer-1: [src/auth/*, src/common/*]
  code-writer-2: [src/buildings/*, src/floors/*]
  code-writer-3: [frontend/src/app/auth/*, frontend/src/app/shared/*]
  integration-agent: [src/app.module.ts, src/main.ts]

Shared files (require integration-agent):
  - src/app.module.ts (all modules register here)
  - src/main.ts (global interceptors/pipes)

Wiring map: 15 WIRE-xxx entries in REQUIREMENTS.md
Enum registry: 8 entities with status fields
```

#### coding-lead -> review-lead: `WAVE_COMPLETE`

Sent after each coding wave finishes (including mock-data gate pass).

```
To: review-lead
Type: WAVE_COMPLETE
Phase: coding
---
Wave 3 of 5 complete.

Tasks completed this wave: TASK-012, TASK-013, TASK-014, TASK-015
Files modified: [list]
Files created: [list]

TASKS.md status: 15/20 complete
Mock data gate: PASS (no mock patterns found)

Requirements to review:
  REQ-005, REQ-006, WIRE-003, WIRE-004, SVC-002

Previous review findings addressed:
  - REQ-003 route alignment fixed (was /buildings/:id/floors, now /floors)
  - WIRE-002 missing import added to app.module.ts
```

#### review-lead -> coding-lead: `REVIEW_RESULTS`

Sent after each review cycle completes.

```
To: coding-lead
Type: REVIEW_RESULTS
Phase: review
---
Review cycle 2 complete.

Convergence: 16/20 items [x] (80%)

PASSING (newly marked [x]):
  - REQ-005: Correctly implemented [x]
  - WIRE-003: Import verified, route registered [x]

FAILING (remain [ ]):
  - REQ-007: Missing validation on tenant_id (review_cycles: 2)
  - SVC-002: Frontend service still uses hardcoded array (review_cycles: 1)
  - WIRE-004: Component created but not rendered in router outlet (review_cycles: 1)
  - TECH-003: No error interceptor registered globally (review_cycles: 2)

ESCALATION NEEDED:
  - TECH-003 has hit 3 cycles -- needs architecture-lead re-examination

Action required: Deploy debuggers for REQ-007, SVC-002, WIRE-004.
Escalate TECH-003 to architecture-lead.
```

#### review-lead -> architecture-lead: `WIRING_ESCALATION`

Sent when a WIRE-xxx or structural item is stuck.

```
To: architecture-lead
Type: WIRING_ESCALATION
Phase: review
---
WIRE-004 has failed review 3 times. The wiring mechanism may need redesign.

Item: WIRE-004 -- AppRoutingModule renders BuildingListComponent
Issue: Component exists at buildings/building-list.component.ts but the
  route path in app-routing.module.ts points to a lazy-loaded module that
  does not re-export the component.

Review history:
  Cycle 1: Route path wrong (fixed)
  Cycle 2: Module import missing (fixed)
  Cycle 3: Lazy loading breaks direct component reference

Please re-examine whether this should use lazy loading or eager import.
```

#### review-lead -> orchestrator: `CONVERGENCE_COMPLETE`

Sent when all items are `[x]`.

```
To: orchestrator
Type: CONVERGENCE_COMPLETE
Phase: review
---
All 20/20 requirements marked [x] after 4 review cycles.
Ready for testing phase.
```

#### testing-lead -> orchestrator: `TESTING_COMPLETE`

```
To: orchestrator
Type: TESTING_COMPLETE
Phase: testing
---
Testing complete.
- Tests written: 47
- Tests passing: 47
- Tests failing: 0
- Coverage: functional=100%, wiring=100%, security=PASS

All testing items marked [x] in REQUIREMENTS.md.
Build verified: pnpm build exits 0.
```

#### coding-lead -> review-lead: `DEBUG_FIX_COMPLETE`

Sent after debuggers fix issues from a review cycle.

```
To: review-lead
Type: DEBUG_FIX_COMPLETE
Phase: coding
---
Debug fixes applied for review cycle 2 findings:

Fixed:
  - REQ-007: Added tenant_id validation in BuildingService.create()
  - SVC-002: Replaced hardcoded array with this.http.get<Building[]>('/api/buildings')
  - WIRE-004: Changed to eager import in AppRoutingModule

Files modified: [list]

Ready for re-review of: REQ-007, SVC-002, WIRE-004
```

#### orchestrator -> planning-lead: `ESCALATION_REQUEST`

Sent when a non-wiring item is stuck beyond escalation threshold.

```
To: planning-lead
Type: ESCALATION_REQUEST
Phase: orchestrator
---
REQ-009 has failed 3 review cycles. Please re-analyze:

Current requirement: "Dashboard shows real-time maintenance alerts"
Failure history:
  Cycle 1: No WebSocket implementation
  Cycle 2: WebSocket connected but no event subscription
  Cycle 3: Events received but not rendered in dashboard component

Options:
  1. Rewrite requirement into sub-tasks
  2. Simplify to polling-based instead of real-time
  3. Identify missing technical prerequisite

Please update REQUIREMENTS.md with revised/split requirement.
```

### Broadcast Messages

Used sparingly for system-wide state changes:

```
To: *
Type: SYSTEM_STATE
---
User intervention received. All phases PAUSE.
New constraint: "Do NOT use WebSockets -- use SSE instead"
Resume when acknowledged.
```

---

## Task Handoff Protocol

### Planning -> Architecture

| Data Passed | Location | Format |
|------------|----------|--------|
| Requirements checklist | `.agent-team/REQUIREMENTS.md` | Markdown with `[ ]` items |
| Codebase context | REQUIREMENTS.md `## Context` section | Prose + file listings |
| Research findings | REQUIREMENTS.md `## Research Findings` section | Prose |
| User constraints | REQUIREMENTS.md header + constraint block | Tagged items |
| Design references | REQUIREMENTS.md `## Design Standards` section | URLs + extracted tokens |
| Depth level | SendMessage body | String: quick/standard/thorough/exhaustive |

**Handoff trigger**: planning-lead sends `REQUIREMENTS_READY` message to architecture-lead.
**Blocking gate**: architecture-lead MUST NOT start until this message is received.

### Architecture -> Coding

| Data Passed | Location | Format |
|------------|----------|--------|
| Architecture decisions | REQUIREMENTS.md `## Architecture Decision` | Prose |
| Wiring map | REQUIREMENTS.md `### Wiring Map` | Markdown table |
| Entry points | REQUIREMENTS.md `### Entry Points` | Ordered list |
| WIRE-xxx requirements | REQUIREMENTS.md `### Wiring Requirements` | Checklist items |
| TECH-xxx requirements | REQUIREMENTS.md `### Technical Requirements` | Checklist items |
| Contracts | `.agent-team/CONTRACTS.json` | JSON schema |
| File ownership map | SendMessage body | Map of writer -> files |
| Enum registry | REQUIREMENTS.md `### Enum Registry` | Markdown table |

**Handoff trigger**: architecture-lead sends `ARCHITECTURE_READY` message to coding-lead.
**Blocking gate**: coding-lead MUST NOT start until CONTRACTS.json exists AND message received.

### Coding -> Review

| Data Passed | Location | Format |
|------------|----------|--------|
| Wave completion signal | SendMessage `WAVE_COMPLETE` | Structured message |
| Tasks completed | TASKS.md (status: COMPLETE) | Markdown |
| Files modified/created | SendMessage body | File path lists |
| Requirements to review | SendMessage body | Requirement IDs |
| Prior review fixes | SendMessage body | Issue -> fix mapping |

**Handoff trigger**: coding-lead sends `WAVE_COMPLETE` message to review-lead.
**Non-blocking**: coding-lead can prepare next wave while review runs.

### Review -> Coding (Failure Loop)

| Data Passed | Location | Format |
|------------|----------|--------|
| Review results | REQUIREMENTS.md Review Log table | Markdown table |
| Failing items | SendMessage `REVIEW_RESULTS` | Item IDs + failure reasons |
| Convergence ratio | SendMessage body | Fraction (e.g., 16/20 = 80%) |
| Escalation requests | SendMessage `WIRING_ESCALATION` | To architecture-lead |

**Handoff trigger**: review-lead sends `REVIEW_RESULTS` message to coding-lead.
**Loop condition**: coding-lead deploys debuggers, then sends `DEBUG_FIX_COMPLETE` back to review-lead.

### Review -> Testing

| Data Passed | Location | Format |
|------------|----------|--------|
| All-pass signal | SendMessage `CONVERGENCE_COMPLETE` (to orchestrator) | Structured message |
| Requirements doc | `.agent-team/REQUIREMENTS.md` (all `[x]`) | Markdown |
| Contracts | `.agent-team/CONTRACTS.json` | JSON |

**Handoff trigger**: Orchestrator forwards `CONVERGENCE_COMPLETE` to testing-lead.
**Blocking gate**: testing-lead MUST NOT start until convergence is complete.

---

## Shared State

All phase leads have read access to all shared artifacts. Write access is controlled per the existing convergence gates.

### Artifact Ownership

| Artifact | Created By | Written By | Read By |
|----------|-----------|------------|---------|
| `REQUIREMENTS.md` | planning-lead | planning-lead (create), architecture-lead (add WIRE/TECH), review-lead (mark [x]/[ ]), testing-lead (mark test items [x]) | All leads |
| `TASKS.md` | coding-lead (via task-assigner) | coding-lead (status updates) | All leads |
| `CONTRACTS.json` | architecture-lead (via contract-generator) | architecture-lead | coding-lead, review-lead, testing-lead |
| `VERIFICATION.md` | testing-lead | testing-lead | orchestrator, review-lead |
| `MASTER_PLAN.md` | planning-lead (PRD mode only) | planning-lead | orchestrator |
| Review Log | review-lead | review-lead (append only) | coding-lead, orchestrator |

### Artifact Locations

All artifacts live under the `.agent-team/` directory in the target project:

```
.agent-team/
  REQUIREMENTS.md          # Single source of truth
  TASKS.md                 # Implementation work plan (DAG)
  CONTRACTS.json           # Module and wiring contracts
  VERIFICATION.md          # Test and verification results
  MASTER_PLAN.md           # PRD mode milestone plan
  INTERVIEW.md             # User interview transcript (if any)
  milestones/              # PRD mode per-milestone artifacts
    milestone-1/
      REQUIREMENTS.md
      TASKS.md
```

### Discovery

Phase leads discover each other through the Claude Code Teams infrastructure -- they are named teammates visible to each other via SendMessage. No separate team config file is needed; the orchestrator spawns all five leads as named teammates at initialization.

---

## Teams vs Sub-Agents Decision Framework

### When to use a Team Member (Phase Lead)

Use a persistent team member when the agent needs to:

1. **Coordinate multiple sub-agents** -- marshaling parallel work requires persistent state
2. **Communicate across phases** -- sending/receiving messages requires a persistent identity
3. **Make decisions based on accumulated context** -- e.g., review-lead tracking failure counts across cycles
4. **React to events from other leads** -- e.g., receiving escalation requests
5. **Maintain a loop** -- e.g., coding-lead running wave-after-wave until done

**All five phase leads qualify because they all coordinate, communicate, and loop.**

### When to use a Sub-Agent (Worker)

Use an isolated sub-agent when the agent:

1. **Executes a single atomic task** -- explore one codebase facet, write one file, review one requirement
2. **Needs no communication** -- it receives context, produces output, and terminates
3. **Can run in parallel with peers** -- multiple code-writers in the same wave
4. **Has scoped context** -- only needs its files + contracts, not the full state

**All current agent types (planner, researcher, architect, code-writer, code-reviewer, test-runner, debugger, security-auditor, integration-agent, contract-generator, spec-validator) remain sub-agents.** They are deployed by their respective phase lead.

### Concrete Example: Coding Wave

```
coding-lead (team member, persistent)
├── Reads TASKS.md, computes wave 3
├── Deploys code-writer-1 (sub-agent) → TASK-012: src/auth/auth.service.ts
├── Deploys code-writer-2 (sub-agent) → TASK-013: src/buildings/building.controller.ts
├── Deploys code-writer-3 (sub-agent) → TASK-014: frontend/src/app/buildings/list.component.ts
├── All three run in parallel (no file overlap)
├── Collects results, marks TASKS.md
├── Runs mock-data gate
├── Deploys integration-agent (sub-agent) → process declarations for app.module.ts
└── Sends WAVE_COMPLETE to review-lead
```

The coding-lead is persistent because it runs this loop multiple times. The code-writers are ephemeral because each executes one task and terminates.

---

## Implementation Mapping to Current Codebase

### What Changes

| Current Component | Current Role | New Role |
|------------------|-------------|----------|
| `ORCHESTRATOR_SYSTEM_PROMPT` (agents.py) | Monolithic 3000+ line prompt encoding entire workflow | Slim coordinator that spawns 5 phase leads |
| `build_orchestrator_prompt()` (agents.py) | Builds the single orchestrator prompt | Builds orchestrator prompt + 5 phase lead prompts |
| `build_agent_definitions()` (agents.py) | Defines 11 sub-agent types | Unchanged -- sub-agents still exist, deployed by phase leads |
| `cli.py` main loop | Manually wires every phase transition | Spawns phase leads as teammates, monitors progress |
| `AgentTeamsBackend` (agent_teams_backend.py) | Placeholder for Agent Teams integration | Real implementation: spawns teammates, routes messages |
| `AgentTeamsConfig` (config.py) | Basic teammate config | Extended with phase lead config |
| `ExecutionWave` (scheduler.py) | Computed by orchestrator | Computed by coding-lead |

### What Stays the Same

- All 11 sub-agent types and their prompts (planner, researcher, architect, etc.)
- The scheduler (DAG, wave computation, conflict detection, critical path)
- The convergence loop logic (gates, escalation thresholds, review cycles)
- REQUIREMENTS.md structure and lifecycle
- TASKS.md structure and lifecycle
- CONTRACTS.json structure
- All post-orchestration scans
- Config loading and validation

### New Components Needed

1. **Phase lead prompt builder** (`agents.py`): `build_phase_lead_prompts()` -- generates the system prompt for each of the 5 phase leads, encoding their specific responsibilities, communication protocol, and sub-agent deployment patterns.

2. **Phase lead spawner** (`agent_teams_backend.py`): Extension to `AgentTeamsBackend.initialize()` that creates 5 named teammates using Claude Code Teams API.

3. **Message router** (`agent_teams_backend.py`): Logic in `AgentTeamsBackend` to handle message types (REQUIREMENTS_READY, ARCHITECTURE_READY, WAVE_COMPLETE, etc.) and route them to the correct phase lead.

4. **Phase lead config** (`config.py`): New `PhaseLeadConfig` dataclass with per-lead settings (model, max_sub_agents, tools, enabled).

5. **Orchestrator slim prompt** (`agents.py`): New slim orchestrator prompt that only handles: spawning leads, monitoring progress, handling user interventions, escalations, and completion.

---

## Error Handling and Escalation

### Phase Lead Failure

If a phase lead's Claude session crashes or times out:

1. Orchestrator detects the failure (teammate goes silent beyond `teammate_idle_timeout`)
2. Orchestrator respawns the lead with the same name
3. The new lead reads shared artifacts to reconstruct state:
   - REQUIREMENTS.md for current requirement status
   - TASKS.md for current task status
   - Review Log for review history
4. Orchestrator sends a `RESUME` message with context about where the lead left off

### Escalation Chains

```
Item fails review 1-2 times:
  review-lead -> coding-lead (REVIEW_RESULTS) -> debugger sub-agents

Item fails review 3+ times (non-wiring):
  review-lead -> orchestrator (ESCALATION_NEEDED)
  orchestrator -> planning-lead (ESCALATION_REQUEST)
  planning-lead rewrites/splits requirement
  orchestrator -> coding-lead (NEW_REQUIREMENTS)

Item fails review 3+ times (wiring, WIRE-xxx):
  review-lead -> architecture-lead (WIRING_ESCALATION)
  architecture-lead re-examines, updates wiring map
  architecture-lead -> coding-lead (WIRING_REVISION)

Max escalation depth exceeded:
  orchestrator -> user (ASK_USER)
```

### User Intervention

When the user sends a `[USER INTERVENTION]` message:

1. Orchestrator receives it and broadcasts `PAUSE` to all leads
2. All leads stop deploying new sub-agents (in-flight agents finish)
3. Orchestrator processes the intervention
4. Orchestrator broadcasts `RESUME` with updated constraints
5. Leads adjust their plans and continue

---

## Configuration Schema

Extension to `AgentTeamsConfig` in `config.py`:

```python
@dataclass
class PhaseLeadConfig:
    """Configuration for a single phase lead."""
    enabled: bool = True
    model: str = "opus"
    max_sub_agents: int = 10        # Max parallel sub-agents this lead can deploy
    tools: list[str] = field(default_factory=list)  # Tool access
    idle_timeout: int = 600         # Seconds before considered stalled


@dataclass
class PhaseLeadsConfig:
    """Configuration for the phase lead team architecture."""
    enabled: bool = False           # Opt-in (requires Agent Teams)
    planning_lead: PhaseLeadConfig = field(default_factory=lambda: PhaseLeadConfig(
        tools=["Read", "Grep", "Glob", "Write", "Bash"],
    ))
    architecture_lead: PhaseLeadConfig = field(default_factory=lambda: PhaseLeadConfig(
        tools=["Read", "Grep", "Glob", "Write", "Edit"],
    ))
    coding_lead: PhaseLeadConfig = field(default_factory=lambda: PhaseLeadConfig(
        tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    ))
    review_lead: PhaseLeadConfig = field(default_factory=lambda: PhaseLeadConfig(
        tools=["Read", "Grep", "Glob", "Write", "Edit"],
    ))
    testing_lead: PhaseLeadConfig = field(default_factory=lambda: PhaseLeadConfig(
        tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    ))
    # Handoff timeout: how long to wait for a phase lead to acknowledge a handoff
    handoff_timeout_seconds: int = 300
    # Whether to allow parallel phases (e.g., coding-lead preparing next wave
    # while review-lead reviews current wave)
    allow_parallel_phases: bool = True
```

### YAML Configuration Example

```yaml
agent_teams:
  enabled: true
  phase_leads:
    enabled: true
    planning_lead:
      model: opus
      max_sub_agents: 8
    architecture_lead:
      model: opus
      max_sub_agents: 4
    coding_lead:
      model: opus
      max_sub_agents: 10
    review_lead:
      model: opus
      max_sub_agents: 8
    testing_lead:
      model: opus
      max_sub_agents: 5
    handoff_timeout_seconds: 300
    allow_parallel_phases: true
```

---

## Appendix: Phase Lead Prompt Structure

Each phase lead gets a focused prompt (not the 3000-line monolith). Structure:

```
You are the {PHASE}-LEAD on a multi-agent team building {project description}.

## Your Role
{2-3 sentences about what this lead does}

## Your Team
- Orchestrator: team-lead (your coordinator)
- Other leads: planning-lead, architecture-lead, coding-lead, review-lead, testing-lead
- You deploy sub-agents for parallel work using the Task tool

## Communication Protocol
- Send REQUIREMENTS_READY to architecture-lead when requirements are complete
- You will receive ESCALATION_REQUEST from orchestrator if items are stuck
- Use SendMessage for all inter-lead communication

## Shared Artifacts
- .agent-team/REQUIREMENTS.md (read/write per your role)
- .agent-team/TASKS.md (read)
- .agent-team/CONTRACTS.json (read)

## Your Sub-Agents
{list of sub-agent types this lead deploys, with their prompts}

## Your Workflow
{step-by-step instructions specific to this phase}

## Quality Gates
{convergence rules, blocking gates, escalation triggers}
```

Each prompt is ~200-400 lines instead of 3000+. The coordination logic lives in the message protocol, not in a single prompt.
