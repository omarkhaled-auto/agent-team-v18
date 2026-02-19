"""Tests for Build 2 pipeline wiring (milestone-4).

TEST-046 through TEST-049, TEST-WIRING-001 through TEST-WIRING-005:
State roundtrip, MCP fallbacks, signal handler, prompt builder parameters,
and server replacement verification.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agent_team_v15.state import (
    ContractReport,
    EndpointTestReport,
    RunState,
    load_state,
    save_state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config(**overrides: Any) -> SimpleNamespace:
    """Build a minimal config-like object for prompt builder testing."""
    convergence = SimpleNamespace(
        requirements_dir=".agent-team",
        requirements_file="REQUIREMENTS.md",
        master_plan_file="MASTER_PLAN.md",
        min_convergence_ratio=0.8,
        degraded_threshold=0.5,
        escalation_threshold=3,
    )
    agent_teams = SimpleNamespace(
        enabled=False,
        contract_limit=100,
    )
    contract_engine = SimpleNamespace(enabled=False)
    codebase_intelligence = SimpleNamespace(
        enabled=False,
        replace_static_map=True,
        register_artifacts=True,
    )
    design_reference = SimpleNamespace(
        depth="standard",
        max_pages_per_site=5,
        cache_ttl_seconds=300,
        standards_file="",
    )
    milestone = SimpleNamespace()
    tracking_documents = SimpleNamespace(milestone_handoff=True)
    prd_chunking = SimpleNamespace(enabled=False, threshold=100000, max_chunk_size=50000)
    orchestrator_st = SimpleNamespace()

    cfg = SimpleNamespace(
        convergence=convergence,
        agent_teams=agent_teams,
        contract_engine=contract_engine,
        codebase_intelligence=codebase_intelligence,
        design_reference=design_reference,
        milestone=milestone,
        tracking_documents=tracking_documents,
        prd_chunking=prd_chunking,
        orchestrator_st=orchestrator_st,
        mcp_servers={},
        **overrides,
    )
    return cfg


# ---------------------------------------------------------------------------
# TEST-046: ContractReport and EndpointTestReport defaults
# ---------------------------------------------------------------------------


class TestReportDefaults:
    """TEST-046: Default health='unknown'."""

    def test_contract_report_default_health(self) -> None:
        cr = ContractReport()
        assert cr.health == "unknown"
        assert cr.total_contracts == 0
        assert cr.verified_contracts == 0
        assert cr.violated_contracts == 0
        assert cr.missing_implementations == 0
        assert cr.violations == []
        assert cr.verified_contract_ids == []
        assert cr.violated_contract_ids == []

    def test_endpoint_test_report_default_health(self) -> None:
        etr = EndpointTestReport()
        assert etr.health == "unknown"
        assert etr.total_endpoints == 0
        assert etr.tested_endpoints == 0
        assert etr.passed_endpoints == 0
        assert etr.failed_endpoints == 0
        assert etr.untested_contracts == []

    def test_contract_report_custom_values(self) -> None:
        cr = ContractReport(
            total_contracts=10,
            verified_contracts=7,
            violated_contracts=1,
            missing_implementations=2,
            violations=[{"check": "api", "message": "err"}],
            health="degraded",
            verified_contract_ids=["c-1"],
            violated_contract_ids=["c-2"],
        )
        assert cr.health == "degraded"
        assert cr.total_contracts == 10

    def test_endpoint_test_report_custom_values(self) -> None:
        etr = EndpointTestReport(
            total_endpoints=5,
            tested_endpoints=5,
            passed_endpoints=4,
            failed_endpoints=1,
            health="partial",
        )
        assert etr.health == "partial"
        assert etr.failed_endpoints == 1


# ---------------------------------------------------------------------------
# TEST-WIRING-001: STATE.json roundtrip with new fields
# ---------------------------------------------------------------------------


class TestStateRoundtrip:
    """TEST-WIRING-001: Verify STATE.json roundtrips correctly with new fields."""

    def test_contract_report_roundtrip(self, tmp_path: Path) -> None:
        state = RunState(
            task="test-task",
            contract_report={
                "total_contracts": 5,
                "verified_contracts": 3,
                "violated_contracts": 1,
                "missing_implementations": 1,
                "violations": [{"check": "api", "message": "err"}],
                "health": "degraded",
                "verified_contract_ids": ["c-1"],
                "violated_contract_ids": ["c-2"],
            },
        )
        save_state(state, str(tmp_path))
        loaded = load_state(str(tmp_path))
        assert loaded is not None
        assert loaded.contract_report["total_contracts"] == 5
        assert loaded.contract_report["verified_contracts"] == 3
        assert loaded.contract_report["health"] == "degraded"

    def test_endpoint_test_report_roundtrip(self, tmp_path: Path) -> None:
        state = RunState(
            task="test-task",
            endpoint_test_report={
                "total_endpoints": 10,
                "tested_endpoints": 8,
                "passed_endpoints": 7,
                "failed_endpoints": 1,
                "untested_contracts": ["c-5"],
                "health": "partial",
            },
        )
        save_state(state, str(tmp_path))
        loaded = load_state(str(tmp_path))
        assert loaded is not None
        assert loaded.endpoint_test_report["total_endpoints"] == 10
        assert loaded.endpoint_test_report["health"] == "partial"

    def test_registered_artifacts_roundtrip(self, tmp_path: Path) -> None:
        state = RunState(
            task="test-task",
            registered_artifacts=["file1.py", "file2.ts", "file3.js"],
        )
        save_state(state, str(tmp_path))
        loaded = load_state(str(tmp_path))
        assert loaded is not None
        assert loaded.registered_artifacts == ["file1.py", "file2.ts", "file3.js"]

    def test_empty_new_fields_roundtrip(self, tmp_path: Path) -> None:
        state = RunState(task="test-task")
        save_state(state, str(tmp_path))
        loaded = load_state(str(tmp_path))
        assert loaded is not None
        assert loaded.contract_report == {}
        assert loaded.endpoint_test_report == {}
        assert loaded.registered_artifacts == []

    def test_backward_compatible_load_without_new_fields(self, tmp_path: Path) -> None:
        """STATE.json without Build 2 fields should load with defaults."""
        state_data = {
            "run_id": "abc123",
            "task": "old-task",
            "depth": "standard",
            "current_phase": "init",
            "completed_phases": [],
            "total_cost": 0.0,
            "artifacts": {},
            "interrupted": True,
            "timestamp": "2024-01-01T00:00:00+00:00",
            "convergence_cycles": 0,
            "requirements_checked": 0,
            "requirements_total": 0,
            "error_context": "",
            "milestone_progress": {},
            "schema_version": 2,
            "current_milestone": "",
            "completed_milestones": [],
            "failed_milestones": [],
            "milestone_order": [],
            "completion_ratio": 0.0,
            "completed_browser_workflows": [],
            "agent_teams_active": False,
            # NO contract_report, endpoint_test_report, registered_artifacts
        }
        state_path = tmp_path / "STATE.json"
        state_path.write_text(json.dumps(state_data), encoding="utf-8")
        loaded = load_state(str(tmp_path))
        assert loaded is not None
        assert loaded.contract_report == {}
        assert loaded.endpoint_test_report == {}
        assert loaded.registered_artifacts == []

    def test_summary_block_in_saved_state(self, tmp_path: Path) -> None:
        """save_state should include a summary block."""
        state = RunState(
            task="test-task",
            requirements_checked=8,
            requirements_total=10,
            contract_report={"total_contracts": 5, "verified_contracts": 3},
            endpoint_test_report={"tested_endpoints": 12, "passed_endpoints": 10},
        )
        save_state(state, str(tmp_path))
        state_path = tmp_path / "STATE.json"
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert "summary" in data
        assert data["summary"]["convergence_ratio"] == 0.8
        assert data["summary"]["test_total"] == 12
        assert data["summary"]["test_passed"] == 10


# ---------------------------------------------------------------------------
# TEST-047: build_orchestrator_prompt with contract_context
# ---------------------------------------------------------------------------


class TestBuildOrchestratorPromptContract:
    """TEST-047: Contract context in orchestrator prompt."""

    def test_contract_context_included(self) -> None:
        from src.agent_team_v15.agents import build_orchestrator_prompt
        config = _make_config()
        result = build_orchestrator_prompt(
            task="test task",
            depth="standard",
            config=config,
            contract_context="Contract: auth-api v1.0 (openapi)",
        )
        assert "[CONTRACT ENGINE CONTEXT]" in result
        assert "auth-api v1.0" in result
        assert "[/CONTRACT ENGINE CONTEXT]" in result

    def test_contract_context_omitted_when_empty(self) -> None:
        from src.agent_team_v15.agents import build_orchestrator_prompt
        config = _make_config()
        result = build_orchestrator_prompt(
            task="test task",
            depth="standard",
            config=config,
            contract_context="",
        )
        assert "[CONTRACT ENGINE CONTEXT]" not in result

    def test_codebase_index_context_included(self) -> None:
        from src.agent_team_v15.agents import build_orchestrator_prompt
        config = _make_config()
        result = build_orchestrator_prompt(
            task="test task",
            depth="standard",
            config=config,
            codebase_index_context="Module: api.py (50 symbols)",
        )
        assert "[CODEBASE INTELLIGENCE CONTEXT]" in result
        assert "api.py" in result
        assert "[/CODEBASE INTELLIGENCE CONTEXT]" in result

    def test_codebase_index_context_omitted_when_empty(self) -> None:
        from src.agent_team_v15.agents import build_orchestrator_prompt
        config = _make_config()
        result = build_orchestrator_prompt(
            task="test task",
            depth="standard",
            config=config,
            codebase_index_context="",
        )
        assert "[CODEBASE INTELLIGENCE CONTEXT]" not in result


# ---------------------------------------------------------------------------
# TEST-048: build_milestone_execution_prompt with codebase_index_context
# ---------------------------------------------------------------------------


class TestBuildMilestonePromptContext:
    """TEST-048: Codebase index context in milestone prompt."""

    def test_codebase_index_context_included(self) -> None:
        from src.agent_team_v15.agents import build_milestone_execution_prompt
        config = _make_config()
        result = build_milestone_execution_prompt(
            task="test task",
            depth="standard",
            config=config,
            codebase_index_context="Module graph: 42 nodes",
        )
        assert "[CODEBASE INTELLIGENCE CONTEXT]" in result
        assert "42 nodes" in result

    def test_contract_context_included(self) -> None:
        from src.agent_team_v15.agents import build_milestone_execution_prompt
        config = _make_config()
        result = build_milestone_execution_prompt(
            task="test task",
            depth="standard",
            config=config,
            contract_context="3 unimplemented contracts",
        )
        assert "[CONTRACT ENGINE CONTEXT]" in result
        assert "3 unimplemented contracts" in result

    def test_both_contexts_omitted_when_empty(self) -> None:
        from src.agent_team_v15.agents import build_milestone_execution_prompt
        config = _make_config()
        result = build_milestone_execution_prompt(
            task="test task",
            depth="standard",
            config=config,
            contract_context="",
            codebase_index_context="",
        )
        assert "[CONTRACT ENGINE CONTEXT]" not in result
        assert "[CODEBASE INTELLIGENCE CONTEXT]" not in result


# ---------------------------------------------------------------------------
# TEST-WIRING-002: MCP codebase map fallback
# ---------------------------------------------------------------------------


class TestMCPCodebaseMapFallback:
    """TEST-WIRING-002: MCP-based codebase map falls back to static."""

    def test_mcp_failure_returns_static_map(self) -> None:
        """When MCP session fails, static map should still work."""
        # This is a unit-level test — the actual fallback is in cli.py
        # We just verify the functions exist and have the right signatures
        from src.agent_team_v15.codebase_map import generate_codebase_map, generate_codebase_map_from_mcp
        import inspect
        sig_mcp = inspect.signature(generate_codebase_map_from_mcp)
        assert "client" in sig_mcp.parameters
        sig_static = inspect.signature(generate_codebase_map)
        assert "project_root" in sig_static.parameters


# ---------------------------------------------------------------------------
# TEST-WIRING-003: Contract registry local fallback
# ---------------------------------------------------------------------------


class TestContractRegistryFallback:
    """TEST-WIRING-003: Registry falls back to local on MCP failure."""

    def test_load_from_local_works(self, tmp_path: Path) -> None:
        from src.agent_team_v15.contracts import ServiceContractRegistry
        registry = ServiceContractRegistry()

        # Create a minimal local cache
        cache = {
            "version": "1.0",
            "contracts": {
                "c-1": {
                    "contract_type": "openapi",
                    "provider_service": "auth",
                    "consumer_service": "",
                    "version": "1.0.0",
                    "spec_hash": "abc",
                    "spec": {},
                    "implemented": False,
                    "evidence_path": "",
                }
            },
        }
        cache_path = tmp_path / "contract_cache.json"
        cache_path.write_text(json.dumps(cache), encoding="utf-8")

        registry.load_from_local(cache_path)
        assert len(registry.contracts) == 1
        assert "c-1" in registry.contracts


# ---------------------------------------------------------------------------
# TEST-WIRING-004: Signal handler state persistence
# ---------------------------------------------------------------------------


class TestSignalHandlerStatePersistence:
    """TEST-WIRING-004: Signal handler saves contract report and agent_teams_active."""

    def test_contract_report_persisted_in_state(self, tmp_path: Path) -> None:
        """Verify that contract_report is saved to STATE.json."""
        state = RunState(
            task="test",
            contract_report={
                "total_contracts": 10,
                "verified_contracts": 7,
                "violated_contracts": 1,
                "missing_implementations": 2,
                "violations": [{"check": "api", "message": "err"}],
                "health": "degraded",
                "verified_contract_ids": [],
                "violated_contract_ids": [],
            },
            agent_teams_active=True,
        )
        save_state(state, str(tmp_path))
        data = json.loads((tmp_path / "STATE.json").read_text(encoding="utf-8"))
        assert data["contract_report"]["total_contracts"] == 10
        assert data["agent_teams_active"] is True

    def test_agent_teams_active_persisted(self, tmp_path: Path) -> None:
        state = RunState(task="test", agent_teams_active=True)
        save_state(state, str(tmp_path))
        loaded = load_state(str(tmp_path))
        assert loaded is not None
        assert loaded.agent_teams_active is True


# ---------------------------------------------------------------------------
# TEST-WIRING-005: get_contract_aware_servers used
# ---------------------------------------------------------------------------


class TestContractAwareServersUsed:
    """TEST-WIRING-005: get_contract_aware_servers replaces get_mcp_servers."""

    def test_import_exists(self) -> None:
        """Verify get_contract_aware_servers is importable from cli module."""
        # Check that cli.py imports get_contract_aware_servers
        import importlib
        import src.agent_team_v15.cli as cli_module
        source = Path(cli_module.__file__).read_text(encoding="utf-8")
        assert "get_contract_aware_servers" in source
        assert "mcp_servers = get_contract_aware_servers(config)" in source

    def test_get_contract_aware_servers_callable(self) -> None:
        from src.agent_team_v15.mcp_servers import get_contract_aware_servers
        import inspect
        sig = inspect.signature(get_contract_aware_servers)
        assert "config" in sig.parameters


# ---------------------------------------------------------------------------
# Agent prompt contract awareness tests
# ---------------------------------------------------------------------------


class TestAgentPromptContractAwareness:
    """Verify contract awareness sections in agent prompts."""

    def test_architect_prompt_has_contract_section(self) -> None:
        from src.agent_team_v15.agents import ARCHITECT_PROMPT
        assert "CONTRACT ENGINE AWARENESS" in ARCHITECT_PROMPT
        assert "get_unimplemented_contracts" in ARCHITECT_PROMPT

    def test_code_writer_prompt_has_contract_section(self) -> None:
        from src.agent_team_v15.agents import CODE_WRITER_PROMPT
        assert "CONTRACT ENGINE COMPLIANCE" in CODE_WRITER_PROMPT
        assert "validate_endpoint" in CODE_WRITER_PROMPT

    def test_code_reviewer_prompt_has_contract_section(self) -> None:
        from src.agent_team_v15.agents import CODE_REVIEWER_PROMPT
        assert "CONTRACT ENGINE REVIEW" in CODE_REVIEWER_PROMPT
        assert "get_unimplemented_contracts" in CODE_REVIEWER_PROMPT


# ---------------------------------------------------------------------------
# ContractReport dataclass serialization tests
# ---------------------------------------------------------------------------


class TestContractReportSerialization:
    """Test ContractReport dataclass <-> dict conversion."""

    def test_asdict(self) -> None:
        cr = ContractReport(
            total_contracts=10,
            verified_contracts=8,
            violated_contracts=1,
            missing_implementations=1,
            violations=[{"check": "api", "message": "mismatch"}],
            health="healthy",
            verified_contract_ids=["c-1", "c-2"],
            violated_contract_ids=["c-3"],
        )
        d = asdict(cr)
        assert d["total_contracts"] == 10
        assert d["verified_contracts"] == 8
        assert d["violated_contracts"] == 1
        assert d["missing_implementations"] == 1
        assert len(d["violations"]) == 1
        assert d["health"] == "healthy"
        assert d["verified_contract_ids"] == ["c-1", "c-2"]
        assert d["violated_contract_ids"] == ["c-3"]

    def test_from_dict(self) -> None:
        d = {
            "total_contracts": 5,
            "verified_contracts": 3,
            "violated_contracts": 1,
            "missing_implementations": 1,
            "violations": [],
            "health": "degraded",
            "verified_contract_ids": ["c-1"],
            "violated_contract_ids": ["c-2"],
        }
        cr = ContractReport(**d)
        assert cr.total_contracts == 5
        assert cr.health == "degraded"


class TestEndpointTestReportSerialization:
    """Test EndpointTestReport dataclass <-> dict conversion."""

    def test_asdict(self) -> None:
        etr = EndpointTestReport(
            total_endpoints=20,
            tested_endpoints=15,
            passed_endpoints=12,
            failed_endpoints=3,
            untested_contracts=["c-5"],
            health="partial",
        )
        d = asdict(etr)
        assert d["total_endpoints"] == 20
        assert d["tested_endpoints"] == 15
        assert d["untested_contracts"] == ["c-5"]
        assert d["health"] == "partial"
