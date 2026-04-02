# Agent Team Phase Leads Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire phase leads as SDK subagents so the orchestrator delegates to them via the Task tool — replacing the unused subprocess/file-based approach.

**Architecture:** The Claude Agent SDK's native subagent mechanism (`AgentDefinition` + `Task` tool) is the correct integration path. Phase lead prompts and configs already exist — they just need to be activated and the orchestrator prompt rewritten to use `Task` instead of `TeamCreate`/`SendMessage`. The subprocess-based `AgentTeamsBackend` remains as an optional advanced backend but is no longer required for phase lead communication.

**Tech Stack:** Python, Claude Agent SDK (`AgentDefinition`, `ClaudeAgentOptions`), existing builder pipeline

---

## Background

The builder has 6 phase leads (planning, architecture, coding, review, testing, audit) with full prompt definitions in `agents.py`. The SDK subagent pipeline is partially wired:

- `build_agent_definitions()` at `agents.py:3971` builds phase lead `AgentDefinition` objects — but only when `config.agent_teams.enabled` is True
- `_build_options()` at `cli.py:298` passes agents to `ClaudeAgentOptions(agents=agent_defs)` at line 366
- `Task` is already in `_BASE_TOOLS` at `mcp_servers.py:108`
- `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` exists at `agents.py:1492` but references `TeamCreate`/`SendMessage` (Claude Code experimental feature) instead of the `Task` tool

**The 5 issues to fix:**
1. `build_agent_definitions()` gates on `agent_teams.enabled` — should gate on `phase_leads.enabled`
2. `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` uses `TeamCreate`/`SendMessage` — should use `Task` tool
3. `phase_leads.enabled` defaults to `False` — should be enabled at standard+ depth
4. Quick depth force-disables `agent_teams.enabled` — separate concern, phase_leads should have own gating
5. The subprocess-based `route_message()`/`spawn_phase_leads()` approach is dead code for now

---

### Task 1: Decouple phase_leads.enabled from agent_teams.enabled in build_agent_definitions()

**Files:**
- Modify: `src/agent_team_v15/agents.py:4116`

**Step 1: Change the gate condition**

At line 4116, change:
```python
    # Phase lead agents — conditionally added when agent_teams is enabled
    if config.agent_teams.enabled:
```

To:
```python
    # Phase lead agents — added as SDK subagents when phase_leads is enabled.
    # These are invoked by the orchestrator via the Task tool (native SDK
    # subagent mechanism), independent of the AgentTeamsBackend subprocess
    # approach which is controlled by agent_teams.enabled.
    if config.phase_leads.enabled:
```

**Step 2: Fix the model fallback to not depend on agent_teams config**

At lines 4117-4118, change:
```python
        _team_tools = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
        _lead_model = config.agent_teams.teammate_model or config.agents.get("planner", AgentConfig()).model
```

To:
```python
        _team_tools = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
        _lead_model = (
            config.agent_teams.phase_lead_model
            or config.agents.get("planner", AgentConfig()).model
        )
```

**Step 3: Run test to verify agent definitions include phase leads**

Run: `python -m pytest tests/ -k "agent_def" -v --no-header 2>&1 | head -30`
Expected: Existing tests still pass (phase leads only built when enabled, which is still False by default)

**Step 4: Commit**

```bash
git add src/agent_team_v15/agents.py
git commit -m "refactor: decouple phase lead agents from agent_teams.enabled gate"
```

---

### Task 2: Rewrite TEAM_ORCHESTRATOR_SYSTEM_PROMPT to use Task tool

**Files:**
- Modify: `src/agent_team_v15/agents.py:1492-1615`

**Step 1: Rewrite the PHASE LEAD COORDINATION section**

Replace the section from "PHASE LEAD COORDINATION" (line 1519) through the end of the "Startup Sequence" and "Structured Message Types" blocks. The key changes:

- Replace all `TeamCreate` references with `Task` tool
- Replace all `SendMessage` references with subagent return values
- Replace "spawn" language with "delegate to" language
- Remove the message-passing protocol (SDK handles communication natively — the orchestrator delegates work via Task, receives results back, then delegates the next phase)

The rewritten section (replace lines 1519-1577):

