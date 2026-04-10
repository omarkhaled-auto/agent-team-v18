"""Tests for agent_team_v15.__init__."""

import re


def test_version_is_semver():
    from agent_team_v15 import __version__
    assert __version__ == "15.0.0"
    assert re.match(r"^\d+\.\d+\.\d+", __version__)


def test_main_is_callable():
    from agent_team_v15 import main
    assert callable(main)


def test_all_exports():
    import agent_team_v15
    assert hasattr(agent_team_v15, "__all__")
    expected = {
        "main", "__version__", "milestone_manager", "quality_checks", "wiring",
        # Build 2 modules
        "agent_teams_backend", "contract_client", "codebase_client",
        "hooks_manager", "claude_md_generator", "contract_scanner",
        "mcp_clients", "contracts",
        # Feature #3: Automated checkpoint gates
        "gate_enforcer",
        # Feature #3.5: Department leader skills
        "skills",
        # Feature #4: Self-Learning Hooks + Pattern Memory
        "hooks",
        "pattern_memory",
        # Feature #5: 3-Tier Model Routing
        "task_router",
        "complexity_analyzer",
    }
    assert set(agent_team_v15.__all__) == expected
