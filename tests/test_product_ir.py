from __future__ import annotations

import json
from pathlib import Path

from agent_team_v15.cli import _load_product_ir
from agent_team_v15.product_ir import (
    compile_product_ir,
    format_ir_summary,
    save_product_ir,
    _detect_integrations,
    _infer_verification_mode,
)


EVS_PRD = """# Project: EVS Customer Portal

## Technology Stack
| Layer | Technology |
|-------|------------|
| Backend | NestJS |
| Frontend | Next.js |
| Database | PostgreSQL |

## AP Service
Manages quotations and invoices.

### Entities
| Entity | Owning Service | Description |
|--------|----------------|-------------|
| Quotation | AP | Customer quotation |
| Invoice | AP | Customer invoice |

### Quotation State Machine
| From | To | Trigger | Guard |
|------|----|---------|-------|
| pending | approved | approve | manager approval |

## Feature F-001: Authentication
### Acceptance Criteria
- [ ] AC-1: GIVEN a valid signup, WHEN the customer completes signup, THEN a magic link email is sent via SendGrid.
- [ ] AC-2: GIVEN a valid magic link, WHEN the user opens the portal, THEN the dashboard displays a welcome message.

| POST | /api/v1/auth/signup | JWT | SignupRequest | SignupResponse |
| POST | /api/v1/auth/magic-link | none | MagicLinkRequest | MagicLinkResponse |

## Feature F-003: Quotation Approval
### Acceptance Criteria
- [ ] AC-3: GIVEN an unauthenticated caller, WHEN they POST approve, THEN the API returns 401.
- [ ] AC-4: GIVEN an approvable quotation, WHEN the customer approves it, THEN the system saves the decision to the database.
- [ ] AC-5: GIVEN an approved quotation, WHEN approval completes, THEN the backend sends notification email and push notification.

| POST | /api/v1/quotations/:id/approve | JWT | ApproveQuotationDto | QuotationResponse |
POST /api/v1/quotations/:id/approve - approves a quotation in Odoo via search_read follow-up sync.

## Workflow: Quotation Approval
Step 1: Customer opens the dashboard.
Step 2: Customer views the quotation details.
Step 3: Customer taps Approve.
Step 4: Backend calls Odoo search_read and updates quotation status.
Step 5: Backend sends push notification and email.

## Localization
Arabic and English are supported. The UI must support RTL layouts.
"""


MINIMAL_PRD = """# Project: Minimal Portal

## Technology Stack
| Layer | Technology |
|-------|------------|
| Backend | NestJS |
| Frontend | Next.js |
| Database | PostgreSQL |

## Catalog Service
### Entities
| Entity | Owning Service | Description |
|--------|----------------|-------------|
| Product | Catalog | Sellable item |

## Feature F-001: Product Catalog
### Acceptance Criteria
- [ ] AC-1: GIVEN a user, WHEN they visit the catalog, THEN the page shows products.
- [ ] AC-2: GIVEN a user, WHEN they create a product, THEN the API returns 201.
- [ ] AC-3: GIVEN a product, WHEN it is updated, THEN the API returns 200.
- [ ] AC-4: GIVEN a product, WHEN it is fetched, THEN the API returns 200.
- [ ] AC-5: GIVEN a product, WHEN it is deleted, THEN the API returns 204.

| GET | /api/v1/products | JWT | - | ProductListResponse |
| POST | /api/v1/products | JWT | CreateProductDto | ProductResponse |
| DELETE | /api/v1/products/:id | JWT | - | - |
"""

ARKANPM_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "product_ir" / "arkanpm_integration_regression.md"