```python
============================================================
PHASE LEAD COORDINATION
============================================================

You manage 6 specialized phase leads registered as SDK subagents.
Delegate work to them using the **Task tool** (same as Agent tool).

1. planning-lead: Explores codebase, creates REQUIREMENTS.md, validates spec
2. architecture-lead: Designs solution, creates CONTRACTS.json, defines file ownership
3. coding-lead: Manages code-writers in waves, coordinates file generation
4. review-lead: Adversarial review, convergence tracking, requirement marking
5. testing-lead: Writes and runs tests, security audit
6. audit-lead: Runs quality audits, tracks fix convergence

### Delegation Sequence

Execute phases SEQUENTIALLY — each phase depends on the previous:

**Phase 1: Planning**
Delegate to planning-lead:
- Give it the user task, PRD content, codebase map, and depth level
- It creates .agent-team/REQUIREMENTS.md
- Wait for completion, verify REQUIREMENTS.md exists

**Phase 2: Architecture**
Delegate to architecture-lead:
- Give it REQUIREMENTS.md content + codebase map
- It creates .agent-team/CONTRACTS.json + architecture decisions
- Wait for completion, verify artifacts exist

**Phase 3: Coding**
Delegate to coding-lead:
- Give it REQUIREMENTS.md + CONTRACTS.json + architecture
- It generates all source files in waves
- Wait for completion, verify key files exist

**Phase 4: Review**
Delegate to review-lead:
- Give it REQUIREMENTS.md + generated code paths
- It reviews every requirement, marks [x] or [ ] with evidence
- Returns convergence ratio (target: 100%)

**Phase 5: Fix Cycle (if needed)**
If review convergence < 100%:
- Read review-lead's findings
- Delegate specific fixes to coding-lead
- Re-delegate to review-lead for re-review
- Repeat until 100% or max cycles

**Phase 6: Testing**
Delegate to testing-lead:
- Give it the code paths + REQUIREMENTS.md
- It writes and runs tests
- Returns test results

**Phase 7: Audit (if enabled)**
Delegate to audit-lead:
- Give it the full project path
- It runs quality scans and reports findings

### Important Rules
- You are the HUB — all coordination flows through you
- Read phase lead results and pass relevant context to the next phase
- Do NOT write code yourself — delegate everything
- After each phase, verify artifacts were created before proceeding
- Track convergence: review-lead's output determines if fix cycles are needed
```

**Step 2: Update the Completion Criteria section**

Replace lines 1563-1570:
```python
### Completion Criteria
The build is COMPLETE when:
1. review-lead achieves 100% convergence (all requirements [x])
2. testing-lead confirms tests pass
3. If audit-lead is active: audit findings are resolved
4. You have verified all critical artifacts exist
```

**Step 3: Verify the prompt compiles**

Run: `python -c "from agent_team_v15.agents import TEAM_ORCHESTRATOR_SYSTEM_PROMPT; print('OK:', len(TEAM_ORCHESTRATOR_SYSTEM_PROMPT), 'chars')"`
Expected: `OK: NNNN chars`

**Step 4: Commit**

```bash
git add src/agent_team_v15/agents.py
git commit -m "feat: rewrite team orchestrator prompt to use Task tool delegation"
```

---

### Task 3: Update _TEAM_COMMUNICATION_PROTOCOL in phase lead prompts

**Files:**
- Modify: `src/agent_team_v15/agents.py:3319-3392`

**Step 1: Rewrite the communication protocol**

The current `_TEAM_COMMUNICATION_PROTOCOL` references `SendMessage` for inter-lead communication. Since phase leads are now SDK subagents invoked by the orchestrator via Task, they don't message each other directly — they receive instructions from the orchestrator and return results.

Replace `_TEAM_COMMUNICATION_PROTOCOL` (lines 3319-3392) with:

```python
_TEAM_COMMUNICATION_PROTOCOL = r"""
============================================================
SDK SUBAGENT PROTOCOL
============================================================

You are an SDK subagent invoked by the orchestrator via the Task tool.

### How This Works
- The orchestrator delegates a specific phase of work to you
- You receive context (REQUIREMENTS.md, architecture, code paths, etc.) in your prompt
- You complete your phase: create artifacts, write files, return results
- Your text output is returned to the orchestrator as your result
- The orchestrator reads your result and passes relevant context to the next phase lead

### Your Responsibilities
- Complete your assigned phase thoroughly
- Create all expected artifacts (files in .agent-team/ or project code)
- Report your results clearly in your final text output
- Include structured data the orchestrator needs (convergence ratios, file lists, findings)

### What You Should NOT Do
- Do NOT try to message other phase leads (you can't — the orchestrator coordinates)
- Do NOT assume you know what other leads have done unless told in your prompt
- Do NOT skip your phase or delegate it back to the orchestrator

### Output Format
End your work with a structured summary:
```
## Phase Result
- Status: COMPLETE | PARTIAL | BLOCKED
- Artifacts created: [list of files]
- Key findings: [any issues or decisions]
- Next phase input: [what the next lead needs to know]
```
"""
```

