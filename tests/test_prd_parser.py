"""Tests for PRD parser (v16 Phase 2.1)."""

from __future__ import annotations

import pytest

from agent_team_v15.prd_parser import (
    BusinessRule,
    ParsedPRD,
    parse_prd,
    format_domain_model,
    extract_business_rules,
    _extract_entities,
    _extract_state_machines,
    _extract_events,
    _extract_project_name,
    _extract_technology_hints,
    _is_section_heading,
    _to_pascal,
    _normalize_event_name,
    _normalize_for_dedup,
    _word_overlap_ratio,
    _filter_garbage_rules,
    _build_entity_service_lookup,
    _build_heading_entity_ranges,
    _entity_from_heading_context,
    _entity_names_lower,
)

# Verify the module is importable from the package
from agent_team_v15 import prd_parser


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


# ===================================================================
# V16 Phase 2.2: Pipeline integration (Phase 0.8)
# ===================================================================

class TestPipelineIntegration:
    """Verify parse_prd + format_domain_model chain for cli.py Phase 0.8."""

    def test_parse_and_format_roundtrip(self):
        """Full roundtrip: PRD text -> parsed -> formatted markdown."""
        prd = (
            "# My App\n\n"
            "## Data Model\n\n"
            "| Entity | Owning Service | Description |\n"
            "|--------|---------------|-------------|\n"
            "| User | Auth | App user |\n"
            "| Order | Orders | Customer order |\n"
            "| Product | Catalog | Product item |\n\n"
            "### Order Status State Machine\n"
            "pending -> confirmed -> shipped -> delivered\n"
        )
        parsed = parse_prd(prd)
        formatted = format_domain_model(parsed)
        assert "Entities" in formatted
        assert "User" in formatted
        assert "Order" in formatted
        assert "State Machines" in formatted

    def test_format_returns_empty_for_no_entities(self):
        """Empty PRD -> empty format (no injection into prompt)."""
        parsed = parse_prd("No entities here, just some short text. " * 3)
        formatted = format_domain_model(parsed)
        assert formatted == ""

    def test_entities_list_usable_for_coverage_scan(self):
        """Parsed entities can be passed directly to run_entity_coverage_scan."""
        prd = (
            "# Test\n\n"
            "| Entity | Owning Service | Description |\n"
            "|--------|---------------|-------------|\n"
            "| Invoice | AR | Invoice record |\n"
            "| Payment | AR | Payment record |\n"
            "| Customer | AR | Customer record |\n"
        )
        parsed = parse_prd(prd)
        # Entities should have the 'name' key expected by run_entity_coverage_scan
        for ent in parsed.entities:
            assert "name" in ent
        assert len(parsed.entities) >= 3


# ===================================================================
# Business rule extraction
# ===================================================================

# Shared PRD snippet used by multiple tests
_AP_PRD = """\
# ERP System PRD

## AP Service
Manages purchase invoices and vendor payments.

### Entities

| Entity | Owning Service | Description |
|--------|---------------|-------------|
| PurchaseInvoice | AP | Vendor invoice for matching |
| PurchaseOrder | AP | Approved purchase order |
| GoodsReceipt | AP | Received goods confirmation |

### PurchaseInvoice State Machine
| From | To | Trigger | Guard |
|------|-----|---------|-------|
| received | matched | user_matches | guard: 3-way match passes with PO quantity times unit price equals invoice amount within configurable tolerance (default 2%) |
| matched | approved | manager_approves | guard: approval workflow complete |

### Procure-to-Pay Flow
1. Vendor submits invoice
2. System performs 3-way matching: PO quantity times unit price versus goods receipt quantity versus invoice amount
3. System creates GL journal entry: DR expense accounts, CR accounts payable

### Acceptance Criteria
8. AP purchase invoice 3-way matching validates against PO and goods receipt
9. System generates monthly AP aging report
"""


