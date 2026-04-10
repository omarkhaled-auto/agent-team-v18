"""Tests for pseudocode stage integration (Feature #1)."""
from __future__ import annotations

import json

from agent_team_v15.agents import build_agent_definitions, PSEUDOCODE_WRITER_PROMPT, ORCHESTRATOR_SYSTEM_PROMPT
from agent_team_v15.config import (
    AgentTeamConfig,
    DEPTH_AGENT_COUNTS,
    PseudocodeConfig,
    get_agent_counts,
)
from agent_team_v15.orchestrator_reasoning import (
    _TEMPLATES,
    _TRIGGER_DESCRIPTIONS,
    _WHEN_CONDITIONS,
    format_pseudocode_review,
)
from agent_team_v15.state import RunState, save_state, load_state


class TestPseudocodeAgentDefinition:
    def test_pseudocode_agent_created_when_enabled(self):
        config = AgentTeamConfig()
        config.pseudocode = PseudocodeConfig(enabled=True)
        agents = build_agent_definitions(config, mcp_servers={})
        assert "pseudocode-writer" in agents

    def test_pseudocode_agent_not_created_when_disabled(self):
        config = AgentTeamConfig()
        config.pseudocode = PseudocodeConfig(enabled=False)
        agents = build_agent_definitions(config, mcp_servers={})
        assert "pseudocode-writer" not in agents

    def test_pseudocode_agent_has_correct_tools(self):
        config = AgentTeamConfig()
        config.pseudocode = PseudocodeConfig(enabled=True)
        agents = build_agent_definitions(config, mcp_servers={})
        assert agents["pseudocode-writer"]["tools"] == ["Read", "Glob", "Grep", "Write"]

    def test_pseudocode_prompt_not_empty(self):
        assert len(PSEUDOCODE_WRITER_PROMPT) > 100


class TestOrchestratorPromptPseudocode:
    def test_section_2_5_present_in_prompt(self):
        """The orchestrator system prompt must contain Section 2.5."""
        assert "SECTION 2.5: PSEUDOCODE VALIDATION PHASE" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_gate_6_present_in_prompt(self):
        """Gate 6 must be present in the orchestrator system prompt."""
        assert "GATE 6" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_step_4_7_present_in_prompt(self):
        """Workflow step 4.7 must reference pseudocode phase."""
        assert "4.7" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "PSEUDOCODE PHASE" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_pseudocode_fleet_docs_present(self):
        """Fleet documentation for pseudocode-writer must be present."""
        assert "### Pseudocode Fleet" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_depth_table_includes_pseudocode(self):
        """Depth table must include Pseudocode column."""
        assert "Pseudocode" in ORCHESTRATOR_SYSTEM_PROMPT


class TestPseudocodeStateTracking:
    def test_default_pseudocode_fields(self):
        state = RunState()
        assert state.pseudocode_validated is False
        assert state.pseudocode_artifacts == {}

    def test_pseudocode_state_roundtrip(self, tmp_path):
        state = RunState(
            pseudocode_validated=True,
            pseudocode_artifacts={"TASK-001": ".agent-team/pseudocode/PSEUDO_TASK-001.md"},
        )
        save_state(state, directory=str(tmp_path))
        loaded = load_state(directory=str(tmp_path))
        assert loaded is not None
        assert loaded.pseudocode_validated is True
        assert loaded.pseudocode_artifacts == {"TASK-001": ".agent-team/pseudocode/PSEUDO_TASK-001.md"}


class TestPseudocodeBackwardCompatibility:
    def test_default_config_has_pseudocode_disabled(self):
        config = AgentTeamConfig()
        assert config.pseudocode.enabled is False

    def test_existing_agents_unchanged_when_pseudocode_enabled(self):
        config = AgentTeamConfig()
        agents_before = build_agent_definitions(config, mcp_servers={})

        config.pseudocode = PseudocodeConfig(enabled=True)
        agents_after = build_agent_definitions(config, mcp_servers={})

        # All original agents must still be present
        for name in agents_before:
            assert name in agents_after, f"Agent {name} missing after enabling pseudocode"
            assert agents_before[name]["prompt"] == agents_after[name]["prompt"]

    def test_old_state_file_loads_without_pseudocode_fields(self, tmp_path):
        """Simulate loading a state file from before pseudocode was added."""
        state_file = tmp_path / "STATE.json"
        old_data = {"run_id": "test123", "task": "test", "schema_version": 2}
        state_file.write_text(json.dumps(old_data))
        loaded = load_state(directory=str(tmp_path))
        assert loaded is not None
        assert loaded.pseudocode_validated is False
        assert loaded.pseudocode_artifacts == {}


class TestPseudocodeDepthCounts:
    def test_all_depths_have_pseudocode_key(self):
        for depth, counts in DEPTH_AGENT_COUNTS.items():
            assert "pseudocode" in counts, f"Depth {depth} missing pseudocode counts"

    def test_quick_pseudocode_range(self):
        counts = get_agent_counts("quick")
        assert counts["pseudocode"] == (0, 1)

    def test_standard_pseudocode_range(self):
        counts = get_agent_counts("standard")
        assert counts["pseudocode"] == (1, 2)

    def test_thorough_pseudocode_range(self):
        counts = get_agent_counts("thorough")
        assert counts["pseudocode"] == (2, 3)

    def test_exhaustive_pseudocode_range(self):
        counts = get_agent_counts("exhaustive")
        assert counts["pseudocode"] == (3, 4)


class TestPseudocodeSTPoint:
    def test_point_5_in_templates(self):
        assert 5 in _TEMPLATES
        assert _TEMPLATES[5][0] == "Pseudocode Review"

    def test_point_5_in_triggers(self):
        assert 5 in _TRIGGER_DESCRIPTIONS

    def test_point_5_in_when_conditions(self):
        assert 5 in _WHEN_CONDITIONS

    def test_format_pseudocode_review(self):
        from agent_team_v15.config import OrchestratorSTConfig
        config = OrchestratorSTConfig()
        result = format_pseudocode_review({}, config)
        assert "PSEUDOCODE DECISION" in result


class TestPseudocodeConfig:
    def test_defaults(self):
        cfg = PseudocodeConfig()
        assert cfg.enabled is False
        assert cfg.require_architect_approval is True
        assert cfg.output_dir == "pseudocode"
        assert cfg.complexity_analysis is True
        assert cfg.edge_case_minimum == 3

    def test_pseudocode_writer_in_default_agents(self):
        config = AgentTeamConfig()
        assert "pseudocode_writer" in config.agents