**Step 2: Update the phase lead prompt injection to remove `{next_phase}` / `{prev_phase}` placeholders**

At lines 4120-4174, the `.replace("{next_phase}", ...)` and `.replace("{prev_phase}", ...)` calls are no longer needed since the protocol no longer references next/prev phases. Simplify:

Change each block like:
```python
        agents["planning-lead"] = {
            ...
            "prompt": PLANNING_LEAD_PROMPT + "\n\n" + _comm_protocol.replace(
                "{next_phase}", "architecture-lead"
            ).replace("{prev_phase}", "orchestrator"),
            ...
        }
```

To:
```python
        agents["planning-lead"] = {
            ...
            "prompt": PLANNING_LEAD_PROMPT + "\n\n" + _comm_protocol,
            ...
        }
```

Do this for all 6 phase leads (planning, architecture, coding, review, testing, audit).

**Step 3: Verify compilation**

Run: `python -c "from agent_team_v15.agents import build_agent_definitions; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add src/agent_team_v15/agents.py
git commit -m "refactor: simplify phase lead communication protocol for SDK subagent model"
```

---

### Task 4: Enable phase_leads at standard+ depth via depth gating

**Files:**
- Modify: `src/agent_team_v15/config.py`

**Step 1: Add phase_leads gating in `apply_depth_quality_gating()`**

In the `quick` depth block (around line 873), add:
```python
        _gate("phase_leads.enabled", False, config.phase_leads, "enabled")
```

In the `standard` depth block (around line 916), add:
```python
        # Standard enables phase lead SDK subagents (lightweight, no subprocess overhead)
        _gate("phase_leads.enabled", True, config.phase_leads, "enabled")
```

In the `thorough` depth block, add:
```python
        _gate("phase_leads.enabled", True, config.phase_leads, "enabled")
```

In the `exhaustive` depth block, add:
```python
        _gate("phase_leads.enabled", True, config.phase_leads, "enabled")
```

**Step 2: Ensure agent_teams.enabled gating is unchanged**

The existing line 873 (`_gate("agent_teams.enabled", False, ...)`) stays — `agent_teams.enabled` controls the subprocess-based `AgentTeamsBackend`, which is a separate concern from SDK subagent phase leads.

**Step 3: Verify depth gating**

Run: `python -c "
from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating
c = AgentTeamConfig()
apply_depth_quality_gating('standard', c, {})
print('standard phase_leads.enabled:', c.phase_leads.enabled)
apply_depth_quality_gating('quick', c, {})
print('quick phase_leads.enabled:', c.phase_leads.enabled)
"`
Expected:
```
standard phase_leads.enabled: True
quick phase_leads.enabled: False
```

**Step 4: Commit**

```bash
git add src/agent_team_v15/config.py
git commit -m "feat: enable phase lead SDK subagents at standard+ depth"
```

---

### Task 5: Update get_orchestrator_system_prompt() selection logic

**Files:**
- Modify: `src/agent_team_v15/agents.py:5300-5306`

**Step 1: Verify the selection logic**

The current code at lines 5304-5306:
```python
    if config.phase_leads.enabled:
        return TEAM_ORCHESTRATOR_SYSTEM_PROMPT
    return ORCHESTRATOR_SYSTEM_PROMPT
```

This is already correct — it uses `config.phase_leads.enabled`, which we're now enabling at standard+ depth. No change needed here.

**Step 2: Verify end-to-end prompt selection**

Run: `python -c "
from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating
from agent_team_v15.agents import get_orchestrator_system_prompt
c = AgentTeamConfig()
apply_depth_quality_gating('standard', c, {})
prompt = get_orchestrator_system_prompt(c)
print('Uses team prompt:', 'PHASE LEAD COORDINATION' in prompt)
print('Uses Task tool:', 'Task tool' in prompt or 'Task' in prompt)
print('No TeamCreate:', 'TeamCreate' not in prompt)
"`
Expected:
```
Uses team prompt: True
Uses Task tool: True
No TeamCreate: True
```

---

### Task 6: Add per-lead tool customization from PhaseLeadConfig

**Files:**
- Modify: `src/agent_team_v15/agents.py:4117-4174`

**Step 1: Use PhaseLeadConfig tools instead of hardcoded _team_tools**

Currently all leads use the same hardcoded tool list. The `PhaseLeadConfig` already defines per-lead tools (e.g., audit-lead has `["Read", "Grep", "Glob", "Bash"]` — no Write/Edit). Wire this up:

