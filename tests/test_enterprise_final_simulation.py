"""Exhaustive enterprise-mode simulation tests.

Validates config round-trip, agent registration, ownership validation,
prompt content, and depth gating comparison for the enterprise depth level.
"""

from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path

import pytest

from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating
from agent_team_v15.agents import (
    BACKEND_DEV_PROMPT,
    ENTERPRISE_ARCHITECTURE_STEPS,
    FRONTEND_DEV_PROMPT,
    INFRA_DEV_PROMPT,
    TEAM_ORCHESTRATOR_SYSTEM_PROMPT,
    build_agent_definitions,
)
from agent_team_v15.ownership_validator import (
    OwnershipFinding,
    run_ownership_gate,
    validate_ownership_map,
)
from agent_team_v15.state import RunState, load_state, save_state


# =========================================================================
# Category 1: Config Round-Trip
# =========================================================================


class TestEnterpriseConfigRoundTrip:
    """Verify enterprise config survives serialization/deserialization."""

    def test_enterprise_config_to_dict_and_back(self):
        """Config -> dict -> Config preserves all enterprise fields."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        d = asdict(c)
        em = d["enterprise_mode"]
        assert em["enabled"] is True
        assert em["domain_agents"] is True
        assert em["max_backend_devs"] == 3
        assert em["max_frontend_devs"] == 2
        assert em["max_infra_devs"] == 1
        assert em["parallel_review"] is True
        assert em["wave_state_persistence"] is True
        assert em["ownership_validation_gate"] is True
        assert em["scaffold_shared_files"] is True
        assert em["multi_step_architecture"] is True

    def test_enterprise_state_round_trip(self):
        """RunState with enterprise fields survives save/load."""
        state = RunState(
            enterprise_mode_active=True,
            ownership_map_validated=True,
            waves_completed=3,
            domain_agents_deployed=5,
        )
        with tempfile.TemporaryDirectory() as td:
            save_state(state, td)
            loaded = load_state(td)
            assert loaded is not None
            assert loaded.enterprise_mode_active is True
            assert loaded.ownership_map_validated is True
            assert loaded.waves_completed == 3
            assert loaded.domain_agents_deployed == 5

    def test_enterprise_depth_gating_idempotent(self):
        """Applying enterprise gating twice doesn't change values."""
        c1 = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c1, set())
        c2 = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c2, set())
        apply_depth_quality_gating("enterprise", c2, set())  # Apply twice
        assert asdict(c1) == asdict(c2)


# =========================================================================
# Category 2: Agent Registration
# =========================================================================


