"""D-09: Tests for MCP pre-flight wiring.

Covers:
- run_mcp_preflight writes MCP_PREFLIGHT.json
- ensure_contract_e2e_fidelity_header writes header when engine unavailable
- Idempotency: calling twice does not duplicate headers
- contract_engine_is_deployable returns correct status
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.mcp_servers import (
    contract_engine_is_deployable,
    ensure_contract_e2e_fidelity_header,
    run_mcp_preflight,
    CONTRACT_E2E_STATIC_FIDELITY_HEADER,
)


class TestRunMcpPreflight:
    """run_mcp_preflight creates MCP_PREFLIGHT.json with structured status."""

    def test_creates_preflight_json(self, tmp_path: Path) -> None:
        cfg = AgentTeamConfig()
        result = run_mcp_preflight(str(tmp_path), cfg)
        json_path = tmp_path / ".agent-team" / "MCP_PREFLIGHT.json"
        assert json_path.is_file()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert "tools" in data
        assert "generated_at" in data

    def test_contains_validate_endpoint_tool(self, tmp_path: Path) -> None:
        cfg = AgentTeamConfig()
        result = run_mcp_preflight(str(tmp_path), cfg)
        assert "validate_endpoint" in result["tools"]
        assert "available" in result["tools"]["validate_endpoint"]

    def test_contains_codebase_intelligence_tool(self, tmp_path: Path) -> None:
        cfg = AgentTeamConfig()
        result = run_mcp_preflight(str(tmp_path), cfg)
        assert "codebase_intelligence" in result["tools"]

    def test_idempotent_overwrites(self, tmp_path: Path) -> None:
        cfg = AgentTeamConfig()
        run_mcp_preflight(str(tmp_path), cfg)
        run_mcp_preflight(str(tmp_path), cfg)
        json_path = tmp_path / ".agent-team" / "MCP_PREFLIGHT.json"
        data = json.loads(json_path.read_text(encoding="utf-8"))
        # Should be a valid single JSON object (not duplicated)
        assert isinstance(data, dict)
        assert "tools" in data


class TestEnsureContractE2EFidelityHeader:
    """ensure_contract_e2e_fidelity_header injects static-analysis header."""

    def test_injects_header_when_engine_unavailable(self, tmp_path: Path) -> None:
        target = tmp_path / "CONTRACT_E2E_RESULTS.md"
        target.write_text("# Results\nSome content", encoding="utf-8")
        modified = ensure_contract_e2e_fidelity_header(
            str(target), contract_engine_available=False
        )
        assert modified is True
        content = target.read_text(encoding="utf-8")
        assert "Verification fidelity:" in content

    def test_no_op_when_engine_available(self, tmp_path: Path) -> None:
        target = tmp_path / "CONTRACT_E2E_RESULTS.md"
        target.write_text("# Results\nSome content", encoding="utf-8")
        modified = ensure_contract_e2e_fidelity_header(
            str(target), contract_engine_available=True
        )
        assert modified is False
        content = target.read_text(encoding="utf-8")
        assert "Verification fidelity:" not in content

    def test_idempotent_no_duplicate(self, tmp_path: Path) -> None:
        target = tmp_path / "CONTRACT_E2E_RESULTS.md"
        target.write_text("# Results\nSome content", encoding="utf-8")
        ensure_contract_e2e_fidelity_header(
            str(target), contract_engine_available=False
        )
        modified_again = ensure_contract_e2e_fidelity_header(
            str(target), contract_engine_available=False
        )
        assert modified_again is False
        content = target.read_text(encoding="utf-8")
        assert content.count("Verification fidelity:") == 1

    def test_missing_file_returns_false(self, tmp_path: Path) -> None:
        target = tmp_path / "nonexistent.md"
        modified = ensure_contract_e2e_fidelity_header(
            str(target), contract_engine_available=False
        )
        assert modified is False


class TestContractEngineIsDeployable:
    """contract_engine_is_deployable checks configuration and environment."""

    def test_disabled_config_returns_false(self) -> None:
        cfg = AgentTeamConfig()
        ok, reason = contract_engine_is_deployable(cfg)
        assert ok is False
        assert reason != ""
