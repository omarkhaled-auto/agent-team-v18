"""Tests for PRD fidelity improvements (from PRD_FIDELITY_REPORT.md).

Four improvements:
1. Framework-specific type hints for CHAR(n), BOOLEAN, SMALLINT, etc.
2. Aggregate validation mandate for financial entities with limits
3. Strengthened audit table mandate for financial/accounting PRDs
4. State machine endpoint completeness scan (SM-DEAD-STATE)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent_team_v15.prd_parser import (
    ParsedPRD,
    format_domain_model,
    parse_prd,
)
from agent_team_v15.agents import (
    build_tiered_mandate,
    build_milestone_execution_prompt,
    _is_accounting_prd,
)
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.milestone_manager import MilestoneContext


# ===================================================================
# Improvement 1: Framework-specific type hints
# ===================================================================


class TestFrameworkTypeHints:
    """format_domain_model() should append framework-specific guidance
    when entities contain types that have known framework idiom mismatches."""

    def _make_parsed(self, fields: list[dict]) -> ParsedPRD:
        return ParsedPRD(
            project_name="Test",
            entities=[{"name": "Account", "fields": fields, "description": ""}],
        )

    def test_char_type_produces_sqlalchemy_hint(self):
        """CHAR(3) field should produce 'use CHAR not String' hint for Python/SQLAlchemy."""
        parsed = self._make_parsed([
            {"name": "currency_code", "type": "CHAR(3)"},
        ])
        result = format_domain_model(parsed)
        assert "CHAR" in result
        assert "String" in result or "sqlalchemy" in result.lower()

    def test_no_hint_when_no_char_fields(self):
        """No framework hints section when no CHAR fields exist."""
        parsed = self._make_parsed([
            {"name": "name", "type": "VARCHAR(100)"},
            {"name": "amount", "type": "DECIMAL(18,4)"},
        ])
        result = format_domain_model(parsed)
        assert "Framework Type Hints" not in result

    def test_smallint_produces_hint(self):
        """SMALLINT should produce a framework hint."""
        parsed = self._make_parsed([
            {"name": "period_number", "type": "SMALLINT"},
        ])
        result = format_domain_model(parsed)
        assert "SmallInteger" in result or "smallint" in result.lower()

    def test_boolean_produces_hint(self):
        """BOOLEAN field should produce framework hint."""
        parsed = self._make_parsed([
            {"name": "is_active", "type": "BOOLEAN"},
        ])
        result = format_domain_model(parsed)
        assert "Boolean" in result

    def test_multiple_char_fields_single_hint(self):
        """Multiple CHAR fields should produce one hint section, not duplicates."""
        parsed = self._make_parsed([
            {"name": "currency_code", "type": "CHAR(3)"},
            {"name": "country_code", "type": "CHAR(2)"},
        ])
        result = format_domain_model(parsed)
        # Should mention CHAR but only one hints section
        assert result.count("Framework Type Hints") == 1

    def test_hint_flows_into_milestone_prompt(self):
        """Framework hints from domain model must appear in the milestone prompt."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[{
                "name": "Transaction",
                "fields": [{"name": "currency_code", "type": "CHAR(3)"}],
                "description": "",
            }],
        )
        domain_text = format_domain_model(parsed)
        config = AgentTeamConfig()
        ms = MilestoneContext(
            milestone_id="ms-1", title="Finance Service",
            requirements_path=".agent-team/milestones/ms-1/REQUIREMENTS.md",
            predecessor_summaries=[],
        )
        prompt = build_milestone_execution_prompt(
            task="Build Finance Service. Python FastAPI.",
            depth="thorough", config=config,
            milestone_context=ms,
            domain_model_text=domain_text,
        )
        assert "CHAR" in prompt


# ===================================================================
# Improvement 2: Aggregate validation mandate
# ===================================================================