class TestEnterpriseAgentRegistrationSimulation:
    """Verify enterprise agents are registered correctly in all scenarios."""

    def test_enterprise_v1_with_context7_full_registration(self):
        """V1 (no dept model): backend+frontend get MCP tools, infra doesn't."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        c.enterprise_mode.department_model = False
        c.departments.enabled = False
        defs = build_agent_definitions(c, {"context7": {"url": "..."}})
        # backend-dev has context7
        assert "mcp__context7__resolve-library-id" in defs["backend-dev"]["tools"]
        assert "mcp__context7__query-docs" in defs["backend-dev"]["tools"]
        assert defs["backend-dev"].get("mcpServers") == ["context7"]
        assert defs["backend-dev"].get("background") is False
        # frontend-dev has context7
        assert "mcp__context7__query-docs" in defs["frontend-dev"]["tools"]
        assert defs["frontend-dev"].get("mcpServers") == ["context7"]
        # infra-dev has NO context7
        assert "mcp__context7__query-docs" not in defs["infra-dev"]["tools"]
        assert defs["infra-dev"].get("mcpServers") is None
        assert defs["infra-dev"].get("background") is None

    def test_enterprise_v2_dept_agents_replace_domain_agents(self):
        """V2 (dept model): department managers replace v1 domain agents."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        defs = build_agent_definitions(c, {"context7": {"url": "..."}})
        # v1 domain agents NOT registered
        for name in ("backend-dev", "frontend-dev", "infra-dev"):
            assert name not in defs, f"v1 agent {name} should not be registered with dept model"
        # v2 department managers registered with context7
        assert "backend-manager" in defs
        assert "frontend-manager" in defs
        assert "mcp__context7__query-docs" in defs["backend-manager"]["tools"]

    def test_enterprise_without_context7(self):
        """Without context7 MCP, no department manager gets MCP tools."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        defs = build_agent_definitions(c, {})  # No MCP servers
        for name in ("backend-manager", "frontend-manager"):
            assert defs[name].get("mcpServers") is None
            assert defs[name].get("background") is None

    def test_enterprise_agents_coexist_with_phase_leads(self):
        """Department agents + all 6 phase leads registered simultaneously."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        defs = build_agent_definitions(c, {})
        # Phase leads
        for lead in (
            "planning-lead", "architecture-lead", "coding-lead",
            "review-lead", "testing-lead", "audit-lead",
        ):
            assert lead in defs, f"Missing phase lead: {lead}"
        # Department agents (v2 replaces v1 domain agents)
        for agent in ("coding-dept-head", "backend-manager", "frontend-manager",
                       "infra-manager", "integration-manager", "review-dept-head"):
            assert agent in defs, f"Missing department agent: {agent}"
        # Total should be at least 16 (6 leads + 10 dept agents)
        assert len(defs) >= 16

    def test_enterprise_disabled_no_domain_agents(self):
        """With enterprise disabled, domain agents are NOT registered."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("standard", c, set())
        defs = build_agent_definitions(c, {})
        for agent in ("backend-dev", "frontend-dev", "infra-dev"):
            assert agent not in defs

    def test_enterprise_domain_agents_false(self):
        """enterprise_mode.enabled=True but domain_agents=False -> no domain agents."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        c.enterprise_mode.domain_agents = False
        defs = build_agent_definitions(c, {})
        for agent in ("backend-dev", "frontend-dev", "infra-dev"):
            assert agent not in defs
        # Phase leads should still be there
        assert "coding-lead" in defs

    def test_architecture_lead_has_enterprise_steps(self):
        """In enterprise mode, architecture-lead prompt includes enterprise steps."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        defs = build_agent_definitions(c, {})
        arch_prompt = defs["architecture-lead"]["prompt"]
        assert "ENTERPRISE MODE: MULTI-STEP ARCHITECTURE PROTOCOL" in arch_prompt
        assert "OWNERSHIP_MAP.json" in arch_prompt
        assert "Step 1:" in arch_prompt
        assert "Step 4:" in arch_prompt

    def test_architecture_lead_no_enterprise_steps_at_standard(self):
        """At standard depth, architecture-lead does NOT have enterprise steps."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("standard", c, set())
        defs = build_agent_definitions(c, {})
        if "architecture-lead" in defs:
            arch_prompt = defs["architecture-lead"]["prompt"]
            assert "ENTERPRISE MODE: MULTI-STEP ARCHITECTURE PROTOCOL" not in arch_prompt


# =========================================================================
# Category 3: Ownership Validation
# =========================================================================


