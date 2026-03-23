"""Tests for contract verification (scaling component 6)."""

from __future__ import annotations

import pytest

from agent_team_v15.contract_verifier import (
    ContractDeviation,
    VerificationResult,
    verify_service_contract,
    verify_all_contracts,
    format_verification_summary,
    verify_client_imports,
)
from agent_team_v15.contract_generator import ServiceContract
from agent_team_v15.interface_registry import ModuleInterface, EndpointEntry


# ===================================================================
# Single service verification
# ===================================================================

class TestVerifyServiceContract:
    def test_all_endpoints_found(self):
        contract_endpoints = [
            {"method": "GET", "path": "/invoices"},
            {"method": "POST", "path": "/invoices"},
            {"method": "GET", "path": "/invoices/{id}"},
        ]
        contract_entities = [{"name": "Invoice"}]
        actual_endpoints = [
            {"method": "GET", "path": "/invoices"},
            {"method": "POST", "path": "/invoices"},
            {"method": "GET", "path": "/invoices/:id"},
        ]
        actual_types = ["Invoice", "InvoiceLine"]

        result = verify_service_contract(
            "ar", contract_endpoints, contract_entities,
            actual_endpoints, actual_types,
        )
        assert result.endpoints_found == 3
        assert result.entities_found == 1
        assert result.is_clean

    def test_missing_endpoint_detected(self):
        contract_endpoints = [
            {"method": "GET", "path": "/invoices"},
            {"method": "POST", "path": "/invoices"},
            {"method": "DELETE", "path": "/invoices/{id}"},
        ]
        actual_endpoints = [
            {"method": "GET", "path": "/invoices"},
            {"method": "POST", "path": "/invoices"},
        ]

        result = verify_service_contract(
            "ar", contract_endpoints, [], actual_endpoints, [],
        )
        assert result.endpoints_found == 2
        assert not result.is_clean
        missing = [d for d in result.deviations if d.deviation_type == "missing_endpoint"]
        assert len(missing) == 1
        assert "DELETE" in missing[0].contract_spec

    def test_missing_entity_detected(self):
        contract_entities = [{"name": "Invoice"}, {"name": "Payment"}]
        actual_types = ["Invoice"]

        result = verify_service_contract(
            "ar", [], contract_entities, [], actual_types,
        )
        assert result.entities_found == 1
        missing = [d for d in result.deviations if d.deviation_type == "missing_entity"]
        assert len(missing) == 1
        assert "Payment" in missing[0].contract_spec

    def test_case_insensitive_entity_match(self):
        contract_entities = [{"name": "JournalEntry"}]
        actual_types = ["journalentry"]  # Different case

        result = verify_service_contract(
            "gl", [], contract_entities, [], actual_types,
        )
        assert result.entities_found == 1

    def test_empty_contract_is_clean(self):
        result = verify_service_contract("svc", [], [], [], [])
        assert result.is_clean
        assert result.endpoints_expected == 0


# ===================================================================
# Multi-service verification
# ===================================================================

class TestVerifyAllContracts:
    def test_all_services_verified(self):
        contracts = [
            ServiceContract(
                service_name="gl", display_name="GL",
                entities=[{"name": "JournalEntry"}],
                endpoints=[{"method": "GET", "path": "/journal-entries"}],
                events_published=[], events_subscribed=[],
            ),
            ServiceContract(
                service_name="ar", display_name="AR",
                entities=[{"name": "Invoice"}],
                endpoints=[{"method": "GET", "path": "/invoices"}],
                events_published=[], events_subscribed=[],
            ),
        ]
        registry = {
            "gl": ModuleInterface(
                module_name="gl",
                endpoints=[EndpointEntry(method="GET", path="/journal-entries", handler="list", file_path="gl/routes.py")],
                types=["JournalEntry"],
            ),
            "ar": ModuleInterface(
                module_name="ar",
                endpoints=[EndpointEntry(method="GET", path="/invoices", handler="list", file_path="ar/routes.py")],
                types=["Invoice"],
            ),
        }
        results = verify_all_contracts(contracts, registry)
        assert len(results) == 2
        assert all(r.is_clean for r in results)

    def test_missing_module_flagged(self):
        contracts = [
            ServiceContract(
                service_name="tax", display_name="Tax",
                entities=[{"name": "TaxCode"}],
                endpoints=[{"method": "GET", "path": "/tax-codes"}],
                events_published=[], events_subscribed=[],
            ),
        ]
        results = verify_all_contracts(contracts, {})  # Empty registry
        assert len(results) == 1
        assert not results[0].is_clean
        assert any(d.deviation_type == "missing_module" for d in results[0].deviations)