class TestAggregateValidationMandate:
    """build_tiered_mandate() should include cumulative/aggregate validation
    guidance when accounting rules are present."""

    def test_mandate_mentions_cumulative(self):
        """Tier 1 should mention cumulative/aggregate validation."""
        mandate = build_tiered_mandate(
            business_rules=[{
                "id": "BR-001", "service": "order", "entity": "Refund",
                "rule_type": "validation",
                "description": "Refund amount must not exceed order total",
            }],
            is_accounting=True,
        )
        assert "cumulative" in mandate.lower() or "aggregate" in mandate.lower()

    def test_mandate_mentions_sum_pattern(self):
        """Mandate should provide the sum pattern example."""
        mandate = build_tiered_mandate(is_accounting=True)
        mandate_lower = mandate.lower()
        assert ("total_refunded" in mandate_lower
                or "already" in mandate_lower
                or "sum of" in mandate_lower
                or "cumulative" in mandate_lower)

    def test_mandate_present_without_explicit_rules(self):
        """Aggregate mandate should appear even without explicit business rules
        when is_accounting=True (falls back to accounting mandate)."""
        mandate = build_tiered_mandate(is_accounting=True)
        assert "cumulative" in mandate.lower() or "aggregate" in mandate.lower()


# ===================================================================
# Improvement 3: Strengthened audit table mandate
# ===================================================================


class TestAuditTableMandate:
    """The accounting mandate should explicitly require a dedicated audit_log
    table, not just event publishing."""

    def test_mandate_requires_audit_table(self):
        """Mandate should mention dedicated audit table/audit_log."""
        mandate = build_tiered_mandate(is_accounting=True)
        assert "audit" in mandate.lower()
        # Must specify table, not just "audit trail"
        assert ("audit_log" in mandate.lower()
                or "audit table" in mandate.lower()
                or "audit_entries" in mandate.lower())

    def test_mandate_rejects_event_only_audit(self):
        """Mandate should explicitly say event publishing alone is not sufficient."""
        mandate = build_tiered_mandate(is_accounting=True)
        mandate_lower = mandate.lower()
        assert ("event" in mandate_lower and "not sufficient" in mandate_lower) or \
               ("event" in mandate_lower and "insufficient" in mandate_lower) or \
               ("event publishing alone" in mandate_lower)

    def test_mandate_specifies_audit_fields(self):
        """Mandate should specify the required audit fields."""
        mandate = build_tiered_mandate(is_accounting=True)
        mandate_lower = mandate.lower()
        assert "entity_type" in mandate_lower or "entity_id" in mandate_lower
        assert "old_value" in mandate_lower or "new_value" in mandate_lower

    def test_audit_mandate_in_tier1_not_tier3(self):
        """Audit table should be in Tier 1 (BLOCKING), not Tier 3."""
        mandate = build_tiered_mandate(is_accounting=True)
        tier1_start = mandate.find("TIER 1")
        tier2_start = mandate.find("TIER 2")
        tier3_start = mandate.find("TIER 3")
        # Find "audit_log" or "audit table" position
        audit_pos = mandate.lower().find("audit_log")
        if audit_pos == -1:
            audit_pos = mandate.lower().find("audit table")
        assert audit_pos != -1, "audit_log or audit table not found in mandate"
        assert tier1_start < audit_pos < tier3_start, \
            f"Audit mandate at pos {audit_pos} should be between Tier 1 ({tier1_start}) and Tier 3 ({tier3_start})"


# ===================================================================
# Improvement 4: State machine endpoint completeness scan
# ===================================================================