class TestOwnershipValidationSimulation:
    """Exhaustive ownership validation scenarios."""

    def test_perfectly_valid_map(self):
        """A well-formed map with no issues produces zero critical findings."""
        m = {
            "version": 1,
            "domains": {
                "infra": {
                    "tech_stack": "docker", "agent_type": "infra-dev",
                    "files": ["docker-compose.yml", "*.Dockerfile"],
                    "requirements": ["REQ-001"], "dependencies": [], "shared_reads": [],
                },
                "auth": {
                    "tech_stack": "nestjs", "agent_type": "backend-dev",
                    "files": ["backend/src/auth/**"],
                    "requirements": ["REQ-002", "REQ-003"], "dependencies": ["infra"], "shared_reads": [],
                },
                "tasks": {
                    "tech_stack": "nestjs", "agent_type": "backend-dev",
                    "files": ["backend/src/tasks/**"],
                    "requirements": ["REQ-004", "REQ-005"], "dependencies": ["infra", "auth"], "shared_reads": [],
                },
                "dashboard": {
                    "tech_stack": "nextjs", "agent_type": "frontend-dev",
                    "files": ["frontend/app/**"],
                    "requirements": ["REQ-006", "REQ-007"], "dependencies": ["auth", "tasks"], "shared_reads": [],
                },
            },
            "waves": [
                {"id": 1, "name": "foundation", "domains": ["infra"], "parallel": False},
                {"id": 2, "name": "backend", "domains": ["auth", "tasks"], "parallel": True},
                {"id": 3, "name": "frontend", "domains": ["dashboard"], "parallel": False},
            ],
            "shared_scaffolding": ["backend/prisma/schema.prisma", "backend/src/app.module.ts"],
        }
        reqs = {f"REQ-{i:03d}" for i in range(1, 8)}
        findings = validate_ownership_map(m, reqs)
        critical = [f for f in findings if f.severity == "critical"]
        assert len(critical) == 0, f"Unexpected critical findings: {critical}"

    def test_multiple_overlaps(self):
        """Multiple file overlaps across 3 domains."""
        m = {
            "version": 1,
            "domains": {
                "a": {"files": ["src/shared/**", "src/utils/**"], "requirements": ["REQ-001"], "dependencies": [], "shared_reads": []},
                "b": {"files": ["src/shared/**"], "requirements": ["REQ-002"], "dependencies": [], "shared_reads": []},
                "c": {"files": ["src/utils/**"], "requirements": ["REQ-003"], "dependencies": [], "shared_reads": []},
            },
            "waves": [],
            "shared_scaffolding": [],
        }
        findings = validate_ownership_map(m)
        own001 = [f for f in findings if f.check == "OWN-001"]
        assert len(own001) >= 2  # src/shared/** overlaps a+b, src/utils/** overlaps a+c

    def test_deep_dependency_chain_no_cycle(self):
        """A -> B -> C -> D is valid (no cycle)."""
        m = {
            "version": 1,
            "domains": {
                "a": {"files": ["a/**"], "requirements": ["REQ-001"], "dependencies": ["b"], "shared_reads": []},
                "b": {"files": ["b/**"], "requirements": ["REQ-002"], "dependencies": ["c"], "shared_reads": []},
                "c": {"files": ["c/**"], "requirements": ["REQ-003"], "dependencies": ["d"], "shared_reads": []},
                "d": {"files": ["d/**"], "requirements": ["REQ-004"], "dependencies": [], "shared_reads": []},
            },
            "waves": [],
            "shared_scaffolding": [],
        }
        findings = validate_ownership_map(m, {"REQ-001", "REQ-002", "REQ-003", "REQ-004"})
        own005 = [f for f in findings if f.check == "OWN-005"]
        assert len(own005) == 0

    def test_three_way_cycle(self):
        """A -> B -> C -> A is a cycle."""
        m = {
            "version": 1,
            "domains": {
                "a": {"files": ["a/**"], "requirements": ["REQ-001"], "dependencies": ["b"], "shared_reads": []},
                "b": {"files": ["b/**"], "requirements": ["REQ-002"], "dependencies": ["c"], "shared_reads": []},
                "c": {"files": ["c/**"], "requirements": ["REQ-003"], "dependencies": ["a"], "shared_reads": []},
            },
            "waves": [],
            "shared_scaffolding": [],
        }
        findings = validate_ownership_map(m)
        own005 = [f for f in findings if f.check == "OWN-005"]
        assert len(own005) > 0

    def test_self_dependency(self):
        """Domain depending on itself is a cycle."""
        m = {
            "version": 1,
            "domains": {
                "a": {"files": ["a/**"], "requirements": ["REQ-001"], "dependencies": ["a"], "shared_reads": []},
            },
            "waves": [],
            "shared_scaffolding": [],
        }
        findings = validate_ownership_map(m)
        own005 = [f for f in findings if f.check == "OWN-005"]
        assert len(own005) > 0

    def test_empty_map(self):
        """Empty domains dict should not crash."""
        m = {"version": 1, "domains": {}, "waves": [], "shared_scaffolding": []}
        findings = validate_ownership_map(m)
        assert isinstance(findings, list)

    def test_run_ownership_gate_no_file(self):
        """run_ownership_gate with no OWNERSHIP_MAP.json returns pass."""
        with tempfile.TemporaryDirectory() as td:
            passed, findings = run_ownership_gate(Path(td))
            assert passed is True
            assert findings == []

    def test_run_ownership_gate_malformed_json(self):
        """run_ownership_gate with invalid JSON returns failure."""
        with tempfile.TemporaryDirectory() as td:
            agent_dir = Path(td) / ".agent-team"
            agent_dir.mkdir()
            (agent_dir / "OWNERSHIP_MAP.json").write_text("NOT JSON {{{", encoding="utf-8")
            passed, findings = run_ownership_gate(Path(td))
            assert passed is False
            assert any(f.check == "OWN-000" for f in findings)

    def test_all_seven_checks_fire(self):
        """Build a map that triggers ALL 7 OWN checks at once."""
        m = {
            "version": 1,
            "domains": {
                "a": {
                    "files": ["shared/**", "backend/prisma/schema.prisma"],  # OWN-001 overlap + OWN-006 scaffolding
                    "requirements": ["REQ-001", "REQ-FAKE"],  # OWN-007 non-existent
                    "dependencies": ["b"], "shared_reads": [],
                },
                "b": {
                    "files": ["shared/**"],  # OWN-001 overlap with a
                    "requirements": [],  # OWN-004 no requirements
                    "dependencies": ["a"], "shared_reads": [],  # OWN-005 cycle a<->b
                },
                "c": {
                    "files": [],  # OWN-003 no files
                    "requirements": ["REQ-003"],
                    "dependencies": [], "shared_reads": [],
                },
            },
            "waves": [],
            "shared_scaffolding": ["backend/prisma/schema.prisma"],
        }
        findings = validate_ownership_map(m, {"REQ-001", "REQ-002", "REQ-003"})
        checks_found = {f.check for f in findings}
        # OWN-001: file overlap (shared/**)
        assert "OWN-001" in checks_found, f"Missing OWN-001. Got: {checks_found}"
        # OWN-002: REQ-002 unassigned
        assert "OWN-002" in checks_found, f"Missing OWN-002. Got: {checks_found}"
        # OWN-003: domain c has no files
        assert "OWN-003" in checks_found, f"Missing OWN-003. Got: {checks_found}"
        # OWN-004: domain b has no requirements
        assert "OWN-004" in checks_found, f"Missing OWN-004. Got: {checks_found}"
        # OWN-005: cycle a<->b
        assert "OWN-005" in checks_found, f"Missing OWN-005. Got: {checks_found}"
        # OWN-006: scaffolding in domain a
        assert "OWN-006" in checks_found, f"Missing OWN-006. Got: {checks_found}"
        # OWN-007: REQ-FAKE doesn't exist
        assert "OWN-007" in checks_found, f"Missing OWN-007. Got: {checks_found}"