def _write_prd(tmp_path: Path, content: str, name: str = "prd.md") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestProductIRCompile:
    def test_compile_product_ir_extracts_expected_shape(self, tmp_path: Path) -> None:
        prd_path = _write_prd(tmp_path, EVS_PRD)
        ir = compile_product_ir(prd_path)

        assert ir.schema_version == 2
        assert ir.project_name == "EVS Customer Portal"
        assert ir.stack_target.backend == "NestJS"
        assert ir.stack_target.frontend == "Next.js"
        assert ir.stack_target.db == "PostgreSQL"
        assert len(ir.entities) >= 2
        assert len(ir.acceptance_criteria) == 5
        assert ir.integration_items
        assert {endpoint.path for endpoint in ir.endpoints} >= {
            "/api/v1/auth/signup",
            "/api/v1/auth/magic-link",
            "/api/v1/quotations/:id/approve",
        }
        assert {integration.vendor for integration in ir.integrations} >= {"SendGrid", "Odoo"}
        assert ir.i18n.locales == ["en", "ar"]
        assert ir.i18n.rtl_locales == ["ar"]
        assert any(workflow.name == "Quotation Approval" for workflow in ir.workflows)

    def test_compile_product_ir_minimal_prd(self, tmp_path: Path) -> None:
        prd_path = _write_prd(tmp_path, MINIMAL_PRD)
        ir = compile_product_ir(prd_path)

        assert ir.project_name == "Minimal Portal"
        assert len(ir.entities) == 1
        assert len(ir.endpoints) == 3
        assert len(ir.acceptance_criteria) == 5

    def test_short_prd_does_not_crash(self, tmp_path: Path) -> None:
        prd_path = _write_prd(tmp_path, "# Tiny\n\nThis is intentionally short but still parsable.")
        ir = compile_product_ir(prd_path)

        assert ir.project_name == "Tiny"
        assert ir.acceptance_criteria == []
        assert ir.endpoints == []

    def test_route_param_id_does_not_trigger_indonesian_locale(self, tmp_path: Path) -> None:
        prd_path = _write_prd(
            tmp_path,
            """# Project: Route Params

## Feature F-001: Catalog
| GET | /api/v1/products/:id | JWT | - | ProductResponse |
""",
        )

        ir = compile_product_ir(prd_path)

        assert ir.i18n.locales == ["en"]

    def test_taskflow_prd_regression_extracts_entities_state_machine_and_rules(self) -> None:
        prd_path = Path(__file__).resolve().parents[1] / "v18 test runs" / "TASKFLOW_MINI_PRD.md"
        ir = compile_product_ir(prd_path)

        entity_names = {entity["name"] for entity in ir.entities}
        assert {"User", "Project", "Task", "Comment"} <= entity_names
        assert not any("LoginPage" in name for name in entity_names)

        assert ir.state_machines
        task_state_machine = next(sm for sm in ir.state_machines if sm["entity"] == "Task")
        assert any(
            transition["from_state"] == "todo" and transition["to_state"] == "in_progress"
            for transition in task_state_machine["transitions"]
        )

        assert ir.business_rules
        assert any(
            "Only project owners and admins can delete projects" in rule["description"]
            for rule in ir.business_rules
        )


class TestProductIRInference:
    def test_http_transcript_inference(self) -> None:
        assert _infer_verification_mode("The API returns 401 for invalid requests.") == "http_transcript"

    def test_playwright_trace_inference(self) -> None:
        assert _infer_verification_mode("The UI displays a success toast.") == "playwright_trace"

    def test_db_assertion_inference(self) -> None:
        assert _infer_verification_mode("The system saves the approval to the database.") == "db_assertion"

    def test_simulator_state_inference(self) -> None:
        assert _infer_verification_mode("The service sends email notification and push updates.") == "simulator_state"

    def test_default_code_span_inference(self) -> None:
        assert _infer_verification_mode("The handler validates the request payload.") == "code_span"


