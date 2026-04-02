# Enterprise v2: Department Model Upgrade — Handoff Document

> **For the next Claude session:** This document contains everything you need to implement the department model upgrade. Read it fully before doing anything. Use Context7 and Sequential Thinking MCP as directed in Part 4.

**Date:** 2026-04-02
**Author:** Omar's builder team (5-agent handoff team)
**Project:** `C:\Projects\agent-team-v15`
**Predecessor:** Enterprise v1 (implemented same day — `--depth enterprise` with domain partitioning)

---

## Executive Summary

Enterprise v1 adds `--depth enterprise` mode with architecture-driven domain partitioning, parallel domain-specialized coding agents, and domain-scoped review. It works, is tested (52+ tests), and has been through 3 review rounds with 20+ agents.

**The bottleneck:** Each phase is handled by a SINGLE phase lead (one context window). At 150K+ LOC with 30+ requirements across 8+ domains, the coding-lead and review-lead become context-pressure bottlenecks — one agent trying to coordinate everything.

**The upgrade:** Replace single phase leads with **departments** — TeamCreate groups where a department head coordinates domain managers who dispatch workers. This distributes context across multiple windows, enables true parallel coordination with lateral communication (SendMessage), and reduces the load on any single agent by >50%.

**Scope:** Convert Coding and Review phases to departments. Planning, Architecture, Testing, and Audit stay as single leads.

---

## Table of Contents