class TestBusinessRuleExtraction:
    def test_extracts_guard_condition(self):
        """Guard condition from state machine table row is extracted."""
        rules = extract_business_rules(
            _AP_PRD,
            entities=[
                {"name": "PurchaseInvoice", "owning_context": "AP"},
                {"name": "PurchaseOrder", "owning_context": "AP"},
                {"name": "GoodsReceipt", "owning_context": "AP"},
            ],
            state_machines=[{
                "entity": "PurchaseInvoice",
                "states": ["received", "matched", "approved"],
                "transitions": [
                    {"from_state": "received", "to_state": "matched", "trigger": "user_matches"},
                    {"from_state": "matched", "to_state": "approved", "trigger": "manager_approves"},
                ],
            }],
        )
        guard_rules = [r for r in rules if r.rule_type == "guard"]
        assert len(guard_rules) >= 1
        match_rule = next(
            (r for r in guard_rules if "3-way" in r.description.lower()),
            None,
        )
        assert match_rule is not None
        assert match_rule.entity == "PurchaseInvoice"
        assert "multiplication" in match_rule.required_operations

    def test_extracts_flow_step(self):
        """System action step from a flow section is extracted."""
        rules = extract_business_rules(
            _AP_PRD,
            entities=[
                {"name": "PurchaseInvoice", "owning_context": "AP"},
                {"name": "PurchaseOrder", "owning_context": "AP"},
                {"name": "GoodsReceipt", "owning_context": "AP"},
            ],
        )
        flow_rules = [r for r in rules if r.rule_type in ("validation", "computation", "integration")]
        descs_lower = [r.description.lower() for r in flow_rules]
        assert any("3-way matching" in d for d in descs_lower), (
            f"Expected a flow rule about 3-way matching; got: {descs_lower}"
        )

    def test_extracts_acceptance_criterion(self):
        """Acceptance criterion mentioning entity + action verb is extracted."""
        rules = extract_business_rules(
            _AP_PRD,
            entities=[
                {"name": "PurchaseInvoice", "owning_context": "AP"},
                {"name": "PurchaseOrder", "owning_context": "AP"},
                {"name": "GoodsReceipt", "owning_context": "AP"},
            ],
        )
        ac_rules = [r for r in rules if r.rule_type == "validation"]
        descs_lower = [r.description.lower() for r in ac_rules]
        assert any("purchase invoice" in d and "validates" in d for d in descs_lower), (
            f"Expected an AC rule about purchase invoice validation; got: {descs_lower}"
        )

    def test_extracts_tolerance_pattern(self):
        """Tolerance/threshold pattern near entity creates validation rule."""
        prd = """\
# Matching Service

| Entity | Owning Service | Description |
|--------|---------------|-------------|
| PurchaseInvoice | AP | Invoice for matching |

The PurchaseInvoice matching uses a configurable tolerance threshold (default 2%) for amount comparison.
"""
        rules = extract_business_rules(
            prd,
            entities=[{"name": "PurchaseInvoice", "owning_context": "AP"}],
        )
        tolerance_rules = [
            r for r in rules
            if "comparison" in r.required_operations or "tolerance_check" in r.required_operations
        ]
        assert len(tolerance_rules) >= 1
        assert tolerance_rules[0].entity == "PurchaseInvoice"

    def test_empty_prd_returns_empty(self):
        """Empty or too-short PRD text returns no rules."""
        assert extract_business_rules("") == []
        assert extract_business_rules("short") == []

    def test_deduplication(self):
        """Same rule detected by multiple strategies produces only one entry."""
        rules = extract_business_rules(
            _AP_PRD,
            entities=[
                {"name": "PurchaseInvoice", "owning_context": "AP"},
                {"name": "PurchaseOrder", "owning_context": "AP"},
                {"name": "GoodsReceipt", "owning_context": "AP"},
            ],
            state_machines=[{
                "entity": "PurchaseInvoice",
                "states": ["received", "matched", "approved"],
                "transitions": [
                    {"from_state": "received", "to_state": "matched", "trigger": "user_matches"},
                    {"from_state": "matched", "to_state": "approved", "trigger": "manager_approves"},
                ],
            }],
        )
        # Each unique entity+description pair should appear at most once
        seen: set[tuple[str, str]] = set()
        for r in rules:
            key = (r.entity.lower(), r.description.lower())
            assert key not in seen, f"Duplicate rule: {r.entity} / {r.description}"
            seen.add(key)

    def test_parse_prd_includes_business_rules(self):
        """Full parse_prd() includes business_rules in its result."""
        result = parse_prd(_AP_PRD)
        assert hasattr(result, "business_rules")
        assert isinstance(result.business_rules, list)
        # Should have extracted at least one rule from this rich PRD
        assert len(result.business_rules) >= 1
        assert all(isinstance(r, BusinessRule) for r in result.business_rules)

    def test_format_domain_model_includes_rules(self):
        """format_domain_model renders the business rules section."""
        parsed = ParsedPRD(
            business_rules=[
                BusinessRule(
                    id="BR-AP-001",
                    service="ap",
                    entity="PurchaseInvoice",
                    rule_type="guard",
                    description="3-way match passes within tolerance",
                    required_operations=["multiplication", "comparison"],
                    anti_patterns=["Check only for field existence without comparing values"],
                    source_line=10,
                ),
            ],
        )
        result = format_domain_model(parsed)
        assert "Business Rules (1 found)" in result
        assert "BR-AP-001" in result
        assert "PurchaseInvoice" in result
        assert "3-way match passes within tolerance" in result
        assert "[guard]" in result