class TestProductIRIntegrations:
    def test_detects_stripe_from_strong_keyword(self) -> None:
        integrations = _detect_integrations("Stripe webhook receives payment_intent updates.")
        assert "Stripe" in {integration.vendor for integration in integrations}

    def test_detects_twilio_from_strong_keyword(self) -> None:
        integrations = _detect_integrations("Twilio handles SMS verification for login codes.")
        assert "Twilio" in {integration.vendor for integration in integrations}

    def test_detects_odoo_from_strong_keyword(self) -> None:
        integrations = _detect_integrations("Odoo search_read is used for invoice synchronization.")
        assert "Odoo" in {integration.vendor for integration in integrations}

    def test_generic_email_does_not_detect_sendgrid(self) -> None:
        integrations = _detect_integrations("The system sends email receipts to customers.")
        assert "SendGrid" not in {integration.vendor for integration in integrations}

    def test_explicit_sendgrid_detects_sendgrid(self) -> None:
        integrations = _detect_integrations("Outbound mail is sent through SendGrid templates.")
        assert "SendGrid" in {integration.vendor for integration in integrations}

    def test_generic_payment_webhook_does_not_detect_stripe_without_explicit_vendor(self) -> None:
        integrations = _detect_integrations("The system handles payment approval and inbound webhook retries.")
        assert "Stripe" not in {integration.vendor for integration in integrations}

    def test_generic_sms_verification_does_not_detect_twilio_without_explicit_vendor(self) -> None:
        integrations = _detect_integrations("SMS is used for MFA verification when required.")
        assert "Twilio" not in {integration.vendor for integration in integrations}

    def test_push_token_device_does_not_detect_firebase_without_explicit_vendor(self) -> None:
        integrations = _detect_integrations("PushToken stores device metadata for push notifications.")
        assert "Firebase" not in {integration.vendor for integration in integrations}

    def test_work_order_part_text_does_not_detect_odoo_from_erp_substring(self) -> None:
        integrations = _detect_integrations("WorkOrderPart is updated during inventory integration checks.")
        assert "Odoo" not in {integration.vendor for integration in integrations}

    def test_generic_provider_words_create_capability_not_vendor(self, tmp_path: Path) -> None:
        prd_path = _write_prd(
            tmp_path,
            """# Project: Notifications

## Feature F-001: Providers
Notification providers may be configured later for email, SMS, and push.
""",
        )
        ir = compile_product_ir(prd_path)

        assert not ir.integrations
        capability_names = {item.name for item in ir.integration_items if item.kind == "capability"}
        assert {"email_delivery", "sms_delivery", "push_notification"} <= capability_names

    def test_stack_extracts_azure_blob_storage_as_service_provider(self, tmp_path: Path) -> None:
        prd_path = _write_prd(
            tmp_path,
            """# Project: Storage

## Technology Stack
| Layer | Technology |
|-------|------------|
| Storage | Azure Blob Storage |
""",
        )
        ir = compile_product_ir(prd_path)

        item = next(item for item in ir.integration_items if item.name == "Azure Blob Storage")
        assert item.kind == "service_provider"
        assert item.implementation_mode == "real_sdk"
        assert item.port_name == "IFileStorageProvider"

    def test_stack_extracts_azure_notification_hubs_as_service_provider(self, tmp_path: Path) -> None:
        prd_path = _write_prd(
            tmp_path,
            """# Project: Notifications

## Technology Stack
| Layer | Technology |
|-------|------------|
| Notifications | Azure Notification Hubs |
""",
        )
        ir = compile_product_ir(prd_path)

        item = next(item for item in ir.integration_items if item.name == "Azure Notification Hubs")
        assert item.kind == "service_provider"
        assert item.implementation_mode == "real_sdk"
        assert item.port_name == "IPushNotificationProvider"

    def test_stack_extracts_redis_as_infra_dependency_not_adapter_candidate(self, tmp_path: Path) -> None:
        prd_path = _write_prd(
            tmp_path,
            """# Project: Cache

## Technology Stack
| Layer | Technology |
|-------|------------|
| Cache | Redis |
""",
        )
        ir = compile_product_ir(prd_path)

        item = next(item for item in ir.integration_items if item.name == "Redis")
        assert item.kind == "infra_dependency"
        assert item.implementation_mode == "infra_only"
        assert "Redis" not in {integration.vendor for integration in ir.integrations}

    def test_arkan_webhook_extracts_external_system_stubbed_adapter(self, tmp_path: Path) -> None:
        prd_path = _write_prd(
            tmp_path,
            """# Project: Arkan

## Technology Stack
| Layer | Technology |
|-------|------------|
| Storage | Azure Blob Storage |

## External Systems
- Arkan Handover webhook receiver (stubbed)

## Feature F-010: Integrations
POST /integrations/arkan/webhook
integration.arkan.handover_received
""",
        )
        ir = compile_product_ir(prd_path)

        arkan = next(item for item in ir.integration_items if item.vendor == "Arkan")
        assert arkan.kind == "external_system"
        assert arkan.status == "stubbed"
        assert arkan.implementation_mode == "adapter_stub"
        assert "Arkan" in {integration.vendor for integration in ir.integrations}

    def test_arkanpm_regression_fixture_filters_false_vendors(self, tmp_path: Path) -> None:
        prd_path = _write_prd(tmp_path, ARKANPM_FIXTURE_PATH.read_text(encoding="utf-8"))
        ir = compile_product_ir(prd_path)

        adapter_candidates = {integration.vendor for integration in ir.integrations}
        assert {"Arkan", "Azure Blob Storage", "Azure Notification Hubs"} <= adapter_candidates
        assert {"Stripe", "Twilio", "Firebase", "Odoo", "Redis"}.isdisjoint(adapter_candidates)

        kinds = {item.kind for item in ir.integration_items}
        assert "capability" in kinds
        assert "infra_dependency" in kinds

    def test_explicit_stack_provider_is_not_downgraded_by_later_heuristic_optional_text(self, tmp_path: Path) -> None:
        prd_path = _write_prd(
            tmp_path,
            """# Project: Storage

## Technology Stack
| Layer | Technology |
|-------|------------|
| Storage | Azure Blob Storage |

Azure Blob Storage may be configured later.
""",
        )
        ir = compile_product_ir(prd_path)

        item = next(item for item in ir.integration_items if item.vendor == "Azure Blob Storage")
        assert item.status == "required"
        assert "Azure Blob Storage" in {integration.vendor for integration in ir.integrations}

    def test_generic_vendor_reference_does_not_create_high_confidence_adapter_candidate(self, tmp_path: Path) -> None:
        prd_path = _write_prd(
            tmp_path,
            """# Project: Research

The design references Stripe-style checkout examples in competitor research.
""",
        )
        ir = compile_product_ir(prd_path)

        assert "Stripe" not in {integration.vendor for integration in ir.integrations}
        stripe_item = next(item for item in ir.integration_items if item.vendor == "Stripe")
        assert stripe_item.kind == "service_provider"
        assert not any(evidence.confidence == "high" for evidence in stripe_item.source_evidence)