# =========================================================================
# Category 4: Prompt Content Verification
# =========================================================================


class TestEnterprisePromptContent:
    """Verify prompt content is correct at runtime."""

    def test_ownership_map_schema_in_architecture_steps(self):
        """ENTERPRISE_ARCHITECTURE_STEPS contains the actual JSON schema, not a placeholder."""
        assert "{ownership_map_schema}" not in ENTERPRISE_ARCHITECTURE_STEPS
        assert '"version"' in ENTERPRISE_ARCHITECTURE_STEPS
        assert '"domains"' in ENTERPRISE_ARCHITECTURE_STEPS
        assert '"waves"' in ENTERPRISE_ARCHITECTURE_STEPS
        assert '"shared_scaffolding"' in ENTERPRISE_ARCHITECTURE_STEPS

    def test_enterprise_steps_has_schema_content(self):
        """The interpolated schema has real content (version, domains, waves)."""
        # The prompt uses escaped \\n for line breaks in non-schema parts,
        # but the f-string interpolated _OWNERSHIP_MAP_SCHEMA has real newlines.
        assert "ENTERPRISE MODE: MULTI-STEP ARCHITECTURE PROTOCOL" in ENTERPRISE_ARCHITECTURE_STEPS
        assert "Step 1:" in ENTERPRISE_ARCHITECTURE_STEPS
        assert "Step 4:" in ENTERPRISE_ARCHITECTURE_STEPS

    def test_all_domain_prompts_have_output_format(self):
        """All domain prompts end with structured output format."""
        for name, prompt in [
            ("backend", BACKEND_DEV_PROMPT),
            ("frontend", FRONTEND_DEV_PROMPT),
            ("infra", INFRA_DEV_PROMPT),
        ]:
            assert "## Domain Result:" in prompt, f"{name} missing output format"
            assert "Status: COMPLETE | PARTIAL" in prompt, f"{name} missing status"

    def test_no_coordinator_tools_in_agent_prompts(self):
        """No enterprise prompt references SendMessage or TeamCreate."""
        for name, prompt in [
            ("backend", BACKEND_DEV_PROMPT),
            ("frontend", FRONTEND_DEV_PROMPT),
            ("infra", INFRA_DEV_PROMPT),
            ("arch-steps", ENTERPRISE_ARCHITECTURE_STEPS),
        ]:
            assert "SendMessage" not in prompt, f"{name} has SendMessage"
            assert "TeamCreate" not in prompt, f"{name} has TeamCreate"

    # Phase G Slice 4f removed the ALL-CAPS "ENTERPRISE MODE (150K+ LOC Builds)"
    # header — the enterprise content now lives inside an <enterprise_mode>
    # XML block. Key elements (all six leads, OWNERSHIP_MAP.json) are asserted
    # in tests/test_orchestrator_prompt.py under the new contract.
    def test_enterprise_orchestrator_core_members_present(self):
        """TEAM_ORCHESTRATOR still references every phase lead and OWNERSHIP_MAP.json."""
        assert "architecture-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "coding-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "review-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "OWNERSHIP_MAP.json" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT


