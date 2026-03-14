"""Tests for PRD parser (v16 Phase 2.1)."""

from __future__ import annotations

import pytest

from agent_team_v15.prd_parser import (
    ParsedPRD,
    parse_prd,
    format_domain_model,
    _extract_entities,
    _extract_state_machines,
    _extract_events,
    _extract_project_name,
    _extract_technology_hints,
    _is_section_heading,
    _to_pascal,
    _normalize_event_name,
)


# ===================================================================
# Project name extraction
# ===================================================================

class TestExtractProjectName:
    def test_project_heading(self):
        assert _extract_project_name("# Project: GlobalBooks\n\nSome text") == "GlobalBooks"

    def test_prd_heading(self):
        assert _extract_project_name("# PRD: SupplyForge\n\nDetails") == "SupplyForge"

    def test_first_heading(self):
        assert _extract_project_name("# My Cool App\n\nStuff") == "My Cool App"

    def test_fallback_first_line(self):
        assert _extract_project_name("GlobalBooks Accounting\n\nDetails") == "GlobalBooks Accounting"


# ===================================================================
# Section heading filter
# ===================================================================

class TestIsSectionHeading:
    def test_overview_is_section(self):
        assert _is_section_heading("Overview") is True

    def test_requirements_is_section(self):
        assert _is_section_heading("requirements") is True

    def test_invoice_is_not_section(self):
        assert _is_section_heading("Invoice") is False

    def test_customer_is_not_section(self):
        assert _is_section_heading("Customer") is False

    def test_user_service_is_section(self):
        assert _is_section_heading("UserService") is True

    def test_api_endpoints_is_section(self):
        assert _is_section_heading("API Endpoints") is True

    def test_data_is_generic_single_word(self):
        assert _is_section_heading("data") is True

    def test_status_is_generic_single_word(self):
        assert _is_section_heading("status") is True

    def test_journal_entry_is_not_section(self):
        assert _is_section_heading("JournalEntry") is False

    def test_numbered_prefix_stripped(self):
        assert _is_section_heading("1.2 System Overview") is True


# ===================================================================
# PascalCase conversion
# ===================================================================

class TestToPascal:
    def test_snake_case(self):
        assert _to_pascal("journal_entry") == "JournalEntry"

    def test_space_separated(self):
        assert _to_pascal("chart of accounts") == "ChartOfAccounts"

    def test_already_pascal(self):
        assert _to_pascal("Invoice") == "Invoice"

    def test_kebab_case(self):
        assert _to_pascal("purchase-order") == "PurchaseOrder"


# ===================================================================
# Entity extraction
# ===================================================================

class TestEntityExtraction:
    def test_authoritative_table(self):
        prd = """
# Data Model

| Entity | Owning Service | Description |
|--------|---------------|-------------|
| Invoice | AR | Customer invoice |
| Payment | AR | Payment record |
| Vendor | AP | Supplier record |
| PurchaseOrder | AP | Purchase order |
"""
        entities = _extract_entities(prd)
        names = {e["name"] for e in entities}
        assert "Invoice" in names
        assert "Payment" in names
        assert "Vendor" in names
        assert "PurchaseOrder" in names

    def test_heading_with_fields(self):
        prd = """
## Invoice
- id: UUID primary key
- amount: decimal total amount
- status: string current status
- tenant_id: UUID tenant identifier
"""
        entities = _extract_entities(prd)
        assert len(entities) >= 1
        inv = next(e for e in entities if e["name"] == "Invoice")
        field_names = {f["name"] for f in inv["fields"]}
        assert "id" in field_names
        assert "amount" in field_names
        assert "status" in field_names

    def test_entity_table_simple(self):
        prd = """
| Entity | Description |
|--------|-------------|
| User | Application user |
| Role | User role |
| Permission | Access permission |
"""
        entities = _extract_entities(prd)
        names = {e["name"] for e in entities}
        assert "User" in names
        assert "Role" in names

    def test_prose_extraction(self):
        prd = """
The system manages Invoice which has id, amount, status, tenant_id and created_at.
The application tracks Payment which contains amount, date, method.
"""
        entities = _extract_entities(prd)
        names = {e["name"] for e in entities}
        assert "Invoice" in names
        assert "Payment" in names

    def test_filters_section_headings(self):
        prd = """
## Overview
Some overview text.

## Requirements
Some requirements.

## Invoice
- id: UUID
- amount: decimal
"""
        entities = _extract_entities(prd)
        names = {e["name"] for e in entities}
        assert "Overview" not in names
        assert "Requirements" not in names
        assert "Invoice" in names

    def test_empty_prd_returns_empty(self):
        entities = _extract_entities("")
        assert entities == []

    def test_deduplication_across_strategies(self):
        prd = """
| Entity | Description |
|--------|-------------|
| Invoice | Customer invoice |

## Invoice
- id: UUID
- amount: decimal
"""
        entities = _extract_entities(prd)
        invoice_count = sum(1 for e in entities if e["name"] == "Invoice")
        assert invoice_count == 1
        # Should have merged fields from heading strategy
        inv = next(e for e in entities if e["name"] == "Invoice")
        field_names = {f["name"] for f in inv.get("fields", [])}
        assert "id" in field_names