# ===================================================================
# Summary formatting
# ===================================================================

class TestFormatSummary:
    def test_empty_results(self):
        assert format_verification_summary([]) == ""

    def test_clean_services(self):
        results = [
            VerificationResult(
                service="gl", endpoints_expected=4, endpoints_found=4,
                entities_expected=2, entities_found=2,
            ),
        ]
        text = format_verification_summary(results)
        assert "CLEAN" in text
        assert "4/4" in text

    def test_deviations_shown(self):
        results = [
            VerificationResult(
                service="ar",
                endpoints_expected=4, endpoints_found=2,
                entities_expected=1, entities_found=1,
                deviations=[
                    ContractDeviation(
                        service="ar", deviation_type="missing_endpoint",
                        contract_spec="DELETE /invoices/{id}", actual_spec="not found",
                    ),
                    ContractDeviation(
                        service="ar", deviation_type="missing_endpoint",
                        contract_spec="PATCH /invoices/{id}", actual_spec="not found",
                    ),
                ],
            ),
        ]
        text = format_verification_summary(results)
        assert "2 deviations" in text
        assert "DELETE" in text

    def test_totals_correct(self):
        results = [
            VerificationResult(service="gl", endpoints_expected=10, endpoints_found=8,
                             entities_expected=5, entities_found=5),
            VerificationResult(service="ar", endpoints_expected=8, endpoints_found=8,
                             entities_expected=3, entities_found=2),
        ]
        text = format_verification_summary(results)
        assert "16/18" in text  # endpoints
        assert "7/8" in text    # entities


# ===================================================================
# Cross-service client import verification
# ===================================================================

class TestVerifyClientImports:
    def test_none_deps_returns_empty(self, tmp_path):
        assert verify_client_imports(tmp_path, None) == []

    def test_empty_deps_returns_empty(self, tmp_path):
        assert verify_client_imports(tmp_path, []) == []

    def test_detects_raw_fetch_ts(self, tmp_path):
        # Setup: ar service with a TS file that uses raw fetch to gl
        svc_dir = tmp_path / "services" / "ar" / "src" / "services"
        svc_dir.mkdir(parents=True)
        (svc_dir / "invoice.service.ts").write_text(
            'const resp = await fetch(`${this.glServiceUrl}/journal-entries`);\n'
            'export class InvoiceService {}\n',
            encoding="utf-8",
        )

        devs = verify_client_imports(
            tmp_path,
            [{"consumer": "ar", "provider": "gl"}],
        )
        assert len(devs) == 1
        assert devs[0].severity == "warning"
        assert devs[0].deviation_type == "raw_fetch"
        assert "raw fetch" in devs[0].actual_spec

    def test_detects_raw_fetch_python(self, tmp_path):
        # Setup: ar service with a Python file that uses httpx to call gl
        svc_dir = tmp_path / "services" / "ar" / "src" / "services"
        svc_dir.mkdir(parents=True)
        (svc_dir / "invoice_service.py").write_text(
            'import httpx\n'
            'response = httpx.post(f"{settings.GL_SERVICE_URL}/journal-entries")\n',
            encoding="utf-8",
        )

        devs = verify_client_imports(
            tmp_path,
            [{"consumer": "ar", "provider": "gl"}],
        )
        assert len(devs) == 1
        assert devs[0].severity == "warning"
        assert devs[0].deviation_type == "raw_fetch"

    def test_no_deviation_when_client_imported(self, tmp_path):
        # Setup: ap service that properly imports a generated gl client
        svc_dir = tmp_path / "services" / "ap" / "src"
        svc_dir.mkdir(parents=True)
        clients_dir = svc_dir / "clients"
        clients_dir.mkdir()
        (clients_dir / "gl-client.ts").write_text(
            'export class GlClient {}\n',
            encoding="utf-8",
        )
        (svc_dir / "payment.service.ts").write_text(
            'import { GlClient } from "./clients/gl-client";\n'
            'export class PaymentService {}\n',
            encoding="utf-8",
        )

        devs = verify_client_imports(
            tmp_path,
            [{"consumer": "ap", "provider": "gl"}],
        )
        assert devs == []

    def test_no_service_dir_returns_info(self, tmp_path):
        # Consumer directory doesn't exist at all
        devs = verify_client_imports(
            tmp_path,
            [{"consumer": "nonexistent", "provider": "gl"}],
        )
        assert len(devs) == 1
        assert devs[0].severity == "info"
        assert devs[0].deviation_type == "missing_client_import"
        assert "not found" in devs[0].actual_spec