Replace lines 4117-4174 with:
```python
        _lead_model = (
            config.agent_teams.phase_lead_model
            or config.agents.get("planner", AgentConfig()).model
        )
        _comm_protocol = _TEAM_COMMUNICATION_PROTOCOL

        _lead_configs = {
            "planning-lead": (config.phase_leads.planning_lead, PLANNING_LEAD_PROMPT),
            "architecture-lead": (config.phase_leads.architecture_lead, ARCHITECTURE_LEAD_PROMPT),
            "coding-lead": (config.phase_leads.coding_lead, CODING_LEAD_PROMPT),
            "review-lead": (config.phase_leads.review_lead, REVIEW_LEAD_PROMPT),
            "testing-lead": (config.phase_leads.testing_lead, TESTING_LEAD_PROMPT),
            "audit-lead": (config.phase_leads.audit_lead, AUDIT_LEAD_PROMPT),
        }

        _lead_descriptions = {
            "planning-lead": "Phase lead: manages planning, exploration, spec validation, and research",
            "architecture-lead": "Phase lead: manages architecture design, contracts, and wiring map",
            "coding-lead": "Phase lead: manages task assignment, code-writer waves, and convergence",
            "review-lead": "Phase lead: manages adversarial code review and convergence signaling",
            "testing-lead": "Phase lead: manages test writing, execution, and test requirement marking",
            "audit-lead": "Phase lead: ensures build quality via deterministic scanning and fix cycle coordination",
        }

        for lead_name, (lead_cfg, lead_prompt) in _lead_configs.items():
            if not lead_cfg.enabled:
                continue
            agents[lead_name] = {
                "description": _lead_descriptions[lead_name],
                "prompt": lead_prompt + "\n\n" + _comm_protocol,
                "tools": lead_cfg.tools or ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
                "model": lead_cfg.model or _lead_model,
            }
```

**Step 2: Verify build**

Run: `python -c "
from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating
from agent_team_v15.agents import build_agent_definitions
c = AgentTeamConfig()
apply_depth_quality_gating('standard', c, {})
defs = build_agent_definitions(c, {})
leads = [k for k in defs if k.endswith('-lead')]
print('Phase leads:', leads)
print('Audit tools:', defs.get('audit-lead', {}).get('tools'))
"`
Expected:
```
Phase leads: ['planning-lead', 'architecture-lead', 'coding-lead', 'review-lead', 'testing-lead', 'audit-lead']
Audit tools: ['Read', 'Grep', 'Glob', 'Bash']
```

**Step 3: Commit**

```bash
git add src/agent_team_v15/agents.py
git commit -m "feat: wire per-lead tool customization from PhaseLeadConfig"
```

---

### Task 7: Remove TeamCreate/SendMessage injection in cli.py

**Files:**
- Modify: `src/agent_team_v15/cli.py:694-707` and `cli.py:1538-1553`

**Step 1: Remove team mode prompt injection**

At lines 694-707, the code injects "[TEAM MODE ENABLED] You MUST use TeamCreate..." into the prompt when agent_teams is active. This is for the subprocess backend, not SDK subagents. The SDK subagent approach doesn't need this injection — the agents are already in ClaudeAgentOptions.

Replace lines 694-707:
```python
    # Inject team-mode instructions when Agent Teams backend is active
    if _use_team_mode:
        prompt += (
            "\n\n[TEAM MODE ENABLED] You MUST use TeamCreate and team members "
            "for parallel task execution. Do NOT use isolated sub-agent fleets. "
            f"Team name prefix: {config.agent_teams.team_name_prefix}. "
            f"Phase lead max turns: {config.agent_teams.phase_lead_max_turns}."
        )
        # Inject audit-lead activation context
        if config.phase_leads.audit_lead.enabled:
            prompt += (
                "\n\n[AUDIT-LEAD ACTIVE] After milestone completion, message audit-lead "
                "to run quality audit. Do NOT call _run_audit_loop or audit_agent directly."
            )
```

With:
```python
    # Inject team-mode instructions when Agent Teams subprocess backend is active
    if _use_team_mode:
        prompt += (
            "\n\n[AGENT TEAMS BACKEND ACTIVE] TeamCreate and SendMessage are "
            "available for subprocess-based team coordination. "
            f"Team name prefix: {config.agent_teams.team_name_prefix}. "
            f"Phase lead max turns: {config.agent_teams.phase_lead_max_turns}."
        )
    # When phase leads are registered as SDK subagents, remind orchestrator
    elif config.phase_leads.enabled:
        prompt += (
            "\n\n[PHASE LEADS ACTIVE] You have 6 phase lead subagents available "
            "via the Task tool. Delegate each build phase to the appropriate lead. "
            "Do NOT write code yourself — use coding-lead. "
            "Do NOT review code yourself — use review-lead."
        )
```