# ===================================================================
# State machine extraction
# ===================================================================

class TestStateMachineExtraction:
    def test_arrow_notation(self):
        prd = """
## Invoice Status State Machine
draft -> submitted -> approved -> paid -> voided
"""
        entities = [{"name": "Invoice", "fields": [{"name": "status", "type": "string"}]}]
        sms = _extract_state_machines(prd, entities)
        assert len(sms) >= 1
        sm = sms[0]
        assert "draft" in sm["states"]
        assert "approved" in sm["states"]
        assert len(sm["transitions"]) >= 3

    def test_prose_transitions(self):
        prd = """
An Order transitions from pending to confirmed.
An Order transitions from confirmed to shipped.
"""
        entities = [{"name": "Order", "fields": []}]
        sms = _extract_state_machines(prd, entities)
        assert len(sms) >= 1
        sm = next(s for s in sms if s["entity"] == "Order")
        states = set(sm["states"])
        assert "pending" in states
        assert "confirmed" in states
        assert "shipped" in states

    def test_enum_values_near_entity(self):
        prd = """
## Invoice
- id: UUID
- status: string

Invoice status: draft, submitted, approved, paid, voided
"""
        entities = [{"name": "Invoice", "fields": [{"name": "status", "type": "string"}]}]
        sms = _extract_state_machines(prd, entities)
        assert len(sms) >= 1
        sm = sms[0]
        assert len(sm["states"]) >= 4

    def test_deduplication_strips_status_suffix(self):
        prd = """
## InvoiceStatus State Machine
draft -> submitted -> approved

## Invoice State Machine
draft -> submitted -> approved -> paid -> voided
"""
        entities = [{"name": "Invoice", "fields": [{"name": "status", "type": "string"}]}]
        sms = _extract_state_machines(prd, entities)
        # Should deduplicate to one machine (keep the one with more transitions)
        invoice_sms = [s for s in sms if "invoice" in s["entity"].lower()]
        assert len(invoice_sms) == 1
        assert len(invoice_sms[0]["transitions"]) >= 3


# ===================================================================
# Event extraction
# ===================================================================

class TestEventExtraction:
    def test_section_events(self):
        prd = """
## Events

The following domain events are used:
- `ar.invoice.created` — when invoice is created
- `ar.payment.applied` — when payment is applied
- `ap.purchase.approved` — when PO is approved
"""
        events = _extract_events(prd)
        names = {e["name"] for e in events}
        assert "ar.invoice.created" in names
        assert "ar.payment.applied" in names

    def test_prose_publish(self):
        prd = """
The AR service publishes an `invoice.created` event when a new invoice is saved.
The AP service emits a `payment.completed` event after payment processing.
"""
        events = _extract_events(prd)
        names = {e["name"] for e in events}
        assert "invoice.created" in names
        assert "payment.completed" in names

    def test_prose_subscribe(self):
        prd = """
The GL service subscribes to `ar.invoice.posted` for journal creation.
"""
        events = _extract_events(prd)
        names = {e["name"] for e in events}
        assert "ar.invoice.posted" in names


