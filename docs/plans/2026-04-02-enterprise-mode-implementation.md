# Enterprise Mode Implementation Plan

> **For Claude:** Execute this plan using an agent team (TeamCreate). Deploy 5 specialized agents that communicate via SendMessage. Follow the wave structure exactly.

**Goal:** Add `--depth enterprise` mode to the builder for 150K+ LOC builds, enabling architecture-driven domain partitioning, parallel domain-specialized coding agents, and domain-scoped parallel review.

**Architecture:** Enterprise mode adds a FILE OWNERSHIP MAP artifact produced by architecture-lead. This map drives domain-specialized coding agents (backend-dev, frontend-dev, infra-dev) that execute in parallel waves, and domain-scoped reviewers that review in parallel. The existing SDK subagent infrastructure (AgentDefinition + Task tool) handles all delegation — no new framework needed.

**Tech Stack:** Python 3.11, Claude Agent SDK v0.1.54, existing builder pipeline

---

## Table of Contents

1. [Agent Team Structure](#1-agent-team-structure)
2. [Codebase Reference Map](#2-codebase-reference-map)
3. [SDK Reference](#3-sdk-reference)
4. [Artifact Schemas](#4-artifact-schemas)
5. [Task Breakdown: config-architect](#5-task-breakdown-config-architect)
6. [Task Breakdown: prompt-engineer](#6-task-breakdown-prompt-engineer)
7. [Task Breakdown: pipeline-engineer](#7-task-breakdown-pipeline-engineer)
8. [Task Breakdown: review-agent](#8-task-breakdown-review-agent)
9. [Task Breakdown: test-agent](#9-task-breakdown-test-agent)
10. [Definition of Done](#10-definition-of-done)

---

## 1. Agent Team Structure

### Team Members

| Agent | Role | Files Owned | Depends On |
|-------|------|-------------|------------|
| **config-architect** | Config dataclasses, depth gating, state | `config.py`, `state.py` | None (starts immediately) |
| **prompt-engineer** | All prompt constants | `agents.py` (prompt constants ONLY) | None (starts immediately, uses spec below) |
| **pipeline-engineer** | Agent registration, CLI wiring, validators | `agents.py` (build_agent_definitions), `cli.py`, NEW `ownership_validator.py` | config-architect + prompt-engineer |
| **review-agent** | Cross-cutting review, SDK verification | Reads all files, edits none | All code agents |
| **test-agent** | Unit tests, integration tests, simulation | `tests/test_enterprise_*.py` | All code agents |

### Communication Protocol

```
Wave 1: config-architect + prompt-engineer (PARALLEL)
         ↓ CONFIG_READY + PROMPTS_READY (SendMessage to pipeline-engineer)
Wave 2: pipeline-engineer
         ↓ PIPELINE_READY (SendMessage to review-agent + test-agent)
Wave 3: review-agent + test-agent (PARALLEL)
         ↓ REVIEW_COMPLETE + TESTS_COMPLETE (SendMessage to coordinator)
Wave 4: Fix cycle if any agent reports issues
```

### Message Types

- `CONFIG_READY` — config-architect → pipeline-engineer: "Config dataclasses and depth gating complete"
- `PROMPTS_READY` — prompt-engineer → pipeline-engineer: "All prompt constants written"
- `PIPELINE_READY` — pipeline-engineer → review-agent, test-agent: "All code changes complete"
- `REVIEW_COMPLETE` — review-agent → coordinator: findings list (PASS/FAIL per check)
- `TESTS_COMPLETE` — test-agent → coordinator: pass/fail counts
- `FIX_REQUIRED` — review-agent → specific agent: "Fix needed in file X at line Y"

---

## 2. Codebase Reference Map

### File: `src/agent_team_v15/config.py`

| Reference | Line | Purpose |
|-----------|------|---------|
| `DepthConfig` dataclass | 29-45 | Depth levels and keyword detection |
| `DepthConfig.keyword_map` | 33-45 | Keywords that trigger each depth |
| `DEPTH_AGENT_COUNTS` | 760-777 | Agent count ranges per depth per phase |
| `PhaseLeadConfig` | 521-528 | Per-lead config (enabled, model, tools, max_sub_agents) |
| `PhaseLeadsConfig` | 531-560 | All 6 lead configs + handoff settings |
| `AgentTeamsConfig` | 563-585 | Team backend config (enabled, model, timeouts) |
| `PostOrchestrationScanConfig` | 295-316 | Scan toggles and fix pass limits |
| `AgentTeamConfig` | 705+ | Top-level config (has orchestrator, depth, phase_leads, agent_teams, etc.) |
| `apply_depth_quality_gating()` | 798-951 | Depth-based feature gating — quick/standard/thorough/exhaustive blocks |
| Quick depth block | 824-878 | Disables most features |
| Standard depth block | 880-897 | Enables phase_leads, agent_teams, contract_engine |
| Thorough depth block | 899-922 | Enables audit_team, e2e_testing, browser_testing |
| Exhaustive depth block | 924-951 | Max everything |
| `_gate()` helper | ~790 | `_gate(key, value, obj, attr)` — sets obj.attr = value unless user override exists |

### File: `src/agent_team_v15/agents.py`

| Reference | Line | Purpose |
|-----------|------|---------|
| `ORCHESTRATOR_SYSTEM_PROMPT` | 67 | Monolithic orchestrator prompt (3000+ lines) |
| `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` | 1492-1615 | Team-mode orchestrator prompt (Task tool delegation) |
| Phase lead coordination section | 1519-1577 | Delegation sequence, completion criteria |
| `_TEAM_COMMUNICATION_PROTOCOL` | 3314-3355 | SDK subagent return format protocol |
| `PLANNING_LEAD_PROMPT` | 3360-3416 | Planning lead responsibilities |
| `ARCHITECTURE_LEAD_PROMPT` | 3418-3460 | Architecture lead responsibilities |
| `CODING_LEAD_PROMPT` | 3462-3502 | Coding lead — wave execution, domain agents |
| `REVIEW_LEAD_PROMPT` | 3504-3548 | Review lead — convergence, domain reviewers |
| `TESTING_LEAD_PROMPT` | 3550-3596 | Testing lead responsibilities |
| `AUDIT_LEAD_PROMPT` | 3598-3700 | Audit lead responsibilities |
| `INTEGRATION_AGENT_PROMPT` | 3241-3270 | Handles shared file declarations atomically |
| `build_agent_definitions()` | 3710-3953 | Builds all AgentDefinition dicts |
| Phase lead agent registration | 3854-3917 | Where phase leads are conditionally registered |
| MCP server access per lead | 3880-3901 | Context7, Sequential Thinking per lead |
| `get_orchestrator_system_prompt()` | 5016-5020 | Selects team vs monolithic prompt |

### File: `src/agent_team_v15/cli.py`

| Reference | Line | Purpose |
|-----------|------|---------|
| `_build_options()` | 298-384 | Builds ClaudeAgentOptions with agents + MCP |
| Agent defs conversion | 330-333 | Converts dicts to AgentDefinition objects |
| MCP servers loaded | 310 | `get_contract_aware_servers(config)` |
| allowed_tools computed | 359 | `recompute_allowed_tools(_BASE_TOOLS, mcp_servers)` |
| Phase leads prompt injection | 695-707 | `[PHASE LEADS ACTIVE]` injection |
| Milestone mode injection | 1535-1553 | Same pattern for milestone builds |
| Post-orchestration scans | 7320-7416 | All 12 scans with fix loops |

### File: `src/agent_team_v15/state.py`

| Reference | Line | Purpose |
|-----------|------|---------|
| `RunState` dataclass | 20-61 | All run state fields |
| `save_state()` | 277-345 | Atomic state persistence |
| `load_state()` | 353-404 | State recovery |

### File: `src/agent_team_v15/scheduler.py`

| Reference | Line | Purpose |
|-----------|------|---------|
| `ExecutionWave` dataclass | 56-62 | Wave with task IDs + conflicts |
| `compute_execution_waves()` | 721-770 | Topological sort into parallel waves |
| `detect_file_conflicts()` | 778-820 | Finds write-write conflicts in a wave |
| `ScheduleResult` dataclass | 74-80 | Complete scheduling output |

### File: `src/agent_team_v15/mcp_servers.py`

| Reference | Line | Purpose |
|-----------|------|---------|
| `_BASE_TOOLS` | 106-109 | `["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Task", "WebSearch", "WebFetch"]` |
| Context7 tool names | 99-100 | `mcp__context7__resolve-library-id`, `mcp__context7__query-docs` |
| Sequential Thinking tool | 82 | `mcp__sequential-thinking__sequentialthinking` |
| `recompute_allowed_tools()` | 141-163 | Combines base tools + MCP tool names |

### File: `src/agent_team_v15/schema_validator.py` (PATTERN REFERENCE)

| Reference | Purpose |
|-----------|---------|
| `SchemaFinding` dataclass | Pattern for `OwnershipFinding` — check, severity, message, suggestion |
| `SchemaValidationReport` | Pattern for validation report structure |
| `run_schema_validation()` | Pattern for `run_ownership_gate()` |

---

## 3. SDK Reference

### AgentDefinition (claude_agent_sdk v0.1.54)

```python
@dataclass
class AgentDefinition:
    description: str                    # When to use this agent
    prompt: str                         # System prompt
    tools: list[str] | None = None      # Tool allowlist (None = inherit all)
    disallowedTools: list[str] | None = None
    model: str | None = None            # "sonnet", "opus", "haiku", "inherit"
    mcpServers: list[str | dict] | None = None  # MCP server refs
    background: bool | None = None      # False required for MCP access!
    maxTurns: int | None = None
    effort: Literal["low","medium","high","max"] | int | None = None
    permissionMode: PermissionMode | None = None
```

### Domain Agent Registration Pattern

```python
# In build_agent_definitions(), after phase lead registration:
if config.enterprise_mode.enabled and config.enterprise_mode.domain_agents:
    _context7_tools = (
        ["mcp__context7__resolve-library-id", "mcp__context7__query-docs"]
        if "context7" in mcp_servers else []
    )
    _context7_ref = ["context7"] if "context7" in mcp_servers else []

    agents["backend-dev"] = {
        "description": "Domain specialist: NestJS/Prisma backend development",
        "prompt": BACKEND_DEV_PROMPT,
        "tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"] + _context7_tools,
        "mcpServers": _context7_ref or None,
        "background": False if _context7_ref else None,
        "model": config.agents.get("code-writer", AgentConfig()).model,
    }
    # ... same for frontend-dev, infra-dev
```

### How Coding-Lead Dispatches Domain Agents

The coding-lead (itself a Task subagent) uses the **Agent** tool to spawn domain agents:
```
Agent("backend-dev", "Implement auth service. Your files: backend/src/auth/**. Requirements: REQ-011..015. Contracts: {scoped_contracts}")
```

The Agent tool inherits the parent session's available agents and MCP servers.

---

## 4. Artifact Schemas

### OWNERSHIP_MAP.json

```json
{
  "version": 1,
  "build_id": "run-id-here",
  "domains": {
    "auth-backend": {
      "tech_stack": "nestjs+prisma",
      "agent_type": "backend-dev",
      "files": ["backend/src/auth/**", "backend/src/prisma/prisma.service.ts"],
      "requirements": ["REQ-011", "REQ-012", "REQ-013", "REQ-014", "REQ-015"],
      "dependencies": ["infrastructure"],
      "shared_reads": ["backend/prisma/schema.prisma", "backend/src/app.module.ts"]
    },
    "tasks-backend": {
      "tech_stack": "nestjs+prisma",
      "agent_type": "backend-dev",
      "files": ["backend/src/tasks/**"],
      "requirements": ["REQ-016", "REQ-017", "REQ-018", "REQ-019", "REQ-020"],
      "dependencies": ["infrastructure", "auth-backend"],
      "shared_reads": ["backend/prisma/schema.prisma"]
    },
    "dashboard-frontend": {
      "tech_stack": "nextjs+react+tailwind",
      "agent_type": "frontend-dev",
      "files": ["frontend/app/dashboard/**", "frontend/components/**"],
      "requirements": ["REQ-027", "REQ-028", "REQ-029", "REQ-030"],
      "dependencies": ["auth-backend", "tasks-backend"],
      "shared_reads": ["frontend/lib/api.ts", "frontend/lib/auth.ts"]
    },
    "infrastructure": {
      "tech_stack": "docker+postgres",
      "agent_type": "infra-dev",
      "files": ["docker-compose.yml", "*.Dockerfile", "backend/.env*", "frontend/.env*"],
      "requirements": ["REQ-001", "REQ-002", "REQ-003"],
      "dependencies": [],
      "shared_reads": []
    }
  },
  "waves": [
    {"id": 1, "name": "foundation", "domains": ["infrastructure"], "parallel": false},
    {"id": 2, "name": "backend-services", "domains": ["auth-backend", "tasks-backend"], "parallel": true},
    {"id": 3, "name": "frontend", "domains": ["dashboard-frontend"], "parallel": true},
    {"id": 4, "name": "integration", "domains": ["wiring"], "parallel": false}
  ],
  "shared_scaffolding": [
    "backend/prisma/schema.prisma",
    "backend/src/app.module.ts",
    "backend/src/main.ts",
    "frontend/lib/api.ts",
    "frontend/lib/auth.ts"
  ]
}
```

### WAVE_STATE.json

```json
{
  "current_wave": 2,
  "total_waves": 4,
  "completed_waves": [
    {
      "id": 1,
      "name": "foundation",
      "domains_completed": ["infrastructure"],
      "files_created": ["docker-compose.yml", "backend/.env", "backend/.env.example"],
      "issues": [],
      "agent_cost": 0.45
    }
  ],
  "pending_fixes": [],
  "scaffolding_complete": true,
  "scaffolding_files": ["backend/prisma/schema.prisma", "backend/src/app.module.ts"]
}
```

---

## 5. Task Breakdown: config-architect

**Files:** `src/agent_team_v15/config.py`, `src/agent_team_v15/state.py`

### Task C1: Add EnterpriseModeConfig dataclass

**Location:** `config.py`, insert after `PhaseLeadsConfig` (~line 560)

```python
@dataclass
class EnterpriseModeConfig:
    """Configuration for enterprise-scale builds (150K+ LOC).

    When enabled, the architecture phase produces a domain OWNERSHIP_MAP.json
    that drives parallel domain-specialized coding agents and scoped review.
    Requires phase_leads.enabled = True.
    """
    enabled: bool = False
    # Multi-step architecture (design → partition → contracts → scaffold)
    multi_step_architecture: bool = True
    # Domain-specialized coding agents (backend-dev, frontend-dev, infra-dev)
    domain_agents: bool = True
    max_backend_devs: int = 3
    max_frontend_devs: int = 2
    max_infra_devs: int = 1
    # Parallel domain-scoped review
    parallel_review: bool = True
    # Wave state persistence between coding-lead invocations
    wave_state_persistence: bool = True
    # Ownership validation gate (block on critical findings)
    ownership_validation_gate: bool = True
    # Architecture produces shared scaffolding files before coding
    scaffold_shared_files: bool = True
```

### Task C2: Add to AgentTeamConfig

**Location:** `config.py`, in `AgentTeamConfig` dataclass (~line 705)

Add field: `enterprise_mode: EnterpriseModeConfig = field(default_factory=EnterpriseModeConfig)`

### Task C3: Add enterprise to DEPTH_AGENT_COUNTS

**Location:** `config.py`, line 760-777

```python
    "enterprise": {
        "planning": (8, 12), "research": (5, 8), "architecture": (3, 5),
        "coding": (8, 15), "review": (5, 10), "testing": (3, 5),
    },
```

### Task C4: Add enterprise keywords

**Location:** `config.py`, `DepthConfig.keyword_map` (lines 33-45)

Add: `"enterprise": ["enterprise", "department", "large-scale", "mega-build"]`

### Task C5: Add enterprise depth gating block

**Location:** `config.py`, after exhaustive block in `apply_depth_quality_gating()` (~line 951)

```python
    elif depth == "enterprise":
        # Enterprise: everything from exhaustive PLUS domain partitioning
        # First apply all exhaustive gates
        _gate("audit_team.enabled", True, config.audit_team, "enabled")
        _gate("audit_team.max_reaudit_cycles", 3, config.audit_team, "max_reaudit_cycles")
        _gate("tech_research.max_queries_per_tech", 6, config.tech_research, "max_queries_per_tech")
        _gate("e2e_testing.enabled", True, config.e2e_testing, "enabled")
        _gate("e2e_testing.max_fix_retries", 3, config.e2e_testing, "max_fix_retries")
        _gate("browser_testing.enabled", True, config.browser_testing, "enabled")
        _gate("post_orchestration_scans.max_scan_fix_passes", 3, config.post_orchestration_scans, "max_scan_fix_passes")
        _gate("contract_engine.enabled", True, config.contract_engine, "enabled")
        _gate("codebase_intelligence.enabled", True, config.codebase_intelligence, "enabled")
        _gate("agent_teams.enabled", True, config.agent_teams, "enabled")
        _gate("phase_leads.enabled", True, config.phase_leads, "enabled")
        # Enterprise-specific gates
        _gate("enterprise_mode.enabled", True, config.enterprise_mode, "enabled")
        _gate("enterprise_mode.domain_agents", True, config.enterprise_mode, "domain_agents")
        _gate("enterprise_mode.parallel_review", True, config.enterprise_mode, "parallel_review")
        _gate("enterprise_mode.ownership_validation_gate", True, config.enterprise_mode, "ownership_validation_gate")
        _gate("enterprise_mode.scaffold_shared_files", True, config.enterprise_mode, "scaffold_shared_files")
        # Higher convergence budget for large builds
        _gate("convergence.max_cycles", 5, config.convergence, "max_cycles")
```

### Task C6: Extend RunState

**Location:** `state.py`, RunState dataclass (~line 46, after agent_teams_active)

```python
    # Enterprise mode tracking
    enterprise_mode_active: bool = False
    ownership_map_validated: bool = False
    waves_completed: int = 0
    domain_agents_deployed: int = 0
```

Also update `load_state()` (~line 386) to deserialize these fields with `_expect()`.

### Task C7: Wire enterprise_mode field in YAML config loading

**Location:** `config.py`, in the config loading function (search for `enterprise_mode` or the YAML loading section)

Ensure `enterprise_mode:` YAML key is deserialized into `EnterpriseModeConfig`.

**Send `CONFIG_READY` to pipeline-engineer when all C tasks are done.**

---

## 6. Task Breakdown: prompt-engineer

**Files:** `src/agent_team_v15/agents.py` (prompt constants ONLY — do NOT modify `build_agent_definitions()`)

### Task P1: Write ENTERPRISE_ARCHITECTURE_STEPS

Insert new constant after `ARCHITECTURE_LEAD_PROMPT` (~line 3460):

```python
ENTERPRISE_ARCHITECTURE_STEPS = r"""
============================================================
ENTERPRISE MODE: MULTI-STEP ARCHITECTURE PROTOCOL
============================================================

When the orchestrator indicates [ENTERPRISE MODE], execute architecture in 4 sequential steps.
The orchestrator will invoke you ONCE PER STEP with the step number.

### Step 1: High-Level Design → ARCHITECTURE.md
- Read REQUIREMENTS.md thoroughly
- Identify service boundaries (which groups of requirements form independent services?)
- Define tech stack per service
- Define data model overview (entities, relationships)
- Write .agent-team/ARCHITECTURE.md with: service list, tech stacks, data model, key design decisions

### Step 2: Domain Partitioning → OWNERSHIP_MAP.json
- Read ARCHITECTURE.md (from Step 1)
- Partition ALL files into non-overlapping domains
- Assign EVERY requirement to exactly one domain
- Define execution waves with dependencies (infrastructure first, then backend, then frontend, then integration)
- Identify shared scaffolding files (schema.prisma, app.module.ts, docker-compose.yml)
- Write .agent-team/OWNERSHIP_MAP.json following the exact schema:
{ownership_map_schema}

### Step 3: API Contracts → CONTRACTS.json
- Read ARCHITECTURE.md + OWNERSHIP_MAP.json
- Define API endpoints per service with request/response shapes
- Define event schemas for cross-service communication
- Write .agent-team/CONTRACTS.json

### Step 4: Shared Scaffolding
- Read OWNERSHIP_MAP.json "shared_scaffolding" list
- Write ALL shared scaffolding files with complete content:
  - prisma/schema.prisma with ALL models (not just one service)
  - app.module.ts with ALL module imports
  - docker-compose.yml with ALL services
  - Shared type files, API client stubs
- These files are COMPLETE — domain agents will NOT modify them

### Return Format per Step
```
## Architecture Step {N} Result
- Status: COMPLETE | BLOCKED
- Artifacts created: [list]
- Key decisions: [list]
- Ready for next step: yes/no
```
""".strip()
```

### Task P2: Write BACKEND_DEV_PROMPT

Insert after ENTERPRISE_ARCHITECTURE_STEPS:

```python
BACKEND_DEV_PROMPT = r"""
You are a BACKEND DEVELOPMENT SPECIALIST in an enterprise-scale Agent Team build.
Your expertise: NestJS, Prisma ORM, PostgreSQL, JWT authentication, REST APIs, TypeORM.

You are assigned a SPECIFIC DOMAIN from the OWNERSHIP_MAP.json. You ONLY write files
within your assigned domain. You do NOT touch shared scaffolding files.

### Your Workflow
1. Read your domain assignment (files, requirements, contracts) from the task prompt
2. Read the shared scaffolding files (schema.prisma, app.module.ts) to understand the foundation
3. Read CONTRACTS.json for your API endpoints
4. Implement ALL your assigned requirements
5. Write COMPLETE, production-ready code — no stubs, no TODOs, no mock data

### Code Standards
- Every @Injectable must be in its module's providers array
- Every module using JwtAuthGuard must import AuthModule
- Use proper @Module imports — NestJS DI requires explicit wiring
- DTOs use class-validator decorators
- Services use PrismaService (already provided in shared scaffolding)
- Controllers handle errors with proper HTTP exceptions

### Integration Protocol
- You ONLY write files matching your assigned glob patterns
- If you need to modify a shared file (schema.prisma, app.module.ts), write an
  INTEGRATION DECLARATION instead — a markdown file at .agent-team/declarations/{your-domain}.md
  describing what changes are needed. The integration-agent will apply them.
- Reference shared types by importing from their existing paths

### Output
End with a structured Phase Result:
```
## Domain Result: {domain-name}
- Status: COMPLETE | PARTIAL
- Files created: [list with line counts]
- Requirements implemented: [REQ-xxx list]
- Integration declarations: [list if any]
- Issues encountered: [list if any]
```
""".strip()
```

### Task P3: Write FRONTEND_DEV_PROMPT

Same structure as P2, but specialized for:
- Next.js 14 App Router, React Server Components, Client Components
- Tailwind CSS with design tokens from tailwind.config.ts
- API client integration (fetch from shared api.ts)
- JWT token handling, route guards, middleware
- Accessible components (focus rings, ARIA labels, semantic HTML)

### Task P4: Write INFRA_DEV_PROMPT

Same structure but specialized for:
- docker-compose.yml with proper networking, health checks, volumes
- Dockerfiles (multi-stage builds for Node.js)
- Environment files (.env, .env.example, .env.test)
- Database migrations (Prisma migrate)
- CI configuration if applicable
- This agent runs in Wave 1 (foundation) — no dependencies on other domains

### Task P5: Extend TEAM_ORCHESTRATOR_SYSTEM_PROMPT for enterprise

**Location:** ~line 1577, BEFORE the closing `"""` of `TEAM_ORCHESTRATOR_SYSTEM_PROMPT`

Insert new section:

```python
============================================================
ENTERPRISE MODE (150K+ LOC Builds)
============================================================

When [ENTERPRISE MODE] is indicated in your task prompt:

### Multi-Step Architecture
Delegate to architecture-lead FOUR TIMES (one per step):
1. Task("architecture-lead", "ENTERPRISE STEP 1: Create ARCHITECTURE.md. Requirements: {req_summary}")
2. Task("architecture-lead", "ENTERPRISE STEP 2: Create OWNERSHIP_MAP.json from ARCHITECTURE.md")
3. Task("architecture-lead", "ENTERPRISE STEP 3: Create CONTRACTS.json from ARCHITECTURE.md + OWNERSHIP_MAP.json")
4. Task("architecture-lead", "ENTERPRISE STEP 4: Write shared scaffolding files per OWNERSHIP_MAP.json")

After Step 2, VALIDATE the ownership map:
- Read .agent-team/OWNERSHIP_MAP.json
- Verify: no file overlaps between domains
- Verify: every REQ-xxx is assigned to exactly one domain
- If validation fails, re-invoke architecture-lead with the errors

### Wave-Based Coding
Delegate to coding-lead ONCE PER WAVE:
- Read OWNERSHIP_MAP.json to get the wave plan
- For wave N: Task("coding-lead", "ENTERPRISE WAVE {N}: Execute domains {domain_list}. Read OWNERSHIP_MAP.json and WAVE_STATE.json for context.")
- After each wave, verify WAVE_STATE.json was updated
- Continue until all waves complete

### Domain-Scoped Review
Delegate to review-lead with ownership context:
- Task("review-lead", "ENTERPRISE REVIEW: Read OWNERSHIP_MAP.json. Deploy parallel domain reviewers.")
- Review-lead spawns one reviewer per domain using the ownership map

### Completion
Enterprise build is complete when:
1. All architecture steps produced their artifacts
2. Ownership map validated
3. All coding waves completed (WAVE_STATE.json shows all waves done)
4. Review achieves 100% convergence across all domains
5. Testing passes
6. Audit findings resolved
```

### Task P6: Extend CODING_LEAD_PROMPT for enterprise

**Location:** End of CODING_LEAD_PROMPT (~line 3502), BEFORE closing `"""`.

Insert:

```python
### Enterprise Mode: Ownership-Map-Driven Execution

When your task prompt contains "ENTERPRISE WAVE":

1. Read .agent-team/OWNERSHIP_MAP.json
2. Read .agent-team/WAVE_STATE.json (if exists — first wave won't have it)
3. Identify domains for this wave from the wave plan
4. For EACH domain in this wave:
   a. Read the domain's tech_stack to select agent type (backend-dev, frontend-dev, infra-dev)
   b. Read the domain's files list, requirements, and scoped contracts
   c. Deploy the domain agent: Agent("{agent_type}", "Domain: {domain_name}. Files: {files}. Requirements: {reqs}. Contracts: {contracts}")
   d. Deploy agents for PARALLEL domains simultaneously
5. Collect results from all domain agents
6. Write/update .agent-team/WAVE_STATE.json with completed wave data
7. If any domain agent reported PARTIAL, add to pending_fixes
8. Return wave results to orchestrator
```

### Task P7: Extend REVIEW_LEAD_PROMPT for enterprise

**Location:** End of REVIEW_LEAD_PROMPT (~line 3548), BEFORE closing `"""`.

Insert:

```python
### Enterprise Mode: Domain-Scoped Parallel Review

When your task prompt contains "ENTERPRISE REVIEW":

1. Read .agent-team/OWNERSHIP_MAP.json
2. For EACH domain in the ownership map:
   a. Deploy a code-reviewer sub-agent scoped to that domain's files
   b. Give it ONLY the requirements assigned to that domain
   c. Deploy ALL domain reviewers in PARALLEL
3. Collect convergence results from all domain reviewers
4. Aggregate: total [x] / total requirements across all domains
5. For items marked [ ], include which domain owns the fix
6. Return aggregated convergence to orchestrator
```

**Send `PROMPTS_READY` to pipeline-engineer when all P tasks are done.**

---

## 7. Task Breakdown: pipeline-engineer

**Files:** `src/agent_team_v15/agents.py` (build_agent_definitions only), `src/agent_team_v15/cli.py`, NEW `src/agent_team_v15/ownership_validator.py`

### Task L1: Create ownership_validator.py

**New file:** `src/agent_team_v15/ownership_validator.py`

Pattern after `schema_validator.py`. ~200 lines.

```python
"""Ownership map validation for enterprise-mode builds."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

_logger = logging.getLogger(__name__)


@dataclass
class OwnershipFinding:
    """A single ownership map validation finding."""
    check: str       # "OWN-001" through "OWN-007"
    severity: str    # "critical", "high", "medium"
    message: str
    domain: str      # Which domain is affected
    suggestion: str


@dataclass
class OwnershipValidationReport:
    """Result of ownership map validation."""
    findings: list[OwnershipFinding]
    domains_checked: int
    requirements_assigned: int
    requirements_total: int
    waves_valid: bool
    passed: bool  # True if no critical findings


def validate_ownership_map(
    ownership_map: dict,
    requirements_ids: list[str] | None = None,
) -> list[OwnershipFinding]:
    """Validate an OWNERSHIP_MAP.json against integrity rules.

    Checks:
    - OWN-001: File glob overlap between domains (critical)
    - OWN-002: Requirement not assigned to any domain (critical)
    - OWN-003: Domain has no files assigned (high)
    - OWN-004: Domain has no requirements assigned (high)
    - OWN-005: Circular wave dependency (critical)
    - OWN-006: Scaffolding file claimed by a domain (high)
    - OWN-007: Domain references non-existent requirement (medium)
    """
    findings: list[OwnershipFinding] = []
    domains = ownership_map.get("domains", {})
    waves = ownership_map.get("waves", [])
    scaffolding = set(ownership_map.get("shared_scaffolding", []))

    # OWN-001: File overlap detection
    # ... (check all file globs across domains for overlaps)

    # OWN-002: Unassigned requirements
    # ... (compare all REQ-xxx in requirements_ids against domain assignments)

    # OWN-003 + OWN-004: Empty domains
    # ...

    # OWN-005: Circular wave dependencies
    # ... (topological sort on domain dependency graph)

    # OWN-006: Scaffolding in domain files
    # ... (check domain files against shared_scaffolding list)

    # OWN-007: Non-existent requirement references
    # ...

    return findings


def run_ownership_gate(project_path: Path) -> tuple[bool, list[OwnershipFinding]]:
    """Run ownership validation as a blocking gate.

    Returns (passed, findings). Blocks on critical findings.
    """
    ownership_path = project_path / ".agent-team" / "OWNERSHIP_MAP.json"
    if not ownership_path.is_file():
        return True, []  # No map = not enterprise mode, pass

    # ... load map, extract requirement IDs from REQUIREMENTS.md, validate
    findings = validate_ownership_map(ownership_map, requirement_ids)
    critical = any(f.severity == "critical" for f in findings)
    return not critical, findings
```

Implement ALL 7 checks with real logic (glob overlap detection, dependency cycle detection, etc.).

### Task L2: Register enterprise domain agents in build_agent_definitions()

**Location:** `agents.py`, after phase lead registration (~line 3917), before constraint injection (~line 3919)

```python
    # Enterprise domain-specialized agents — registered when enterprise mode is active
    if config.enterprise_mode.enabled and config.enterprise_mode.domain_agents:
        _context7_tools = (
            ["mcp__context7__resolve-library-id", "mcp__context7__query-docs"]
            if "context7" in mcp_servers else []
        )
        _context7_ref = ["context7"] if "context7" in mcp_servers else []

        _domain_agents = {
            "backend-dev": {
                "description": "Enterprise domain specialist: NestJS/Prisma backend services",
                "prompt": BACKEND_DEV_PROMPT,
                "tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"] + _context7_tools,
            },
            "frontend-dev": {
                "description": "Enterprise domain specialist: Next.js/React/Tailwind frontend",
                "prompt": FRONTEND_DEV_PROMPT,
                "tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"] + _context7_tools,
            },
            "infra-dev": {
                "description": "Enterprise domain specialist: Docker, CI/CD, migrations, configs",
                "prompt": INFRA_DEV_PROMPT,
                "tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
            },
        }

        _dev_model = config.agents.get("code-writer", AgentConfig()).model
        for agent_name, agent_def in _domain_agents.items():
            agent_def["model"] = _dev_model
            if _context7_ref and "mcp__context7" in str(agent_def.get("tools", [])):
                agent_def["mcpServers"] = _context7_ref
                agent_def["background"] = False
            agents[agent_name] = agent_def
```

### Task L3: Wire enterprise prompt injection in CLI

**Location:** `cli.py`, after the existing phase leads injection (~line 707)

Add a new branch:

```python
    if config.enterprise_mode.enabled:
        prompt += (
            "\n\n[ENTERPRISE MODE] This is a large-scale build with domain partitioning. "
            "Follow the ENTERPRISE MODE protocol in your system prompt. "
            "Architecture must produce OWNERSHIP_MAP.json. Coding executes per-wave. "
            "Review is domain-scoped."
        )
```

### Task L4: Add ownership validation to post-orchestration

**Location:** `cli.py`, in the post-orchestration section (~line 7320)

Add ownership validation call:

```python
    # Enterprise mode: ownership map validation
    if config.enterprise_mode.enabled and config.enterprise_mode.ownership_validation_gate:
        try:
            from .ownership_validator import run_ownership_gate
            _own_passed, _own_findings = run_ownership_gate(Path(cwd))
            if _own_findings:
                for f in _own_findings[:5]:
                    print_warning(f"[{f.check}] {f.message}")
                if not _own_passed:
                    print_warning("Ownership validation BLOCKED — critical findings detected.")
            else:
                print_info("Ownership validation: 0 findings (clean)")
        except Exception as exc:
            print_warning(f"Ownership validation failed (non-blocking): {exc}")
```

**Send `PIPELINE_READY` to review-agent and test-agent when all L tasks are done.**

---

## 8. Task Breakdown: review-agent

**Reads all modified files, writes nothing (reports findings only).**

### Review Checklist

1. **Config consistency:**
   - [ ] EnterpriseModeConfig fields match usage in apply_depth_quality_gating()
   - [ ] enterprise_mode field exists on AgentTeamConfig
   - [ ] DEPTH_AGENT_COUNTS has "enterprise" key
   - [ ] DepthConfig.keyword_map has "enterprise" key
   - [ ] RunState enterprise fields are deserialized in load_state()

2. **Prompt consistency:**
   - [ ] ENTERPRISE_ARCHITECTURE_STEPS references correct artifact names (OWNERSHIP_MAP.json, ARCHITECTURE.md, CONTRACTS.json)
   - [ ] BACKEND_DEV_PROMPT, FRONTEND_DEV_PROMPT, INFRA_DEV_PROMPT all include integration declaration protocol
   - [ ] All domain prompts include SDK subagent return format
   - [ ] TEAM_ORCHESTRATOR_SYSTEM_PROMPT enterprise section references correct Task tool calls
   - [ ] CODING_LEAD_PROMPT enterprise section reads OWNERSHIP_MAP.json and WAVE_STATE.json
   - [ ] REVIEW_LEAD_PROMPT enterprise section deploys parallel domain reviewers
   - [ ] No SendMessage/TeamCreate references in any new prompts

3. **Pipeline consistency:**
   - [ ] build_agent_definitions() registers domain agents when enterprise_mode.domain_agents is True
   - [ ] Domain agents have correct MCP access (context7 for backend-dev, frontend-dev; none for infra-dev)
   - [ ] Domain agents have background=False when mcpServers is set
   - [ ] ownership_validator.py follows schema_validator.py patterns
   - [ ] All 7 OWN checks are implemented with real logic
   - [ ] CLI prompt injection includes [ENTERPRISE MODE] tag
   - [ ] Post-orchestration calls run_ownership_gate()

4. **SDK correctness:**
   - [ ] AgentDefinition fields used correctly (mcpServers is list, not dict)
   - [ ] "Task" is in _BASE_TOOLS (already confirmed: line 108)
   - [ ] Domain agent tools lists include MCP tool names when mcpServers is set

5. **No regressions:**
   - [ ] Quick, standard, thorough, exhaustive depths unchanged
   - [ ] Existing phase lead behavior unchanged
   - [ ] Existing post-orchestration scans unchanged

**Send `REVIEW_COMPLETE` with detailed findings to coordinator.**

---

## 9. Task Breakdown: test-agent

**Files:** Creates `tests/test_enterprise_config.py`, `tests/test_enterprise_agents.py`, `tests/test_enterprise_simulation.py`

### test_enterprise_config.py

```python
"""Tests for enterprise mode configuration and depth gating."""
import pytest
from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating


class TestEnterpriseModeConfig:
    def test_enterprise_mode_defaults_disabled(self):
        c = AgentTeamConfig()
        assert c.enterprise_mode.enabled is False

    def test_enterprise_depth_enables_enterprise_mode(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, {})
        assert c.enterprise_mode.enabled is True
        assert c.enterprise_mode.domain_agents is True
        assert c.enterprise_mode.parallel_review is True
        assert c.enterprise_mode.ownership_validation_gate is True
        assert c.phase_leads.enabled is True
        assert c.agent_teams.enabled is True

    def test_enterprise_depth_higher_convergence(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, {})
        assert c.convergence.max_cycles >= 5

    def test_enterprise_depth_higher_agent_counts(self):
        from agent_team_v15.config import DEPTH_AGENT_COUNTS
        assert "enterprise" in DEPTH_AGENT_COUNTS
        assert DEPTH_AGENT_COUNTS["enterprise"]["coding"][1] >= 10

    def test_standard_depth_does_not_enable_enterprise(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("standard", c, {})
        assert c.enterprise_mode.enabled is False

    def test_enterprise_keyword_detection(self):
        c = AgentTeamConfig()
        assert "enterprise" in c.depth.keyword_map
```

### test_enterprise_agents.py

```python
"""Tests for enterprise domain agent registration."""
import pytest
from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating
from agent_team_v15.agents import build_agent_definitions


class TestEnterpriseDomainAgents:
    def _enterprise_config(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, {})
        return c

    def test_enterprise_registers_domain_agents(self):
        defs = build_agent_definitions(self._enterprise_config(), {"context7": {}})
        assert "backend-dev" in defs
        assert "frontend-dev" in defs
        assert "infra-dev" in defs

    def test_standard_does_not_register_domain_agents(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("standard", c, {})
        defs = build_agent_definitions(c, {})
        assert "backend-dev" not in defs

    def test_backend_dev_has_context7(self):
        defs = build_agent_definitions(self._enterprise_config(), {"context7": {}})
        tools = defs["backend-dev"]["tools"]
        assert "mcp__context7__query-docs" in tools

    def test_infra_dev_no_context7(self):
        defs = build_agent_definitions(self._enterprise_config(), {"context7": {}})
        tools = defs["infra-dev"]["tools"]
        assert "mcp__context7__query-docs" not in tools

    def test_domain_agents_have_required_fields(self):
        defs = build_agent_definitions(self._enterprise_config(), {})
        for name in ["backend-dev", "frontend-dev", "infra-dev"]:
            assert "description" in defs[name]
            assert "prompt" in defs[name]
            assert "tools" in defs[name]
            assert len(defs[name]["prompt"]) > 200

    def test_enterprise_still_has_phase_leads(self):
        defs = build_agent_definitions(self._enterprise_config(), {})
        assert "coding-lead" in defs
        assert "review-lead" in defs
        assert "architecture-lead" in defs
```

### test_enterprise_simulation.py

```python
"""Simulation tests for enterprise ownership validation and wave execution."""
import json
import pytest
from agent_team_v15.ownership_validator import validate_ownership_map, OwnershipFinding


class TestOwnershipValidation:
    def _valid_map(self):
        return {
            "version": 1,
            "domains": {
                "auth-backend": {
                    "tech_stack": "nestjs", "agent_type": "backend-dev",
                    "files": ["backend/src/auth/**"],
                    "requirements": ["REQ-001", "REQ-002"],
                    "dependencies": [], "shared_reads": []
                },
                "dashboard-frontend": {
                    "tech_stack": "nextjs", "agent_type": "frontend-dev",
                    "files": ["frontend/app/dashboard/**"],
                    "requirements": ["REQ-003", "REQ-004"],
                    "dependencies": ["auth-backend"], "shared_reads": []
                },
            },
            "waves": [
                {"id": 1, "name": "backend", "domains": ["auth-backend"], "parallel": False},
                {"id": 2, "name": "frontend", "domains": ["dashboard-frontend"], "parallel": False},
            ],
            "shared_scaffolding": ["backend/prisma/schema.prisma"]
        }

    def test_valid_map_passes(self):
        findings = validate_ownership_map(
            self._valid_map(), ["REQ-001", "REQ-002", "REQ-003", "REQ-004"]
        )
        critical = [f for f in findings if f.severity == "critical"]
        assert len(critical) == 0

    def test_file_overlap_detected(self):
        m = self._valid_map()
        m["domains"]["auth-backend"]["files"].append("frontend/app/dashboard/**")
        findings = validate_ownership_map(m)
        own001 = [f for f in findings if f.check == "OWN-001"]
        assert len(own001) > 0

    def test_unassigned_requirement_detected(self):
        findings = validate_ownership_map(
            self._valid_map(), ["REQ-001", "REQ-002", "REQ-003", "REQ-004", "REQ-005"]
        )
        own002 = [f for f in findings if f.check == "OWN-002"]
        assert len(own002) > 0

    def test_circular_dependency_detected(self):
        m = self._valid_map()
        m["domains"]["auth-backend"]["dependencies"] = ["dashboard-frontend"]
        m["domains"]["dashboard-frontend"]["dependencies"] = ["auth-backend"]
        findings = validate_ownership_map(m)
        own005 = [f for f in findings if f.check == "OWN-005"]
        assert len(own005) > 0

    def test_scaffolding_in_domain_detected(self):
        m = self._valid_map()
        m["domains"]["auth-backend"]["files"].append("backend/prisma/schema.prisma")
        findings = validate_ownership_map(m)
        own006 = [f for f in findings if f.check == "OWN-006"]
        assert len(own006) > 0

    def test_no_sendmessage_in_enterprise_prompts(self):
        from agent_team_v15.agents import (
            BACKEND_DEV_PROMPT, FRONTEND_DEV_PROMPT, INFRA_DEV_PROMPT,
            ENTERPRISE_ARCHITECTURE_STEPS,
        )
        for name, prompt in [
            ("backend-dev", BACKEND_DEV_PROMPT),
            ("frontend-dev", FRONTEND_DEV_PROMPT),
            ("infra-dev", INFRA_DEV_PROMPT),
            ("architecture-steps", ENTERPRISE_ARCHITECTURE_STEPS),
        ]:
            assert "SendMessage" not in prompt, f"{name} has SendMessage"
            assert "TeamCreate" not in prompt, f"{name} has TeamCreate"
```

### Run full test suite

After writing all test files:
```bash
python -m pytest tests/ --no-header --tb=short -q
```

Expected: ALL existing tests pass + all new enterprise tests pass.

**Send `TESTS_COMPLETE` with pass/fail counts to coordinator.**

---

## 10. Definition of Done

The implementation is COMPLETE when:

- [ ] `--depth enterprise` activates enterprise mode with all features
- [ ] Architecture-lead prompt includes 4-step enterprise protocol
- [ ] OWNERSHIP_MAP.json schema is defined and validated
- [ ] 3 domain-specialized agent prompts exist (backend-dev, frontend-dev, infra-dev)
- [ ] Domain agents registered in build_agent_definitions() with MCP access
- [ ] Coding-lead prompt includes ownership-map-driven wave execution
- [ ] Review-lead prompt includes domain-scoped parallel review
- [ ] ownership_validator.py implements all 7 OWN checks
- [ ] CLI injects [ENTERPRISE MODE] tag in orchestrator prompt
- [ ] Post-orchestration runs ownership validation gate
- [ ] RunState tracks enterprise mode fields
- [ ] All existing tests pass (no regressions)
- [ ] All new enterprise tests pass
- [ ] Review agent confirms cross-cutting consistency