**Step 2: Apply same fix to milestone mode**

At lines 1538-1553, apply the same pattern (replace TeamCreate injection with phase lead reminder for SDK subagent mode).

**Step 3: Commit**

```bash
git add src/agent_team_v15/cli.py
git commit -m "refactor: separate SDK subagent prompt injection from Agent Teams backend"
```

---

### Task 8: Run existing tests to verify nothing is broken

**Files:**
- Test: `tests/test_agent_teams_backend.py`
- Test: `tests/test_agents.py` (if exists)
- Test: `tests/test_config.py` (if exists)

**Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v --no-header -x 2>&1 | tail -40`
Expected: All tests pass. The agent_teams_backend tests should still pass since we didn't change that module.

**Step 2: Run a focused smoke test**

Run: `python -c "
from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating
from agent_team_v15.agents import build_agent_definitions, get_orchestrator_system_prompt

# Test 1: Quick depth = no phase leads
c1 = AgentTeamConfig()
apply_depth_quality_gating('quick', c1, {})
d1 = build_agent_definitions(c1, {})
leads1 = [k for k in d1 if k.endswith('-lead')]
p1 = get_orchestrator_system_prompt(c1)
assert leads1 == [], f'Quick should have no leads, got {leads1}'
assert 'TeamCreate' not in p1, 'Quick should use monolithic prompt'
print('PASS: quick depth — no phase leads')

# Test 2: Standard depth = phase leads as SDK subagents
c2 = AgentTeamConfig()
apply_depth_quality_gating('standard', c2, {})
d2 = build_agent_definitions(c2, {})
leads2 = sorted([k for k in d2 if k.endswith('-lead')])
p2 = get_orchestrator_system_prompt(c2)
assert len(leads2) == 6, f'Standard should have 6 leads, got {leads2}'
assert 'Task tool' in p2 or 'Task' in p2, 'Standard should reference Task tool'
assert 'TeamCreate' not in p2, 'Standard should NOT reference TeamCreate'
print('PASS: standard depth — 6 phase leads as SDK subagents')

# Test 3: Phase lead tools are customized
assert d2['audit-lead']['tools'] == ['Read', 'Grep', 'Glob', 'Bash'], f'Audit tools wrong: {d2[\"audit-lead\"][\"tools\"]}'
assert 'Write' in d2['coding-lead']['tools'], 'Coding lead should have Write'
print('PASS: per-lead tool customization')

print('ALL SMOKE TESTS PASSED')
"`
Expected: `ALL SMOKE TESTS PASSED`

**Step 3: Commit (if any test fixes needed)**

---

### Task 9: Update agent-team.yml test config to enable phase leads

**Files:**
- Modify: `/c/Users/Omar Khaled/AppData/Local/Temp/mini-test-build/agent-team.yml`

**Step 1: Add phase_leads config for testing at standard depth**

This is the test config — update it to use standard depth (so phase leads activate) and enable validators:

```yaml
# Minimal config for quick test run
orchestrator:
  model: sonnet
  max_turns: 100

depth:
  default: standard

convergence:
  max_cycles: 3

schema_validation:
  enabled: true
  block_on_critical: true

quality_validation:
  enabled: true
  block_on_critical: true

integration_gate:
  enabled: true
  verification_mode: block
  route_pattern_enforcement: true

post_orchestration_scans:
  enum_registry_scan: true
  response_shape_scan: true
  soft_delete_scan: true
  auth_flow_scan: true
  infrastructure_scan: true
  schema_validation_scan: true
```

Note: `phase_leads.enabled` is automatically set to True by the standard depth gate — no need to add it explicitly.

**Step 2: Commit**

```bash
git add -A
git commit -m "test: update mini build config to standard depth for phase lead testing"
```

---

## Verification

After all tasks are complete, run the mini build again:

```bash
bash scripts/run_mini_build.sh
```

Expected behavior:
1. Orchestrator uses `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` (references Task tool, not TeamCreate)
2. 6 phase lead `AgentDefinition` objects are registered in `ClaudeAgentOptions.agents`
3. Orchestrator delegates to phase leads via Task tool calls
4. Phase leads execute their work and return results
5. Orchestrator coordinates phases sequentially
6. All validators fire (standard depth enables them)
7. `STATE.json` should show meaningful convergence data

Watch for:
- `Task` tool calls in the build output (indicates phase lead delegation)
- Phase lead names in the output (planning-lead, coding-lead, etc.)
- No `TeamCreate` or `SendMessage` references (those are the old approach)
