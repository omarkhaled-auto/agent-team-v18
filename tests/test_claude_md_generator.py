"""Tests for claude_md_generator module (milestone-4).

TEST-040 through TEST-049: CLAUDE.md generation for 5 agent roles,
MCP tools section, convergence mandates, contract truncation, file writing.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.agent_team_v15.claude_md_generator import (
    _BEGIN_MARKER,
    _END_MARKER,
    _generate_convergence_section,
    _generate_mcp_section,
    _generate_role_section,
    generate_claude_md,
    write_teammate_claude_md,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config(
    min_convergence_ratio: float = 0.9,
    contract_limit: int = 100,
) -> SimpleNamespace:
    """Build a minimal config-like object for testing."""
    convergence = SimpleNamespace(min_convergence_ratio=min_convergence_ratio)
    agent_teams = SimpleNamespace(contract_limit=contract_limit)
    return SimpleNamespace(convergence=convergence, agent_teams=agent_teams)


# ---------------------------------------------------------------------------
# TEST-040: generate_claude_md() for all 5 roles
# ---------------------------------------------------------------------------


class TestGenerateClaudeMdAllRoles:
    """TEST-040: Non-empty output for all 5 roles."""

    @pytest.mark.parametrize(
        "role",
        ["architect", "code-writer", "code-reviewer", "test-engineer", "wiring-verifier"],
    )
    def test_produces_non_empty_string(self, role: str) -> None:
        config = _make_config()
        result = generate_claude_md(role, config, mcp_servers={})
        assert isinstance(result, str)
        assert len(result) > 0
        assert "Agent Teams" in result

    def test_all_roles_contain_role_header(self) -> None:
        config = _make_config()
        for role in ["architect", "code-writer", "code-reviewer", "test-engineer", "wiring-verifier"]:
            result = generate_claude_md(role, config, mcp_servers={})
            assert "## Role:" in result


# ---------------------------------------------------------------------------
# TEST-041: MCP tools section included
# ---------------------------------------------------------------------------


class TestMCPToolsIncluded:
    """TEST-041: MCP section present when servers contain relevant keys."""

    def test_contract_engine_tools_listed(self) -> None:
        config = _make_config()
        servers = {"contract_engine": {"type": "stdio"}}
        result = generate_claude_md("architect", config, servers)
        assert "Contract Engine" in result
        assert "validate_endpoint" in result

    def test_codebase_intelligence_tools_listed(self) -> None:
        config = _make_config()
        servers = {"codebase_intelligence": {"type": "stdio"}}
        result = generate_claude_md("architect", config, servers)
        assert "Codebase Intelligence" in result
        assert "find_definition" in result

    def test_both_servers_listed(self) -> None:
        config = _make_config()
        servers = {
            "contract_engine": {"type": "stdio"},
            "codebase_intelligence": {"type": "stdio"},
        }
        result = generate_claude_md("architect", config, servers)
        assert "Contract Engine" in result
        assert "Codebase Intelligence" in result


# ---------------------------------------------------------------------------
# TEST-042: MCP tools section omitted when empty
# ---------------------------------------------------------------------------


class TestMCPToolsOmitted:
    """TEST-042: No MCP section when servers dict is empty."""

    def test_no_mcp_section_when_empty(self) -> None:
        config = _make_config()
        result = generate_claude_md("architect", config, mcp_servers={})
        assert "Available MCP Tools" not in result

    def test_no_mcp_section_when_irrelevant_servers(self) -> None:
        config = _make_config()
        servers = {"firecrawl": {"type": "stdio"}}
        result = generate_claude_md("architect", config, servers)
        assert "Available MCP Tools" not in result


# ---------------------------------------------------------------------------
# TEST-043: Convergence mandates with min_ratio
# ---------------------------------------------------------------------------


class TestConvergenceMandates:
    """TEST-043: Correct min_ratio in convergence section."""

    def test_default_ratio(self) -> None:
        config = _make_config(min_convergence_ratio=0.9)
        section = _generate_convergence_section(config)
        assert "90%" in section

    def test_custom_ratio(self) -> None:
        config = _make_config(min_convergence_ratio=0.95)
        section = _generate_convergence_section(config)
        assert "95%" in section

    def test_convergence_in_full_output(self) -> None:
        config = _make_config(min_convergence_ratio=0.9)
        result = generate_claude_md("architect", config, {})
        assert "90%" in result
        assert "Convergence Mandates" in result


# ---------------------------------------------------------------------------
# TEST-044: Contract truncation
# ---------------------------------------------------------------------------


class TestContractTruncation:
    """TEST-044: Contracts truncated at limit with overflow suffix."""

    def test_under_limit_no_truncation(self) -> None:
        config = _make_config(contract_limit=10)
        contracts = [
            {"contract_id": f"c-{i}", "provider_service": "svc", "contract_type": "openapi", "version": "1.0"}
            for i in range(5)
        ]
        result = generate_claude_md("architect", config, {}, contracts=contracts)
        assert "not shown" not in result
        assert "c-0" in result
        assert "c-4" in result

    def test_at_limit_no_truncation(self) -> None:
        config = _make_config(contract_limit=3)
        contracts = [
            {"contract_id": f"c-{i}", "provider_service": "svc", "contract_type": "openapi", "version": "1.0"}
            for i in range(3)
        ]
        result = generate_claude_md("architect", config, {}, contracts=contracts)
        assert "not shown" not in result

    def test_over_limit_truncated(self) -> None:
        config = _make_config(contract_limit=3)
        contracts = [
            {"contract_id": f"c-{i}", "provider_service": "svc", "contract_type": "openapi", "version": "1.0"}
            for i in range(10)
        ]
        result = generate_claude_md("architect", config, {}, contracts=contracts)
        assert "7 more" in result
        assert "get_contract(contract_id)" in result
        assert "c-0" in result
        assert "c-2" in result

    def test_empty_contracts(self) -> None:
        config = _make_config()
        result = generate_claude_md("architect", config, {}, contracts=[])
        assert "Active Contracts" not in result

    def test_none_contracts(self) -> None:
        config = _make_config()
        result = generate_claude_md("architect", config, {}, contracts=None)
        assert "Active Contracts" not in result


# ---------------------------------------------------------------------------
# TEST-045: write_teammate_claude_md()
# ---------------------------------------------------------------------------


class TestWriteTeammateCLAUDEMD:
    """TEST-045: File creation and marker preservation."""

    def test_creates_file(self, tmp_path: Path) -> None:
        config = _make_config()
        result = write_teammate_claude_md("architect", config, {}, tmp_path)
        assert result.is_file()
        assert result.name == "CLAUDE.md"
        assert result.parent.name == ".claude"

    def test_returns_correct_path(self, tmp_path: Path) -> None:
        config = _make_config()
        result = write_teammate_claude_md("architect", config, {}, tmp_path)
        expected = tmp_path / ".claude" / "CLAUDE.md"
        assert result == expected

    def test_content_has_markers(self, tmp_path: Path) -> None:
        config = _make_config()
        write_teammate_claude_md("architect", config, {}, tmp_path)
        content = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        assert _BEGIN_MARKER in content
        assert _END_MARKER in content

    def test_preserves_existing_content_outside_markers(self, tmp_path: Path) -> None:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        claude_md = claude_dir / "CLAUDE.md"
        claude_md.write_text("# Existing Content\nKeep this.\n", encoding="utf-8")

        config = _make_config()
        write_teammate_claude_md("architect", config, {}, tmp_path)
        content = claude_md.read_text(encoding="utf-8")
        assert "# Existing Content" in content
        assert "Keep this." in content
        assert _BEGIN_MARKER in content
        assert _END_MARKER in content

    def test_replaces_between_markers(self, tmp_path: Path) -> None:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        claude_md = claude_dir / "CLAUDE.md"
        claude_md.write_text(
            f"# Header\n{_BEGIN_MARKER}\nOLD CONTENT\n{_END_MARKER}\n# Footer\n",
            encoding="utf-8",
        )

        config = _make_config()
        write_teammate_claude_md("code-writer", config, {}, tmp_path)
        content = claude_md.read_text(encoding="utf-8")
        assert "OLD CONTENT" not in content
        assert "# Header" in content
        assert "# Footer" in content
        assert "Code Writer" in content

    def test_different_roles_produce_different_content(self, tmp_path: Path) -> None:
        config = _make_config()
        write_teammate_claude_md("architect", config, {}, tmp_path)
        architect_content = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")

        write_teammate_claude_md("code-reviewer", config, {}, tmp_path)
        reviewer_content = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")

        # Both should have markers, but different role sections
        assert "Architect" in architect_content
        assert "Code Reviewer" in reviewer_content


# ---------------------------------------------------------------------------
# TEST-049: _generate_role_section() generic fallback
# ---------------------------------------------------------------------------


class TestRoleSectionGenericFallback:
    """TEST-049: Unknown roles get generic fallback."""

    def test_unknown_role_returns_generic(self) -> None:
        section = _generate_role_section("unknown-role")
        assert "Role: Agent" in section
        assert "REQUIREMENTS.md" in section

    def test_empty_role_returns_generic(self) -> None:
        section = _generate_role_section("")
        assert "Role: Agent" in section

    def test_known_role_not_generic(self) -> None:
        section = _generate_role_section("architect")
        assert "Role: Architect" in section
        assert "Role: Agent" not in section


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------


class TestMCPSectionHelpers:
    """Extra tests for _generate_mcp_section edge cases."""

    def test_empty_dict(self) -> None:
        assert _generate_mcp_section({}) == ""

    def test_only_contract_engine(self) -> None:
        result = _generate_mcp_section({"contract_engine": {}})
        assert "Contract Engine" in result
        assert "Codebase Intelligence" not in result

    def test_only_codebase_intelligence(self) -> None:
        result = _generate_mcp_section({"codebase_intelligence": {}})
        assert "Codebase Intelligence" in result
        assert "Contract Engine" not in result


class TestContractImplementedStatus:
    """Test that implemented contracts show [x] marker."""

    def test_implemented_contract_marked(self) -> None:
        config = _make_config()
        contracts = [
            {"contract_id": "c-1", "provider_service": "svc", "contract_type": "openapi", "version": "1.0", "implemented": True},
        ]
        result = generate_claude_md("architect", config, {}, contracts=contracts)
        assert "[x]" in result

    def test_unimplemented_contract_unmarked(self) -> None:
        config = _make_config()
        contracts = [
            {"contract_id": "c-1", "provider_service": "svc", "contract_type": "openapi", "version": "1.0", "implemented": False},
        ]
        result = generate_claude_md("architect", config, {}, contracts=contracts)
        assert "[ ]" in result