class TestProductIRSerialization:
    def test_save_product_ir_writes_all_artifacts(self, tmp_path: Path) -> None:
        prd_path = _write_prd(tmp_path, EVS_PRD)
        ir = compile_product_ir(prd_path)
        out_dir = tmp_path / "product-ir"

        save_product_ir(ir, out_dir)

        product_ir_path = out_dir / "product.ir.json"
        compat_ir_path = out_dir / "IR.json"
        ac_path = out_dir / "acceptance-criteria.ir.json"
        integration_items_path = out_dir / "integration-items.ir.json"
        integrations_path = out_dir / "integrations.ir.json"
        milestones_path = out_dir / "milestones.ir.json"

        assert product_ir_path.is_file()
        assert compat_ir_path.is_file()
        assert ac_path.is_file()
        assert integration_items_path.is_file()
        assert integrations_path.is_file()
        assert milestones_path.is_file()

        product_data = json.loads(product_ir_path.read_text(encoding="utf-8"))
        compat_data = json.loads(compat_ir_path.read_text(encoding="utf-8"))
        integration_items_data = json.loads(integration_items_path.read_text(encoding="utf-8"))
        milestone_data = json.loads(milestones_path.read_text(encoding="utf-8"))

        assert compat_data == product_data
        assert product_data["schema_version"] == 2
        assert product_data["project_name"] == "EVS Customer Portal"
        assert product_data["integration_items"] == integration_items_data
        by_feature = {item["feature"]: item for item in milestone_data}
        assert "F-003" in by_feature
        assert "AC-3" in by_feature["F-003"]["acs"]
        assert {"method": "POST", "path": "/api/v1/quotations/:id/approve"} in by_feature["F-003"]["endpoints"]

    def test_save_product_ir_writes_integration_items_artifact(self, tmp_path: Path) -> None:
        prd_path = _write_prd(tmp_path, ARKANPM_FIXTURE_PATH.read_text(encoding="utf-8"))
        ir = compile_product_ir(prd_path)
        out_dir = tmp_path / "product-ir"

        save_product_ir(ir, out_dir)

        integration_items = json.loads((out_dir / "integration-items.ir.json").read_text(encoding="utf-8"))
        names = {item["name"] for item in integration_items}
        assert "Arkan Handover" in names
        assert "Redis" in names

    def test_legacy_integrations_artifact_only_contains_adapter_candidates(self, tmp_path: Path) -> None:
        prd_path = _write_prd(tmp_path, ARKANPM_FIXTURE_PATH.read_text(encoding="utf-8"))
        ir = compile_product_ir(prd_path)
        out_dir = tmp_path / "product-ir"

        save_product_ir(ir, out_dir)

        integrations = json.loads((out_dir / "integrations.ir.json").read_text(encoding="utf-8"))
        vendors = {item["vendor"] for item in integrations}
        assert {"Arkan", "Azure Blob Storage", "Azure Notification Hubs"} <= vendors
        assert {"Stripe", "Twilio", "Firebase", "Odoo", "Redis"}.isdisjoint(vendors)

    def test_cli_loader_accepts_compat_ir_alias(self, tmp_path: Path) -> None:
        product_ir_dir = tmp_path / ".agent-team" / "product-ir"
        product_ir_dir.mkdir(parents=True, exist_ok=True)
        (product_ir_dir / "IR.json").write_text(json.dumps({"project_name": "Compat"}), encoding="utf-8")

        loaded = _load_product_ir(str(tmp_path))

        assert loaded["project_name"] == "Compat"

    def test_format_ir_summary_groups_integrations_by_kind(self, tmp_path: Path) -> None:
        prd_path = _write_prd(tmp_path, EVS_PRD)
        ir = compile_product_ir(prd_path)

        summary = format_ir_summary(ir)

        assert "[PRODUCT IR SUMMARY]" in summary
        assert "Stack: NestJS + Next.js + PostgreSQL" in summary
        assert "Acceptance Criteria: 5" in summary
        assert "External Systems: Odoo" in summary
        assert "Provider Services: SendGrid" in summary
        assert "Capabilities:" in summary
        assert "Infra Dependencies: PostgreSQL" in summary
        assert "Adapter Candidates: Odoo, SendGrid" in summary