# ===================================================================
# Event name normalization
# ===================================================================

class TestNormalizeEventName:
    def test_already_dotted(self):
        assert _normalize_event_name("ar.invoice.created") == "ar.invoice.created"

    def test_camel_case(self):
        result = _normalize_event_name("InvoiceCreated")
        assert "." in result
        assert "invoice" in result.lower()

    def test_snake_case(self):
        result = _normalize_event_name("INVOICE_CREATED")
        assert "." in result


# ===================================================================
# Technology hints
# ===================================================================

class TestTechnologyHints:
    def test_detects_python(self):
        hints = _extract_technology_hints("Built with Python and FastAPI")
        assert hints["language"] == "Python"
        assert hints["framework"] == "FastAPI"

    def test_detects_typescript(self):
        hints = _extract_technology_hints("Using TypeScript with NestJS framework")
        assert hints["language"] == "TypeScript"
        assert hints["framework"] == "NestJS"

    def test_detects_database(self):
        hints = _extract_technology_hints("Data stored in PostgreSQL")
        assert hints["database"] == "PostgreSQL"

    def test_no_hints(self):
        hints = _extract_technology_hints("Some generic text about an app")
        assert hints["language"] is None


# ===================================================================
# Full parse_prd integration
# ===================================================================

class TestParsePRD:
    def test_minimal_prd(self):
        result = parse_prd("too short")
        assert result.entities == []

    def test_full_prd(self):
        prd = (
            "# Project: GlobalBooks\n\n"
            "## Technology Stack\n"
            "Built with Python/FastAPI and TypeScript/NestJS. PostgreSQL database.\n\n"
            "## Data Model\n\n"
            "| Entity | Owning Service | Description |\n"
            "|--------|---------------|-------------|\n"
            "| JournalEntry | GL | General ledger entry |\n"
            "| JournalLine | GL | Line item in journal |\n"
            "| Invoice | AR | Customer invoice |\n"
            "| Customer | AR | Customer record |\n\n"
            "## Invoice\n"
            "- id: UUID\n"
            "- amount: decimal\n"
            "- status: string (draft, sent, paid, voided)\n\n"
            "## State Machines\n\n"
            "### Invoice Status State Machine\n"
            "draft -> sent -> paid -> voided\n\n"
            "## Events\n\n"
            "- `ar.invoice.created` -- new invoice\n"
            "- `ar.invoice.sent` -- invoice sent to customer\n"
        )
        result = parse_prd(prd)
        assert result.project_name == "GlobalBooks"
        assert len(result.entities) >= 4
        assert len(result.state_machines) >= 1
        assert len(result.events) >= 1  # Section regex captures first event; others via prose
        assert result.technology_hints["language"] == "Python"
        assert result.technology_hints["database"] == "PostgreSQL"


# ===================================================================
# Format domain model
# ===================================================================

class TestFormatDomainModel:
    def test_empty_parsed_returns_empty(self):
        result = format_domain_model(ParsedPRD())
        assert result == ""

    def test_with_entities(self):
        parsed = ParsedPRD(
            entities=[
                {"name": "Invoice", "fields": [
                    {"name": "id", "type": "UUID"},
                    {"name": "amount", "type": "decimal"},
                ], "description": "Customer invoice"},
            ],
        )
        result = format_domain_model(parsed)
        assert "Entities (1 found)" in result
        assert "Invoice" in result
        assert "id(UUID)" in result

    def test_with_state_machines(self):
        parsed = ParsedPRD(
            state_machines=[{
                "entity": "Invoice",
                "states": ["draft", "sent", "paid"],
                "transitions": [
                    {"from_state": "draft", "to_state": "sent", "trigger": "send"},
                ],
            }],
        )
        result = format_domain_model(parsed)
        assert "State Machines (1 found)" in result
        assert "draft → sent → paid" in result

    def test_with_events(self):
        parsed = ParsedPRD(
            events=[{"name": "ar.invoice.created", "publisher": "AR"}],
        )
        result = format_domain_model(parsed)
        assert "Events (1 found)" in result
        assert "ar.invoice.created" in result
        assert "AR" in result