1. [Current Enterprise Implementation (v1)](#part-1-current-enterprise-implementation-v1)
2. [Department Model Upgrade Specification (v2)](#part-2-department-model-upgrade-specification-v2)
3. [Prompt Engineering Guide](#part-3-prompt-engineering-guide)
4. [Research & Planning Guide (Context7 + Sequential Thinking)](#part-4-research--planning-guide)
5. [Implementation Roadmap & Risk Assessment](#part-5-implementation-roadmap--risk-assessment)

---

## Part 1: Current Enterprise Implementation (v1)

### 1.1 Config Layer (`src/agent_team_v15/config.py`)

#### EnterpriseModeConfig — line 566

```python
@dataclass
class EnterpriseModeConfig:
    enabled: bool = False
    multi_step_architecture: bool = True
    domain_agents: bool = True
    max_backend_devs: int = 3
    max_frontend_devs: int = 2
    max_infra_devs: int = 1
    parallel_review: bool = True
    wave_state_persistence: bool = True
    ownership_validation_gate: bool = True
    scaffold_shared_files: bool = True
```

`AgentTeamConfig.enterprise_mode` field at line 777. YAML loaded at lines 1870-1886. Depth-gated at lines 980-1007.

#### Key Config References

| Reference | Line | Purpose |
|-----------|------|---------|
| `DEPTH_AGENT_COUNTS["enterprise"]` | 801-804 | `coding: (8,15)`, `review: (5,10)` — highest counts |
| `apply_depth_quality_gating()` enterprise block | 980-1007 | Strict superset of exhaustive + enterprise-specific gates |
| `PhaseLeadsConfig` | 534-563 | Per-lead config: model, tools, max_sub_agents, idle_timeout |
| `AgentTeamsConfig` | 586-608 | max_teammates=5, wave_timeout=3600, phase_lead_max_turns=200 |
| `_gate()` helper | 847 | `_gate(key, value, target, attr)` — respects user overrides |
| Phase leads enabled at ALL depths | 904 | Universal: `_gate("phase_leads.enabled", True, ...)` |
| Agent teams enabled at ALL depths | 903 | Universal: `_gate("agent_teams.enabled", True, ...)` |

### 1.2 Agent Layer (`src/agent_team_v15/agents.py`)

#### Prompt Constants

| Constant | Line | Purpose |
|----------|------|---------|
| `_OWNERSHIP_MAP_SCHEMA` | 3505 | JSON template for OWNERSHIP_MAP.json structure |
| `ENTERPRISE_ARCHITECTURE_STEPS` | 3525 | 4-step protocol: ARCHITECTURE.md → OWNERSHIP_MAP.json → CONTRACTS.json → scaffolding |
| `BACKEND_DEV_PROMPT` | 3574 | NestJS/Prisma worker (1,755 chars) |
| `FRONTEND_DEV_PROMPT` | 3615 | Next.js 14/React/Tailwind worker (2,059 chars) |
| `INFRA_DEV_PROMPT` | 3658 | Docker/CI/migrations worker (1,954 chars) |
| `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` enterprise section | 1613-1651 | 4 Task() calls, wave coding, domain review, 6 completion criteria |
| `CODING_LEAD_PROMPT` enterprise extension | 3740-3755 | Agent() dispatch for domain agents per wave |
| `REVIEW_LEAD_PROMPT` enterprise extension | 3803-3816 | Parallel domain-scoped review |
| `_TEAM_COMMUNICATION_PROTOCOL` | 3357-3399 | SDK subagent rules: no SendMessage, structured Phase Result return |

#### Agent Registration (`build_agent_definitions()` — line 3978)

- Phase leads register at lines 4122-4189 when `phase_leads.enabled`
- Architecture-lead gets `ENTERPRISE_ARCHITECTURE_STEPS` appended when `enterprise_mode.enabled` (line 4130-4132)
- MCP servers (Context7, Sequential Thinking) assigned per lead (lines 4154-4173)
- Enterprise domain agents register at lines 4191-4223 when `enterprise_mode.enabled AND domain_agents`
- Three agents: backend-dev, frontend-dev, infra-dev with Context7 MCP (except infra-dev)
- `get_orchestrator_system_prompt()` (line 5346): returns TEAM prompt when `phase_leads.enabled`

### 1.3 Pipeline Layer (`src/agent_team_v15/cli.py`)

| Reference | Line | Purpose |
|-----------|------|---------|
| `--depth enterprise` | 4586 | CLI choices include enterprise |
| `[ENTERPRISE MODE]` injection | 709-715 | Appended to orchestrator task prompt |
| Ownership validation gate | 7334-7348 | Post-orchestration, lazy import, non-blocking |
| `_use_team_mode` | 4527, 6604-6665 | Set by `create_execution_backend()` |
| Team-mode audit fallthrough | 6874 | Checks `completed_phases` before skipping |
| Orchestrator session creation | 298-384 | `_build_options()` → `ClaudeAgentOptions` |

### 1.4 Ownership Validator (`src/agent_team_v15/ownership_validator.py`)

7+1 checks: OWN-000 (parse), OWN-001 (file overlap), OWN-002 (unassigned reqs), OWN-003 (empty files), OWN-004 (empty reqs), OWN-005 (circular deps), OWN-006 (scaffolding collision), OWN-007 (invalid req refs). `run_ownership_gate()` at line 267 integrates with cli.py.

### 1.5 State (`src/agent_team_v15/state.py`)

Enterprise fields on `RunState` (lines 48-51): `enterprise_mode_active`, `ownership_map_validated`, `waves_completed`, `domain_agents_deployed`. Serialized via `asdict()`, deserialized via `_expect()`.

### 1.6 SDK Patterns

- **AgentDefinition**: dict with `description`, `prompt`, `tools`, `model`, optional `mcpServers` (list[str]), `background` (False for MCP)
- **Task tool**: Orchestrator → phase leads (sequential delegation)
- **Agent tool**: Phase leads → workers (parallel dispatch)
- **Constraint**: "Subagents cannot spawn their own subagents" — **VERIFY via Context7 before implementing departments**
- **3-level hierarchy**: Orchestrator → Phase leads → Workers

### 1.7 Test Coverage

| File | Tests | Coverage |
|------|-------|---------|
| `tests/test_enterprise_config.py` | 6 | Config defaults, depth gating, agent counts |
| `tests/test_enterprise_agents.py` | 6 | Domain agent registration, MCP wiring |
| `tests/test_enterprise_simulation.py` | 7 | Ownership validation OWN-001 through OWN-007 |
| `tests/test_enterprise_final_simulation.py` | 30 | Config round-trip, agent registration, prompt content, depth comparison |
| `tests/verify_enterprise_live.py` | 12 sections | End-to-end verification script |

---

## Part 2: Department Model Upgrade Specification (v2)

### 2.1 What Is a Department

A **department** replaces a single phase lead with a `TeamCreate` group:

```
Department = {
    department_head:  coordinator (1) — routes, aggregates, never writes code
    managers:         domain-scoped (2-4) — dispatch workers, lateral communication
    workers:          task executors (N) — write code, review files
}
```

### 2.2 Which Phases Become Departments

| Phase | Department? | Rationale |
|-------|:-----------:|-----------|
| Planning | No | Sequential reasoning, not domain-parallelizable |
| Architecture | No | One architect must hold the entire system design |
| **Coding** | **YES** | Biggest bottleneck — true parallel domain execution |
| **Review** | **YES** | Domain-scoped parallel review with aggregated convergence |
| Testing | No (v2.1) | Test-runner parallelism already sufficient |
| Audit | No (v2.1) | Already has parallel auditors internally |

### 2.3 Coding Department

```
Coding Department (TeamCreate "build-coding-dept")
├── coding-dept-head ── reads OWNERSHIP_MAP, manages waves, aggregates results
├── backend-manager ── owns backend domains, spawns backend-dev workers
├── frontend-manager ── owns frontend domains, spawns frontend-dev workers
├── infra-manager ── owns infra domains (Wave 1 foundation)
└── integration-manager ── processes declarations, merges shared files
```

**Manager selection**: `tech_stack` → manager mapping (nestjs→backend, nextjs→frontend, docker→infra)

**Smart sizing**: ≤2 domains per tech-stack → manager does the work directly (no workers)

**Wave execution**: Department head dispatches managers per wave from OWNERSHIP_MAP.waves, collects results, triggers integration-manager, updates WAVE_STATE.json.

### 2.4 Review Department

```
Review Department (TeamCreate "build-review-dept")
├── review-dept-head ── assigns domain reviewers, aggregates convergence
├── backend-review-manager ── reviews backend domains in parallel
├── frontend-review-manager ── reviews frontend domains
└── cross-cutting-reviewer ── checks cross-domain wiring
```

### 2.5 Communication Protocol

**Intra-department** (SendMessage between managers):

| Message | Sender → Receiver | When |
|---------|-------------------|------|
| `DOMAIN_ASSIGNMENT` | dept-head → manager | Start of wave |
| `DOMAIN_COMPLETE` | manager → dept-head | Domain finished |
| `API_CHANGE` | manager → manager | Cross-domain API notification |
| `CONFLICT_DETECTED` | integration-mgr → manager | Declaration conflict |

**Inter-department** (orchestrator mediates):

| Message | Flow | When |
|---------|------|------|
| `PHASE_COMPLETE` | dept-head → orchestrator | All waves done |
| `FIX_REQUIRED` | review-dept → orchestrator → coding-dept | Review found issues |
| `CONVERGENCE_RESULT` | review-dept → orchestrator | Per-domain convergence |

### 2.6 Config Changes

New dataclasses:
```python
@dataclass
class DepartmentConfig:
    enabled: bool = False
    max_managers: int = 4
    max_workers_per_manager: int = 5
    communication_timeout: int = 300
    wave_timeout: int = 1800

@dataclass
class DepartmentsConfig:
    enabled: bool = False
    coding: DepartmentConfig = field(default_factory=lambda: DepartmentConfig(enabled=True, max_managers=4))
    review: DepartmentConfig = field(default_factory=lambda: DepartmentConfig(enabled=True, max_managers=3))
```

New field on `EnterpriseModeConfig`: `department_model: bool = False`

**Backwards compatible**: `department_model=False` (default) means v1 single leads execute as before.

### 2.7 OWNERSHIP_MAP Drives Departments

The existing OWNERSHIP_MAP.json already contains everything departments need:
- `domains` → manager assignments (by `agent_type`)
- `waves` → department execution order
- `shared_scaffolding` → integration-manager responsibility
- `dependencies` → cross-domain coordination needs

### 2.8 Convergence

Review department aggregates per-domain convergence → global ratio. Fix flow: review-dept-head → orchestrator → coding-dept-head → specific manager. Scoped fixes (not full rebuilds). Existing `convergence.max_cycles=15` applies to outer loop.

---

## Part 3: Prompt Engineering Guide

### 3.1 Prompt Hierarchy

```
Tier 0: Orchestrator (~15% context) — department registry, completion criteria
Tier 1: Department Head (~10%) — manager registry, wave protocol, progress tracking
Tier 2: Manager (~15%) — domain tech stack, worker dispatch, quality gates
Tier 3: Worker (~20%) — full implementation instructions, code standards
```

### 3.2 New Prompts Needed

| Prompt | Role | Tier |
|--------|------|------|
| `CODING_DEPARTMENT_HEAD_PROMPT` | Coordinates coding managers across waves | 1 |
| `BACKEND_MANAGER_PROMPT` | Owns backend domains, dispatches backend-dev workers | 2 |
| `FRONTEND_MANAGER_PROMPT` | Owns frontend domains, dispatches frontend-dev workers | 2 |
| `INFRA_MANAGER_PROMPT` | Owns infra domains, Wave 1 foundation | 2 |
| `INTEGRATION_MANAGER_PROMPT` | Cross-domain wiring, shared file merges | 2 |
| `REVIEW_DEPARTMENT_HEAD_PROMPT` | Coordinates domain reviewers, aggregates convergence | 1 |
| `DOMAIN_REVIEWER_PROMPT` | Per-domain review specialist | 2 |

### 3.3 Key Optimization Strategies

**Context slicing**: Don't pass full OWNERSHIP_MAP to every agent. Slice per tier:
- Department head: full map
- Manager: only their tech-stack domains + consumed API contracts
- Worker: only their specific domain entry + file assignments

**Message conciseness**: Embed in all prompts:
```
Status: one word (COMPLETE / PARTIAL / BLOCKED)
Files: list paths only, no descriptions
Issues: one line per issue (file:line — what's wrong)
Do NOT summarize what you did — the artifacts speak for themselves
```

**Anti-patterns to avoid**:
1. Don't give managers knowledge of OTHER managers' domains
2. Don't let workers make cross-domain decisions
3. Don't put coordination logic in worker prompts
4. Don't use overly long prompts for coordinators
5. Avoid "telephone game" — workers READ files directly, don't relay through managers

### 3.4 Production-Ready Prompt Templates

Three complete drafts are provided (see the full handoff doc or ask the agent team for them):
- **Coding Department Head** — wave execution protocol, manager selection by tech_stack, quality gates, failure handling
- **Backend Manager** — domain decomposition, worker dispatch, mock data scanning, integration declarations
- **Review Department Head** — parallel domain review, convergence aggregation, cross-cutting checks, fix routing

### 3.5 Prompt Migration Map

| Current | New | Change |
|---------|-----|--------|
| `CODING_LEAD_PROMPT` | Splits into dept-head + 4 manager prompts | Coordination → head, domains → managers |
| `REVIEW_LEAD_PROMPT` | Splits into dept-head + reviewer prompts | Aggregation → head, checking → reviewers |
| `BACKEND/FRONTEND/INFRA_DEV_PROMPT` | **Unchanged** | Stay as worker prompts under managers |
| `TEAM_ORCHESTRATOR` enterprise section | Simplified | Talks to dept-heads, not phase leads |
| `ENTERPRISE_ARCHITECTURE_STEPS` | **Unchanged** | Architecture stays as single lead |

---

## Part 4: Research & Planning Guide

### 4.1 Context7 Queries (Run First)

**Step 1**: `mcp__context7__resolve-library-id(query: "anthropic claude agent sdk")` → save as `{sdk_id}`

**Step 2**: Run these queries in order:

| # | Query | Critical? |
|---|-------|-----------|
| 1 | `query-docs({sdk_id}, "AgentDefinition subagent nesting limitation")` | **YES — blocks architecture** |
| 2 | `query-docs({sdk_id}, "TeamCreate agent teams communication")` | YES |
| 3 | `query-docs({sdk_id}, "SendMessage inter-agent messaging protocol")` | YES |
| 4 | `query-docs({sdk_id}, "agent teams vs subagents architecture")` | YES |
| 5 | `query-docs({sdk_id}, "MCP server access in nested agents")` | YES |
| 6-9 | Background, permissions, maxTurns, task coordination | Informational |

**Decision gate**: If query #1 confirms subagents can't spawn sub-subagents AND this applies to TeamCreate members, the department architecture must flatten (managers ARE the workers).

### 4.2 Sequential Thinking Sessions (Run After Context7)

5 planning sessions with exact prompts:
1. **Architecture Decision** — optimal department structure given SDK constraints
2. **Communication Protocol** — message types, storm prevention, conflict resolution
3. **Convergence** — multi-department fix flow, partial convergence tracking
4. **Config & Registration** — minimal config changes, CLI department lifecycle
5. **Context Slicing** — how to programmatically slice OWNERSHIP_MAP per tier

Each session includes the exact `mcp__sequential-thinking__sequentialthinking` call with full context about current codebase state, line references, and constraints.

### 4.3 SDK Verification Checklist (10 items)

Must-verify before implementing:
1. Can TeamCreate members spawn Agent subagents?
2. Message queue limits for SendMessage?
3. Orchestrator visibility into department messages?
4. TeamCreate member crash recovery?
5. Nested departments possible?
6. Team size limits?
7. TaskStop with team members?
8. MCP connection sharing across team members?
9. Runtime tool list modification?
10. Max concurrent agent count before rate limiting?

### 4.4 Research Execution Order

1. Context7 SDK queries → 2. SDK verification checklist → 3. Sequential Thinking session 1 (architecture) → 4. Session 4 (config) → 5. Sessions 2-3 (communication, convergence) → 6. Session 5 (context slicing) → 7. Framework doc queries → 8. Performance research

---

## Part 5: Implementation Roadmap

### 5.1 Phases

| Phase | Scope | Risk |
|-------|-------|------|
| **1. Foundation** | DepartmentConfig, registration, backwards compat | LOW |
| **2. Coding Department** | Dept head + 4 managers + wave execution | MEDIUM |
| **3. Review Department** | Dept head + domain reviewers + convergence | MEDIUM |
| **4. Testing/Audit** | Skip for v2.0 — defer to v2.1 | N/A |
| **5. Cross-Department** | Review → Coding fix flow via orchestrator | MEDIUM |

### 5.2 File Change Map

| File | Changes |
|------|---------|
| `config.py` | New DepartmentConfig, DepartmentsConfig dataclasses. department_model field. Validation. YAML loading. |
| `agents.py` | 7+ new prompt constants. Extended build_agent_definitions(). Context slicing helper. |
| `cli.py` | Department lifecycle. Department-aware wave execution. Cross-department fix routing. |
| `state.py` | New RunState fields: department_mode_active, departments_created, manager_count |
| **NEW** `department.py` | Department lifecycle, TeamCreate wiring, context slicing, message batching |
| `ownership_validator.py` | Domain-to-manager assignment validation |

### 5.3 Top Risks

1. **SDK nesting depth** (CRITICAL) — verify 3-level nesting works before writing code
2. **Message storms** (MEDIUM) — mitigate with batching at wave boundaries
3. **Coordination deadlocks** (MEDIUM) — mitigate with wave ordering from OWNERSHIP_MAP
4. **Increased cost** (MEDIUM) — mitigate with smart sizing (≤2 domains → no workers)
5. **Debug complexity** (LOW) — mitigate with structured logging and WAVE_STATE.json

### 5.4 Optimization Strategies

- **Smart sizing**: ≤2 domains → manager does work directly (no worker spawning)
- **Lazy creation**: Only coding + review get departments (configurable list)
- **Context slicing**: Each tier gets only relevant OWNERSHIP_MAP slice
- **Message batching**: Cross-domain notifications batched per wave
- **Progressive rollout**: v2.0 coding only → v2.1 review → v2.2 cross-dept → v2.3 testing

### 5.5 Definition of Done (14 items)

- [ ] DepartmentConfig dataclass with all fields
- [ ] Coding department head creates team and assigns managers
- [ ] Managers dispatch domain agents (or work directly for ≤2 domains)
- [ ] Lateral SendMessage works between managers
- [ ] Department head aggregates results → orchestrator
- [ ] Review department produces per-domain convergence
- [ ] Context slicing: each reviewer sees only their domain
- [ ] Cross-department fix flow: review → orchestrator → coding
- [ ] WAVE_STATE.json updated by department head
- [ ] All 52+ enterprise v1 tests still pass
- [ ] New department tests written and passing
- [ ] Live run with --depth enterprise produces department logs
- [ ] Smart sizing threshold enforced
- [ ] Backwards compatible: department_mode=False unchanged

---

## Quick Start for Next Session

1. Read this document fully
2. Run Context7 SDK queries from Part 4.1
3. Verify the 10-item SDK checklist from Part 4.3
4. Run Sequential Thinking sessions 1 and 4 from Part 4.2
5. Implement Phase 1 (config foundation) — zero behavioral change
6. Implement Phase 2 (coding department) — the big one
7. Test with `--depth enterprise --prd spec.md`
8. Implement Phase 3 (review department)
9. Implement Phase 5 (cross-department fix flow)
10. Run full test suite — zero regressions
