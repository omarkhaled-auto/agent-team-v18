"""Tests for contract code generation (scaling component 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_team_v15.contract_generator import (
    ContractBundle,
    ServiceContract,
    generate_contracts,
    generate_contracts_md,
    generate_python_client,
    generate_typescript_client,
    generate_event_schemas_py,
    generate_event_schemas_ts,
    write_contract_files,
    _group_entities_by_service,
    _normalize_service_name,
    _generate_endpoints,
    _pluralize,
)
from agent_team_v15.prd_parser import ParsedPRD


# ===================================================================
# Service name normalization
# ===================================================================

class TestNormalizeServiceName:
    def test_strips_service_suffix(self):
        assert _normalize_service_name("Auth Service") == "auth"

    def test_abbreviates_gl(self):
        assert _normalize_service_name("General Ledger") == "gl"

    def test_abbreviates_ar(self):
        assert _normalize_service_name("Accounts Receivable") == "ar"

    def test_abbreviates_ap(self):
        assert _normalize_service_name("Accounts Payable") == "ap"

    def test_simple_name(self):
        assert _normalize_service_name("Banking") == "banking"

    def test_strips_module_suffix(self):
        assert _normalize_service_name("Tax Module") == "tax"


# ===================================================================
# Entity grouping
# ===================================================================

class TestGroupEntitiesByService:
    def test_groups_correctly(self):
        entities = [
            {"name": "User", "owning_context": "Auth Service"},
            {"name": "Role", "owning_context": "Auth Service"},
            {"name": "Invoice", "owning_context": "Accounts Receivable"},
        ]
        groups = _group_entities_by_service(entities)
        assert len(groups) == 2
        assert len(groups["auth"]) == 2
        assert len(groups["ar"]) == 1

    def test_missing_context_uses_default(self):
        entities = [{"name": "Orphan", "owning_context": ""}]
        groups = _group_entities_by_service(entities)
        assert "default" in groups


# ===================================================================
# Pluralization
# ===================================================================

class TestPluralize:
    def test_regular(self):
        assert _pluralize("Invoice") == "Invoices"

    def test_ends_in_s(self):
        assert _pluralize("Address") == "Addresses"

    def test_ends_in_y(self):
        assert _pluralize("Entry") == "Entries"


# ===================================================================
# Endpoint generation
# ===================================================================

class TestGenerateEndpoints:
    def test_generates_crud(self):
        entity = {
            "name": "Invoice",
            "fields": [
                {"name": "id", "type": "UUID"},
                {"name": "amount", "type": "decimal"},
                {"name": "status", "type": "str"},
            ],
        }
        endpoints = _generate_endpoints(entity, "ar")
        methods = {ep["method"] for ep in endpoints}
        assert "GET" in methods
        assert "POST" in methods
        assert "PATCH" in methods
        assert len(endpoints) == 4  # list, create, get, update

    def test_path_uses_kebab_plural(self):
        entity = {"name": "JournalEntry", "fields": [{"name": "id", "type": "UUID"}]}
        endpoints = _generate_endpoints(entity, "gl")
        assert any("/journal-entries" in ep["path"] for ep in endpoints)


# ===================================================================
# CONTRACTS.md generation
# ===================================================================

class TestGenerateContractsMd:
    def test_contains_project_name(self):
        services = [ServiceContract(
            service_name="gl", display_name="General Ledger",
            entities=[{"name": "JournalEntry", "fields": [{"name": "id", "type": "UUID"}]}],
            endpoints=[{"method": "GET", "path": "/journal-entries", "description": "List", "response_type": "list"}],
            events_published=[], events_subscribed=[],
        )]
        md = generate_contracts_md("GlobalBooks", services)
        assert "GlobalBooks" in md
        assert "General Ledger" in md
        assert "GET /journal-entries" in md

    def test_contains_events(self):
        services = [ServiceContract(
            service_name="ar", display_name="AR",
            entities=[], endpoints=[],
            events_published=[{"name": "ar.invoice.created", "publisher": "ar"}],
            events_subscribed=[],
        )]
        md = generate_contracts_md("Test", services)
        assert "ar.invoice.created" in md


# ===================================================================
# Python client generation
# ===================================================================

class TestGeneratePythonClient:
    def test_generates_response_dataclass(self):
        svc = ServiceContract(
            service_name="gl", display_name="GL",
            entities=[{"name": "JournalEntry", "fields": [
                {"name": "id", "type": "UUID"},
                {"name": "entry_number", "type": "str"},
            ]}],
            endpoints=[], events_published=[], events_subscribed=[],
        )
        code = generate_python_client(svc)
        assert "class JournalEntryResponse:" in code
        assert "id: str" in code
        assert "entry_number: str" in code

    def test_generates_request_dataclass(self):
        svc = ServiceContract(
            service_name="ar", display_name="AR",
            entities=[{"name": "Invoice", "fields": [
                {"name": "id", "type": "UUID"},
                {"name": "amount", "type": "decimal"},
                {"name": "tenant_id", "type": "UUID"},
            ]}],
            endpoints=[], events_published=[], events_subscribed=[],
        )
        code = generate_python_client(svc)
        assert "class CreateInvoiceRequest:" in code
        assert "amount: float" in code
        # id and tenant_id should NOT be in create request
        assert "class CreateInvoiceRequest" in code
        lines = code.split("\n")
        in_create = False
        for line in lines:
            if "class CreateInvoiceRequest" in line:
                in_create = True
            elif in_create and line.strip().startswith("class "):
                break
            elif in_create and "tenant_id" in line:
                pytest.fail("tenant_id should not be in CreateInvoiceRequest")

    def test_generates_client_class(self):
        svc = ServiceContract(
            service_name="gl", display_name="GL",
            entities=[{"name": "Account", "fields": [{"name": "id", "type": "UUID"}]}],
            endpoints=[], events_published=[], events_subscribed=[],
        )
        code = generate_python_client(svc)
        assert "class GlClient:" in code
        assert "async def list_accounts" in code
        assert "async def get_account" in code

    def test_uses_httpx(self):
        svc = ServiceContract(
            service_name="ar", display_name="AR",
            entities=[{"name": "Customer", "fields": [{"name": "id", "type": "UUID"}]}],
            endpoints=[], events_published=[], events_subscribed=[],
        )
        code = generate_python_client(svc)
        assert "import httpx" in code
        assert "httpx.AsyncClient" in code


# ===================================================================
# TypeScript client generation
# ===================================================================

class TestGenerateTypescriptClient:
    def test_generates_interface(self):
        svc = ServiceContract(
            service_name="gl", display_name="GL",
            entities=[{"name": "JournalEntry", "fields": [
                {"name": "id", "type": "UUID"},
                {"name": "amount", "type": "decimal"},
            ]}],
            endpoints=[], events_published=[], events_subscribed=[],
        )
        code = generate_typescript_client(svc)
        assert "export interface JournalEntry {" in code
        assert "id: string;" in code
        assert "amount: number;" in code

    def test_generates_create_input(self):
        svc = ServiceContract(
            service_name="ar", display_name="AR",
            entities=[{"name": "Invoice", "fields": [
                {"name": "id", "type": "UUID"},
                {"name": "total", "type": "decimal"},
            ]}],
            endpoints=[], events_published=[], events_subscribed=[],
        )
        code = generate_typescript_client(svc)
        assert "export interface CreateInvoiceInput {" in code

    def test_generates_client_class(self):
        svc = ServiceContract(
            service_name="gl", display_name="GL",
            entities=[{"name": "Account", "fields": [{"name": "id", "type": "UUID"}]}],
            endpoints=[], events_published=[], events_subscribed=[],
        )
        code = generate_typescript_client(svc)
        assert "export class GlClient {" in code
        assert "async listAccounts" in code
        assert "async getAccount" in code


# ===================================================================
# Event schemas
# ===================================================================

class TestEventSchemas:
    def test_python_event_constants(self):
        events = [
            {"name": "ar.invoice.created"},
            {"name": "gl.period.closed"},
        ]
        code = generate_event_schemas_py(events)
        assert 'EVENT_AR_INVOICE_CREATED = "ar.invoice.created"' in code
        assert 'EVENT_GL_PERIOD_CLOSED = "gl.period.closed"' in code
        assert "class EventEnvelope:" in code

    def test_typescript_event_constants(self):
        events = [{"name": "ar.invoice.created"}]
        code = generate_event_schemas_ts(events)
        assert "EVENT_AR_INVOICE_CREATED = 'ar.invoice.created'" in code
        assert "export interface EventEnvelope {" in code


# ===================================================================
# Full pipeline: ParsedPRD → ContractBundle
# ===================================================================

class TestGenerateContracts:
    def test_full_pipeline(self):
        parsed = ParsedPRD(
            project_name="TestApp",
            entities=[
                {"name": "User", "fields": [
                    {"name": "id", "type": "UUID", "required": True},
                    {"name": "email", "type": "str", "required": True},
                ], "description": "App user", "owning_context": "Auth Service"},
                {"name": "Invoice", "fields": [
                    {"name": "id", "type": "UUID", "required": True},
                    {"name": "amount", "type": "decimal", "required": True},
                ], "description": "Customer invoice", "owning_context": "Accounts Receivable"},
            ],
            events=[
                {"name": "ar.invoice.created", "publisher": "ar", "payload_fields": []},
            ],
        )
        bundle = generate_contracts(parsed)
        assert bundle.project_name == "TestApp"
        assert len(bundle.services) == 2
        assert "CONTRACTS.md" in bundle.contracts_md or "Cross-Module" in bundle.contracts_md
        assert "auth" in bundle.python_clients
        assert "ar" in bundle.python_clients
        assert "auth" in bundle.typescript_clients
        assert "ar" in bundle.typescript_clients
        assert "EVENT_AR_INVOICE_CREATED" in bundle.event_schemas_py

    def test_empty_prd(self):
        parsed = ParsedPRD()
        bundle = generate_contracts(parsed)
        assert len(bundle.services) == 0
        assert bundle.python_clients == {}


# ===================================================================
# File writing
# ===================================================================

class TestWriteContractFiles:
    def test_writes_all_files(self, tmp_path):
        bundle = ContractBundle(
            project_name="Test",
            services=[],
            contracts_md="# Contracts\n",
            python_clients={"auth": "# auth client\n"},
            typescript_clients={"auth": "// auth client\n"},
            event_schemas_py="# events\n",
            event_schemas_ts="// events\n",
        )
        created = write_contract_files(bundle, tmp_path)
        assert any("CONTRACTS.md" in str(p) for p in created)
        assert any("auth_client.py" in str(p) for p in created)
        assert any("auth-client.ts" in str(p) for p in created)
        assert any("event_schemas.py" in str(p) for p in created)
        assert any("event-schemas.ts" in str(p) for p in created)

        # Verify files exist on disk
        assert (tmp_path / "CONTRACTS.md").is_file()
        assert (tmp_path / "contracts" / "python" / "auth_client.py").is_file()
        assert (tmp_path / "contracts" / "typescript" / "auth-client.ts").is_file()


# ===================================================================
# Real PRD integration test
# ===================================================================

class TestRealPRD:
    def test_globalbooks_prd(self):
        """Test contract generation against the real GlobalBooks PRD."""
        prd_path = Path(r"C:\MY_PROJECTS\globalbooks\prd.md")
        if not prd_path.is_file():
            pytest.skip("GlobalBooks PRD not available")

        from agent_team_v15.prd_parser import parse_prd
        parsed = parse_prd(prd_path.read_text(encoding="utf-8"))
        bundle = generate_contracts(parsed)

        # Should produce contracts for multiple services
        assert len(bundle.services) >= 5, f"Expected 5+ services, got {len(bundle.services)}"

        # Should have Python and TypeScript clients
        assert len(bundle.python_clients) >= 5
        assert len(bundle.typescript_clients) >= 5

        # CONTRACTS.md should be substantial
        assert len(bundle.contracts_md) > 1000

        # Event schemas should have constants
        assert "EVENT_" in bundle.event_schemas_py
        assert "EVENT_" in bundle.event_schemas_ts

        # Python clients should have valid syntax
        for svc_name, code in bundle.python_clients.items():
            compile(code, f"{svc_name}_client.py", "exec")  # Syntax check

        # Print summary for manual inspection
        print(f"\nServices: {len(bundle.services)}")
        for svc in bundle.services:
            print(f"  {svc.service_name}: {len(svc.entities)} entities, {len(svc.endpoints)} endpoints")
        print(f"CONTRACTS.md: {len(bundle.contracts_md)} chars")
        print(f"Python clients: {len(bundle.python_clients)}")
        print(f"TypeScript clients: {len(bundle.typescript_clients)}")