# ===================================================================
# Fix 1: Deduplication improvements
# ===================================================================

class TestDeduplicationImprovements:
    """Test improved word-overlap deduplication."""

    def test_word_overlap_ratio_identical(self):
        words_a = {"3way", "match", "po", "quantity", "price"}
        words_b = {"3way", "match", "po", "quantity", "price"}
        assert _word_overlap_ratio(words_a, words_b) == 1.0

    def test_word_overlap_ratio_high(self):
        words_a = _normalize_for_dedup("3-way match passes with PO quantity times unit price")
        words_b = _normalize_for_dedup("3-way matching PO quantity times unit price versus invoice")
        ratio = _word_overlap_ratio(words_a, words_b)
        assert ratio > 0.60, f"Expected >0.60, got {ratio}"

    def test_word_overlap_ratio_low(self):
        words_a = _normalize_for_dedup("approval workflow complete")
        words_b = _normalize_for_dedup("bank account has sufficient balance")
        ratio = _word_overlap_ratio(words_a, words_b)
        assert ratio < 0.60, f"Expected <0.60, got {ratio}"

    def test_word_overlap_empty(self):
        assert _word_overlap_ratio(set(), {"word"}) == 0.0
        assert _word_overlap_ratio(set(), set()) == 0.0

    def test_dedup_keeps_most_specific_operations(self):
        """When two rules overlap, keep the one with more required_operations."""
        prd = """\
# Test PRD

| Entity | Owning Service | Description |
|--------|---------------|-------------|
| PurchaseInvoice | AP | Invoice |

### PurchaseInvoice State Machine
| From | To | Trigger | Guard |
|------|-----|---------|-------|
| received | matched | match | guard: 3-way match PO quantity times unit price equals invoice amount within tolerance |

### Procure-to-Pay Flow
1. System performs purchase invoice 3-way matching: PO quantity times unit price versus invoice amount
"""
        rules = extract_business_rules(
            prd,
            entities=[{"name": "PurchaseInvoice", "owning_context": "AP"}],
            state_machines=[{
                "entity": "PurchaseInvoice",
                "states": ["received", "matched"],
                "transitions": [
                    {"from_state": "received", "to_state": "matched", "trigger": "match"},
                ],
            }],
        )
        # Both rules mention PurchaseInvoice, so dedup should merge them
        matching = [r for r in rules if "3-way" in r.description.lower() or "3way" in r.description.lower()]
        assert len(matching) == 1, f"Expected 1 matching rule, got {len(matching)}: {[r.description[:80] for r in matching]}"
        # The kept rule should have the most operations (the guard one has tolerance_check)
        assert "tolerance_check" in matching[0].required_operations

    def test_dedup_same_entity_different_description(self):
        """Two distinct rules for the same entity should NOT be deduplicated."""
        prd = """\
# Test PRD

| Entity | Owning Service | Description |
|--------|---------------|-------------|
| Invoice | AR | Customer invoice |

### Invoice State Machine
| From | To | Trigger | Guard |
|------|-----|---------|-------|
| draft | sent | send | guard: at least one line item exists |
| sent | paid | pay | guard: amount paid equals total amount |
"""
        rules = extract_business_rules(
            prd,
            entities=[{"name": "Invoice", "owning_context": "AR"}],
            state_machines=[{
                "entity": "Invoice",
                "states": ["draft", "sent", "paid"],
                "transitions": [
                    {"from_state": "draft", "to_state": "sent", "trigger": "send"},
                    {"from_state": "sent", "to_state": "paid", "trigger": "pay"},
                ],
            }],
        )
        assert len(rules) >= 2, f"Expected >= 2 distinct rules, got {len(rules)}"