class TestStateMachineEndpointScan:
    """Scan that cross-references state machine states against API routes.
    States with inbound transitions but no triggering endpoint should be
    flagged as SM-DEAD-STATE."""

    def test_import_exists(self):
        """The scan function should be importable."""
        from agent_team_v15.quality_checks import run_sm_endpoint_scan
        assert callable(run_sm_endpoint_scan)

    def test_detects_dead_state(self, tmp_path):
        """State with inbound transition but no endpoint → SM-DEAD-STATE."""
        from agent_team_v15.quality_checks import run_sm_endpoint_scan

        # Create a service file with routes that cover some but not all states
        service_file = tmp_path / "src" / "orders" / "routes.py"
        service_file.parent.mkdir(parents=True)
        service_file.write_text(
            'from fastapi import APIRouter\n'
            'router = APIRouter()\n'
            '@router.patch("/{id}/cancel")\n'
            'async def cancel_order(id: str): pass\n'
            # No approve endpoint, no ship endpoint
        )

        state_machines = [{
            "entity": "Order",
            "states": ["pending", "approved", "shipped", "cancelled"],
            "transitions": [
                {"from_state": "pending", "to_state": "approved", "trigger": "approve"},
                {"from_state": "approved", "to_state": "shipped", "trigger": "ship"},
                {"from_state": "pending", "to_state": "cancelled", "trigger": "cancel"},
            ],
        }]

        violations = run_sm_endpoint_scan(tmp_path, state_machines)
        dead_states = [v for v in violations if v.check == "SM-DEAD-STATE"]

        # "approved" and "shipped" have no triggering endpoints
        dead_state_names = {v.message.split("'")[1] for v in dead_states if "'" in v.message}
        assert "approved" in dead_state_names, f"Expected 'approved' in dead states, got {dead_state_names}"
        assert "shipped" in dead_state_names, f"Expected 'shipped' in dead states, got {dead_state_names}"

    def test_no_violations_when_all_covered(self, tmp_path):
        """No violations when every inbound-transition state has a matching endpoint."""
        from agent_team_v15.quality_checks import run_sm_endpoint_scan

        service_file = tmp_path / "src" / "orders" / "routes.py"
        service_file.parent.mkdir(parents=True)
        service_file.write_text(
            '@router.patch("/{id}/approve")\n'
            'async def approve(id): pass\n'
            '@router.patch("/{id}/ship")\n'
            'async def ship(id): pass\n'
            '@router.patch("/{id}/cancel")\n'
            'async def cancel(id): pass\n'
        )

        state_machines = [{
            "entity": "Order",
            "states": ["pending", "approved", "shipped", "cancelled"],
            "transitions": [
                {"from_state": "pending", "to_state": "approved", "trigger": "approve"},
                {"from_state": "approved", "to_state": "shipped", "trigger": "ship"},
                {"from_state": "pending", "to_state": "cancelled", "trigger": "cancel"},
            ],
        }]

        violations = run_sm_endpoint_scan(tmp_path, state_machines)
        dead_states = [v for v in violations if v.check == "SM-DEAD-STATE"]
        assert len(dead_states) == 0

    def test_ignores_initial_state(self, tmp_path):
        """The initial state (first in states list, no inbound transitions) should not be flagged."""
        from agent_team_v15.quality_checks import run_sm_endpoint_scan

        service_file = tmp_path / "src" / "routes.py"
        service_file.parent.mkdir(parents=True)
        service_file.write_text(
            '@router.patch("/{id}/submit")\n'
            'async def submit(id): pass\n'
        )

        state_machines = [{
            "entity": "Order",
            "states": ["draft", "submitted"],
            "transitions": [
                {"from_state": "draft", "to_state": "submitted", "trigger": "submit"},
            ],
        }]

        violations = run_sm_endpoint_scan(tmp_path, state_machines)
        dead_states = [v for v in violations if v.check == "SM-DEAD-STATE"]
        assert len(dead_states) == 0

    def test_empty_state_machines_returns_empty(self, tmp_path):
        """No state machines → no violations."""
        from agent_team_v15.quality_checks import run_sm_endpoint_scan

        violations = run_sm_endpoint_scan(tmp_path, [])
        assert violations == []

    def test_typescript_routes_detected(self, tmp_path):
        """NestJS-style TypeScript routes should be detected."""
        from agent_team_v15.quality_checks import run_sm_endpoint_scan

        ctrl_file = tmp_path / "src" / "orders" / "orders.controller.ts"
        ctrl_file.parent.mkdir(parents=True)
        ctrl_file.write_text(
            'import { Controller, Patch } from "@nestjs/common";\n'
            '@Controller("orders")\n'
            'export class OrdersController {\n'
            '  @Patch(":id/approve")\n'
            '  async approve(@Param("id") id: string) {}\n'
            '  @Patch(":id/cancel")\n'
            '  async cancel(@Param("id") id: string) {}\n'
            '}\n'
        )

        state_machines = [{
            "entity": "Order",
            "states": ["pending", "approved", "shipped", "cancelled"],
            "transitions": [
                {"from_state": "pending", "to_state": "approved", "trigger": "approve"},
                {"from_state": "approved", "to_state": "shipped", "trigger": "ship"},
                {"from_state": "pending", "to_state": "cancelled", "trigger": "cancel"},
            ],
        }]

        violations = run_sm_endpoint_scan(tmp_path, state_machines)
        dead_states = [v for v in violations if v.check == "SM-DEAD-STATE"]
        # "shipped" has no endpoint, "approved" and "cancelled" do
        dead_names = {v.message.split("'")[1] for v in dead_states if "'" in v.message}
        assert "shipped" in dead_names
        assert "approved" not in dead_names
        assert "cancelled" not in dead_names