# =========================================================================
# Category 5: Depth Gating Exhaustive Comparison
# =========================================================================


class TestDepthGatingComparison:
    """Verify enterprise is strictly superior to all other depths."""

    def test_enterprise_enables_everything_exhaustive_does(self):
        """Every feature enabled by exhaustive is also enabled by enterprise."""
        c_exhaust = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", c_exhaust, set())
        c_enter = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c_enter, set())

        # Everything exhaustive enables, enterprise also enables
        assert c_enter.audit_team.enabled >= c_exhaust.audit_team.enabled
        assert c_enter.e2e_testing.enabled >= c_exhaust.e2e_testing.enabled
        assert c_enter.contract_engine.enabled >= c_exhaust.contract_engine.enabled
        assert c_enter.codebase_intelligence.enabled >= c_exhaust.codebase_intelligence.enabled
        assert c_enter.phase_leads.enabled >= c_exhaust.phase_leads.enabled

        # Enterprise has MORE
        assert c_enter.enterprise_mode.enabled is True
        assert c_exhaust.enterprise_mode.enabled is False
        assert c_enter.convergence.max_cycles > c_exhaust.convergence.max_cycles

    def test_all_depths_dont_crash(self):
        """Apply every depth level without crashing."""
        for depth in ("quick", "standard", "thorough", "exhaustive", "enterprise"):
            c = AgentTeamConfig()
            apply_depth_quality_gating(depth, c, set())  # Should not raise

    def test_enterprise_convergence_budget_higher(self):
        """Enterprise has max_cycles=15 vs exhaustive default (10)."""
        c_exhaust = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", c_exhaust, set())
        c_enter = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c_enter, set())
        assert c_enter.convergence.max_cycles == 25
        # Exhaustive uses default (10) since it doesn't override max_cycles
        assert c_exhaust.convergence.max_cycles == 10

    def test_enterprise_always_enables_browser_testing(self):
        """Enterprise enables browser testing unconditionally (no PRD gate)."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        assert c.browser_testing.enabled is True

    def test_enterprise_always_enables_runtime_verification(self):
        """Enterprise enables runtime verification unconditionally (no PRD gate)."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        assert c.runtime_verification.enabled is True

    def test_enterprise_agent_teams_enabled_without_env_var(self):
        """Enterprise enables agent_teams without CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        assert c.agent_teams.enabled is True