# ===================================================================
# Fix 2: Service attribution via heading context
# ===================================================================

class TestServiceAttribution:
    """Test that guard rules are attributed to the state machine owner."""

    def test_guard_attributed_to_state_machine_entity(self):
        """Guard on PurchaseInvoice mentioning JournalEntry should be AP, not GL."""
        prd = """\
# ERP PRD

| Entity | Owning Service | Description |
|--------|---------------|-------------|
| PurchaseInvoice | AP | Vendor invoice |
| JournalEntry | GL | GL entry |

### PurchaseInvoice State Machine
| From | To | Trigger | Guard |
|------|-----|---------|-------|
| approved | paid | pay | guard: creates GL journal entry for expense recognition |
"""
        rules = extract_business_rules(
            prd,
            entities=[
                {"name": "PurchaseInvoice", "owning_context": "AP"},
                {"name": "JournalEntry", "owning_context": "GL"},
            ],
            state_machines=[{
                "entity": "PurchaseInvoice",
                "states": ["approved", "paid"],
                "transitions": [
                    {"from_state": "approved", "to_state": "paid", "trigger": "pay"},
                ],
            }],
        )
        guard_rules = [r for r in rules if r.rule_type == "guard"]
        assert len(guard_rules) >= 1
        # The guard should be attributed to AP (PurchaseInvoice's owner),
        # NOT to GL (JournalEntry's owner)
        for r in guard_rules:
            if "journal" in r.description.lower():
                assert r.service == "ap", (
                    f"Guard mentioning journal should be AP service, got {r.service}"
                )

    def test_heading_context_resolves_entity(self):
        """Heading context should pick the correct entity for guard lines."""
        prd = """\
# Test

| Entity | Owning Service | Description |
|--------|---------------|-------------|
| Invoice | AR | Customer invoice |
| JournalEntry | GL | GL entry |

### Invoice Status State Machine

**Transitions:**
- draft -> sent: user_sends (guard: at least one line item exists)
- sent -> void: user_voids (guard: creates reversing journal entry)
"""
        entities = [
            {"name": "Invoice", "owning_context": "AR"},
            {"name": "JournalEntry", "owning_context": "GL"},
        ]
        entity_map = _entity_names_lower(entities)
        ranges = _build_heading_entity_ranges(prd, entity_map)
        # The heading range for Invoice should cover the guard lines
        invoice_ranges = [(s, e) for s, e, n in ranges if n == "Invoice"]
        assert len(invoice_ranges) >= 1

    def test_build_entity_service_lookup(self):
        """Entity->service lookup dict works correctly."""
        entities = [
            {"name": "PurchaseInvoice", "owning_context": "AP Service"},
            {"name": "Invoice", "owning_context": "AR Service"},
            {"name": "JournalEntry", "owning_context": "GL"},
        ]
        lookup = _build_entity_service_lookup(entities)
        assert lookup["purchaseinvoice"] == "ap"
        assert lookup["invoice"] == "ar"
        assert lookup["journalentry"] == "gl"

    def test_entity_from_heading_context_narrowest(self):
        """When nested headings exist, return the most specific (narrowest)."""
        ranges = [
            (1, 100, "Section"),
            (10, 30, "Invoice"),
            (15, 25, "InvoiceLine"),
        ]
        assert _entity_from_heading_context(20, ranges) == "InvoiceLine"
        assert _entity_from_heading_context(12, ranges) == "Invoice"
        assert _entity_from_heading_context(50, ranges) == "Section"
        assert _entity_from_heading_context(200, ranges) == ""


# ===================================================================
# Fix 3: Garbage rule filtering
# ===================================================================

class TestGarbageFiltering:
    """Test that non-rule content is filtered out."""

    def test_filters_long_descriptions(self):
        rules = [
            BusinessRule(id="BR-1", service="ap", entity="X", rule_type="validation",
                         description="A" * 301, source_line=1),
            BusinessRule(id="BR-2", service="ap", entity="X", rule_type="validation",
                         description="Short valid rule", source_line=2),
        ]
        filtered = _filter_garbage_rules(rules)
        assert len(filtered) == 1
        assert filtered[0].id == "BR-2"

    def test_filters_field_type_annotations(self):
        rules = [
            BusinessRule(id="BR-1", service="ap", entity="X", rule_type="validation",
                         description="id (UUID) primary key for the entity", source_line=1),
            BusinessRule(id="BR-2", service="ap", entity="X", rule_type="validation",
                         description="amount (decimal) total invoice amount", source_line=2),
            BusinessRule(id="BR-3", service="ap", entity="X", rule_type="validation",
                         description="validate amount against PO total", source_line=3),
        ]
        filtered = _filter_garbage_rules(rules)
        assert len(filtered) == 1
        assert filtered[0].id == "BR-3"

    def test_filters_markdown_table_content(self):
        rules = [
            BusinessRule(id="BR-1", service="ap", entity="X", rule_type="validation",
                         description="| Field | Type | Description | more columns here", source_line=1),
            BusinessRule(id="BR-2", service="ap", entity="X", rule_type="guard",
                         description="approval complete", source_line=2),
        ]
        filtered = _filter_garbage_rules(rules)
        assert len(filtered) == 1
        assert filtered[0].id == "BR-2"

    def test_filters_transition_line_garbage(self):
        """Lines starting with state transition notation should be filtered."""
        rules = [
            BusinessRule(id="BR-1", service="ar", entity="Invoice", rule_type="validation",
                         description="- sent \u2192 written_off: user_writes_off (guard: aging threshold exceeded)",
                         source_line=1),
            BusinessRule(id="BR-2", service="ar", entity="Invoice", rule_type="guard",
                         description="aging threshold exceeded", source_line=2),
        ]
        filtered = _filter_garbage_rules(rules)
        assert len(filtered) == 1
        assert filtered[0].id == "BR-2"

    def test_keeps_valid_rules(self):
        rules = [
            BusinessRule(id="BR-1", service="ap", entity="X", rule_type="guard",
                         description="3-way match passes within tolerance", source_line=1),
            BusinessRule(id="BR-2", service="ar", entity="Y", rule_type="validation",
                         description="amount paid equals total amount", source_line=2),
        ]
        filtered = _filter_garbage_rules(rules)
        assert len(filtered) == 2
