"""Tests for Prisma schema validator."""
from __future__ import annotations

import pytest
from pathlib import Path

from agent_team_v15.schema_validator import (
    SchemaFinding,
    SchemaValidationReport,
    ParsedSchema,
    PrismaModel,
    PrismaField,
    parse_prisma_schema,
    check_missing_cascades,
    check_missing_relations,
    check_invalid_defaults,
    check_missing_indexes,
    check_type_consistency,
    check_soft_delete_filters,
    check_tenant_isolation,
    check_pseudo_enums,
    check_tenant_unique_constraints,
    validate_schema,
    validate_prisma_schema,
    get_schema_models,
    run_schema_validation,
    format_findings_report,
    _pascal_to_kebab,
)


# ===================================================================
# Helpers
# ===================================================================

def _write_file(base: Path, relative: str, content: str) -> Path:
    """Create a file under *base* and return its Path."""
    p = base / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ===================================================================
# Parser Tests
# ===================================================================

class TestPrismaParser:
    def test_parse_simple_model(self):
        schema = parse_prisma_schema("""
model User {
  id    String @id @default(uuid())
  name  String
  email String @unique
}
""")
        assert "User" in schema.models
        assert len(schema.models["User"].fields) == 3

    def test_parse_field_types(self):
        schema = parse_prisma_schema("""
model Item {
  id         String   @id
  count      Int
  price      Decimal  @db.Decimal(18, 4)
  is_active  Boolean
  created_at DateTime @default(now())
}
""")
        model = schema.models["Item"]
        field_types = {f.name: f.type for f in model.fields}
        assert field_types["count"] == "Int"
        assert field_types["price"] == "Decimal"
        assert field_types["is_active"] == "Boolean"

    def test_parse_relation_field(self):
        schema = parse_prisma_schema("""
model Asset {
  id   String @id
  name String
}

model AssetDocument {
  id       String @id
  asset_id String
  asset    Asset  @relation(fields: [asset_id], references: [id])
}
""")
        doc_model = schema.models["AssetDocument"]
        asset_field = next(f for f in doc_model.fields if f.name == "asset")
        assert asset_field.is_relation is True
        assert asset_field.has_relation_attr is True

    def test_parse_indexes(self):
        schema = parse_prisma_schema("""
model WorkOrder {
  id        String @id
  tenant_id String
  status    String

  @@index([tenant_id])
  @@index([status])
}
""")
        model = schema.models["WorkOrder"]
        assert "tenant_id" in model.indexes
        assert "status" in model.indexes

    def test_parse_enum(self):
        schema = parse_prisma_schema("""
enum Status {
  ACTIVE
  INACTIVE
  DELETED
}
""")
        assert "Status" in schema.enums
        assert "ACTIVE" in schema.enums["Status"].values
        assert len(schema.enums["Status"].values) == 3

    def test_parse_optional_field(self):
        schema = parse_prisma_schema("""
model Lease {
  id              String  @id
  renewed_from_id String?
}
""")
        f = next(f for f in schema.models["Lease"].fields if f.name == "renewed_from_id")
        assert f.is_optional is True

    def test_parse_deleted_at_detection(self):
        schema = parse_prisma_schema("""
model SoftModel {
  id         String    @id
  deleted_at DateTime?
}

model HardModel {
  id String @id
}
""")
        assert schema.models["SoftModel"].has_deleted_at is True
        assert schema.models["HardModel"].has_deleted_at is False

    def test_parse_unique_constraints(self):
        schema = parse_prisma_schema("""
model NotificationPref {
  id        String @id
  tenant_id String
  user_id   String
  event     String

  @@unique([tenant_id, user_id, event])
}
""")
        model = schema.models["NotificationPref"]
        assert "tenant_id" in model.unique_constraints
        assert "user_id" in model.unique_constraints


# ===================================================================
# SCHEMA-001: Missing onDelete Cascade
# ===================================================================

class TestCheckMissingCascades:
    def test_detects_missing_cascade(self):
        schema = parse_prisma_schema("""
model Asset {
  id   String @id
  docs AssetDocument[]
}

model AssetDocument {
  id       String @id
  asset_id String
  asset    Asset  @relation(fields: [asset_id], references: [id])
}
""")
        findings = check_missing_cascades(schema)
        assert len(findings) == 1
        assert findings[0].check == "SCHEMA-001"
        assert findings[0].model == "AssetDocument"
        assert findings[0].severity == "critical"

    def test_no_finding_when_cascade_present(self):
        schema = parse_prisma_schema("""
model Asset {
  id   String @id
  docs AssetDocument[]
}

model AssetDocument {
  id       String @id
  asset_id String
  asset    Asset  @relation(fields: [asset_id], references: [id], onDelete: Cascade)
}
""")
        findings = check_missing_cascades(schema)
        assert len(findings) == 0

    def test_no_finding_when_set_null(self):
        schema = parse_prisma_schema("""
model User {
  id    String @id
  posts Post[]
}

model Post {
  id        String @id
  author_id String?
  author    User?  @relation(fields: [author_id], references: [id], onDelete: SetNull)
}
""")
        findings = check_missing_cascades(schema)
        assert len(findings) == 0

    def test_detects_multiple_missing_cascades(self):
        schema = parse_prisma_schema("""
model WorkOrder {
  id          String @id
  assignments WorkOrderAssignment[]
  costs       WorkOrderCost[]
}

model WorkOrderAssignment {
  id            String    @id
  work_order_id String
  work_order    WorkOrder @relation(fields: [work_order_id], references: [id])
}

model WorkOrderCost {
  id            String    @id
  work_order_id String
  work_order    WorkOrder @relation(fields: [work_order_id], references: [id])
}
""")
        findings = check_missing_cascades(schema)
        assert len(findings) == 2
        models = {f.model for f in findings}
        assert "WorkOrderAssignment" in models
        assert "WorkOrderCost" in models

    def test_ignores_relation_without_fields(self):
        """Relation list fields (the parent side) should not trigger."""
        schema = parse_prisma_schema("""
model Asset {
  id   String           @id
  docs AssetDocument[]
}

model AssetDocument {
  id       String @id
  asset_id String
  asset    Asset  @relation(fields: [asset_id], references: [id], onDelete: Cascade)
}
""")
        findings = check_missing_cascades(schema)
        assert len(findings) == 0

    def test_finding_has_correct_line_number(self):
        schema_text = """model Parent {
  id       String  @id
  children Child[]
}

model Child {
  id        String @id
  parent_id String
  parent    Parent @relation(fields: [parent_id], references: [id])
}
"""
        schema = parse_prisma_schema(schema_text)
        findings = check_missing_cascades(schema)
        assert len(findings) == 1
        # Line 9 is "parent Parent @relation(...)"
        assert findings[0].line == 9


# ===================================================================
# SCHEMA-002: Missing @relation on FK Field
# ===================================================================

class TestCheckMissingRelations:
    def test_detects_bare_fk_field(self):
        schema = parse_prisma_schema("""
model WorkRequest {
  id           String @id
  requester_id String
  building_id  String
}
""")
        findings = check_missing_relations(schema)
        assert len(findings) == 2
        field_names = {f.field for f in findings}
        assert "requester_id" in field_names
        assert "building_id" in field_names

    def test_no_finding_when_relation_exists(self):
        schema = parse_prisma_schema("""
model Building {
  id    String @id
  units Unit[]
}

model Unit {
  id          String   @id
  building_id String
  building    Building @relation(fields: [building_id], references: [id], onDelete: Cascade)
}
""")
        findings = check_missing_relations(schema)
        assert len(findings) == 0

    def test_ignores_id_field(self):
        schema = parse_prisma_schema("""
model User {
  id String @id
}
""")
        findings = check_missing_relations(schema)
        assert len(findings) == 0

    def test_ignores_exception_fields(self):
        schema = parse_prisma_schema("""
model Payment {
  id          String @id
  external_id String
  stripe_id   String
  session_id  String
}
""")
        findings = check_missing_relations(schema)
        assert len(findings) == 0

    def test_detects_self_referential_fk(self):
        schema = parse_prisma_schema("""
model Lease {
  id              String  @id
  renewed_from_id String?
}
""")
        findings = check_missing_relations(schema)
        assert len(findings) == 1
        assert findings[0].field == "renewed_from_id"
        assert findings[0].check == "SCHEMA-002"

    def test_multiple_bare_fks_in_one_model(self):
        schema = parse_prisma_schema("""
model WorkRequest {
  id              String  @id
  requester_id    String
  building_id     String
  floor_id        String?
  unit_id         String?
  asset_id        String?
  converted_wo_id String?
}
""")
        findings = check_missing_relations(schema)
        assert len(findings) == 6


# ===================================================================
# SCHEMA-003: Invalid Default Value on FK Field
# ===================================================================

class TestCheckInvalidDefaults:
    def test_detects_empty_string_default_on_fk(self):
        schema = parse_prisma_schema("""
model WarrantyClaim {
  id          String @id
  warranty_id String @default("")
}
""")
        findings = check_invalid_defaults(schema)
        assert len(findings) == 1
        assert findings[0].check == "SCHEMA-003"
        assert findings[0].severity == "critical"
        assert findings[0].field == "warranty_id"

    def test_no_finding_on_valid_default(self):
        schema = parse_prisma_schema("""
model User {
  id   String @id @default(uuid())
  name String @default("Unknown")
}
""")
        findings = check_invalid_defaults(schema)
        assert len(findings) == 0

    def test_no_finding_on_nullable_fk(self):
        schema = parse_prisma_schema("""
model WarrantyClaim {
  id          String  @id
  warranty_id String?
}
""")
        findings = check_invalid_defaults(schema)
        assert len(findings) == 0

    def test_detects_empty_string_on_uuid_field(self):
        schema = parse_prisma_schema("""
model Record {
  id       String @id
  ref_uuid String @default("") @db.Uuid
}
""")
        findings = check_invalid_defaults(schema)
        assert len(findings) == 1
        assert findings[0].check == "SCHEMA-003"

    def test_no_finding_on_normal_string_default(self):
        schema = parse_prisma_schema("""
model Setting {
  id       String @id
  currency String @default("USD")
  status   String @default("active")
}
""")
        findings = check_invalid_defaults(schema)
        assert len(findings) == 0

    def test_multiple_invalid_defaults(self):
        schema = parse_prisma_schema("""
model Broken {
  id          String @id
  parent_id   String @default("")
  category_id String @default("")
}
""")
        findings = check_invalid_defaults(schema)
        assert len(findings) == 2


# ===================================================================
# SCHEMA-004: Missing Database Index
# ===================================================================

class TestCheckMissingIndexes:
    def test_detects_missing_fk_index(self):
        schema = parse_prisma_schema("""
model WorkOrder {
  id        String @id
  asset_id  String
  tenant_id String
}
""")
        findings = check_missing_indexes(schema)
        fk_findings = [f for f in findings if f.field == "asset_id"]
        assert len(fk_findings) == 1
        assert fk_findings[0].check == "SCHEMA-004"

    def test_no_finding_when_index_exists(self):
        schema = parse_prisma_schema("""
model WorkOrder {
  id       String @id
  asset_id String

  @@index([asset_id])
}
""")
        findings = check_missing_indexes(schema)
        fk_findings = [f for f in findings if f.field == "asset_id"]
        assert len(fk_findings) == 0

    def test_no_finding_when_unique_exists(self):
        schema = parse_prisma_schema("""
model UserEmail {
  id    String @id
  email String @unique
}
""")
        findings = check_missing_indexes(schema)
        email_findings = [f for f in findings if f.field == "email"]
        assert len(email_findings) == 0

    def test_detects_missing_tenant_id_index(self):
        schema = parse_prisma_schema("""
model Asset {
  id        String @id
  tenant_id String
}
""")
        findings = check_missing_indexes(schema)
        tenant_findings = [f for f in findings if f.field == "tenant_id"]
        assert len(tenant_findings) == 1

    def test_detects_missing_deleted_at_index(self):
        schema = parse_prisma_schema("""
model Asset {
  id         String    @id
  deleted_at DateTime?
}
""")
        findings = check_missing_indexes(schema)
        del_findings = [f for f in findings if f.field == "deleted_at"]
        assert len(del_findings) == 1

    def test_no_finding_on_id_field(self):
        """The primary key id field should not trigger."""
        schema = parse_prisma_schema("""
model User {
  id String @id @default(uuid())
}
""")
        findings = check_missing_indexes(schema)
        assert len(findings) == 0

    def test_composite_index_covers_field(self):
        schema = parse_prisma_schema("""
model MeterReading {
  id           String   @id
  unit_id      String
  reading_date DateTime

  @@index([unit_id, reading_date])
}
""")
        findings = check_missing_indexes(schema)
        unit_findings = [f for f in findings if f.field == "unit_id"]
        assert len(unit_findings) == 0


# ===================================================================
# SCHEMA-005: Type/Precision Inconsistency
# ===================================================================

class TestCheckTypeConsistency:
    def test_detects_bigint_vs_int_inconsistency(self):
        schema = parse_prisma_schema("""
model AssetDocument {
  id        String @id
  file_size Int
}

model LeaseDocument {
  id        String @id
  file_size BigInt
}
""")
        findings = check_type_consistency(schema)
        assert len(findings) >= 1
        assert all(f.check == "SCHEMA-005" for f in findings)

    def test_no_finding_when_types_consistent(self):
        schema = parse_prisma_schema("""
model AssetDocument {
  id        String @id
  file_size Int
}

model LeaseDocument {
  id        String @id
  file_size Int
}
""")
        findings = check_type_consistency(schema)
        size_findings = [f for f in findings if "size" in f.field.lower()]
        assert len(size_findings) == 0

    def test_detects_decimal_precision_inconsistency(self):
        schema = parse_prisma_schema("""
model Invoice {
  id     String  @id
  amount Decimal @db.Decimal(18, 4)
}

model Payment {
  id     String  @id
  amount Decimal @db.Decimal(5, 2)
}
""")
        findings = check_type_consistency(schema)
        financial_findings = [f for f in findings if "amount" in f.field]
        assert len(financial_findings) >= 1

    def test_no_finding_single_size_field(self):
        schema = parse_prisma_schema("""
model Doc {
  id        String @id
  file_size Int
}
""")
        findings = check_type_consistency(schema)
        assert len(findings) == 0

    def test_no_finding_consistent_decimals(self):
        schema = parse_prisma_schema("""
model Invoice {
  id     String  @id
  amount Decimal @db.Decimal(18, 4)
}

model Payment {
  id    String  @id
  total Decimal @db.Decimal(18, 4)
}
""")
        findings = check_type_consistency(schema)
        financial_findings = [f for f in findings if f.check == "SCHEMA-005"
                              and ("amount" in f.field or "total" in f.field)]
        assert len(financial_findings) == 0

    def test_detects_mixed_score_precisions(self):
        schema = parse_prisma_schema("""
model VendorScore {
  id            String  @id
  quality_rate  Decimal @db.Decimal(5, 2)
  delivery_rate Decimal @db.Decimal(5, 4)
}
""")
        findings = check_type_consistency(schema)
        rate_findings = [f for f in findings if "rate" in f.field]
        assert len(rate_findings) >= 1


# ===================================================================
# SCHEMA-006: Soft-Delete Without Filter in Service
# ===================================================================

class TestCheckSoftDeleteFilters:
    def test_detects_missing_filter(self, tmp_path):
        schema = parse_prisma_schema("""
model WorkRequest {
  id         String    @id
  deleted_at DateTime?
}
""")
        _write_file(tmp_path, "work-request.service.ts", """
export class WorkRequestService {
  async findAll() {
    return this.prisma.workRequest.findMany({
      where: { status: 'open' }
    });
  }
}
""")
        findings = check_soft_delete_filters(schema, tmp_path)
        assert len(findings) == 1
        assert findings[0].check == "SCHEMA-006"
        assert findings[0].model == "WorkRequest"

    def test_no_finding_when_filter_present(self, tmp_path):
        schema = parse_prisma_schema("""
model WorkRequest {
  id         String    @id
  deleted_at DateTime?
}
""")
        _write_file(tmp_path, "work-request.service.ts", """
export class WorkRequestService {
  async findAll() {
    return this.prisma.workRequest.findMany({
      where: { deleted_at: null, status: 'open' }
    });
  }
}
""")
        findings = check_soft_delete_filters(schema, tmp_path)
        assert len(findings) == 0

    def test_no_finding_when_no_service_file(self, tmp_path):
        schema = parse_prisma_schema("""
model WorkRequest {
  id         String    @id
  deleted_at DateTime?
}
""")
        # No service file created
        findings = check_soft_delete_filters(schema, tmp_path)
        assert len(findings) == 0

    def test_no_finding_when_model_lacks_deleted_at(self, tmp_path):
        schema = parse_prisma_schema("""
model StockLevel {
  id       String @id
  quantity Int
}
""")
        _write_file(tmp_path, "stock-level.service.ts", """
export class StockLevelService {
  async findAll() {
    return this.prisma.stockLevel.findMany();
  }
}
""")
        findings = check_soft_delete_filters(schema, tmp_path)
        assert len(findings) == 0

    def test_no_finding_when_no_service_dir(self):
        schema = parse_prisma_schema("""
model WorkRequest {
  id         String    @id
  deleted_at DateTime?
}
""")
        findings = check_soft_delete_filters(schema, None)
        assert len(findings) == 0

    def test_detects_multiple_models_missing_filter(self, tmp_path):
        schema = parse_prisma_schema("""
model Announcement {
  id         String    @id
  deleted_at DateTime?
}

model Defect {
  id         String    @id
  deleted_at DateTime?
}
""")
        _write_file(tmp_path, "announcement.service.ts", """
export class AnnouncementService {
  findAll() { return this.prisma.announcement.findMany(); }
}
""")
        _write_file(tmp_path, "defect.service.ts", """
export class DefectService {
  findAll() { return this.prisma.defect.findMany({ where: { status: 'open' } }); }
}
""")
        findings = check_soft_delete_filters(schema, tmp_path)
        assert len(findings) == 2


# ===================================================================
# SCHEMA-007: Missing Tenant Isolation
# ===================================================================

class TestCheckTenantIsolation:
    def test_detects_missing_tenant_id(self):
        schema = parse_prisma_schema("""
model Tenant {
  id   String @id
  name String
}

model Building {
  id   String @id
  name String
  addr String
  city String
}
""")
        findings = check_tenant_isolation(schema)
        assert len(findings) == 1
        assert findings[0].check == "SCHEMA-007"
        assert findings[0].model == "Building"

    def test_no_finding_when_tenant_id_present(self):
        schema = parse_prisma_schema("""
model Tenant {
  id   String @id
  name String
}

model Building {
  id        String @id
  tenant_id String
  name      String
  addr      String
}
""")
        findings = check_tenant_isolation(schema)
        assert len(findings) == 0

    def test_detects_nullable_tenant_id(self):
        schema = parse_prisma_schema("""
model Tenant {
  id   String @id
  name String
}

model NotificationTemplate {
  id        String  @id
  tenant_id String?
  title     String
  body      String
}
""")
        findings = check_tenant_isolation(schema)
        assert len(findings) == 1
        assert "nullable" in findings[0].message.lower()

    def test_no_finding_without_tenant_model(self):
        """If no Tenant model exists, skip tenant isolation checks."""
        schema = parse_prisma_schema("""
model Building {
  id   String @id
  name String
  addr String
  city String
}
""")
        findings = check_tenant_isolation(schema)
        assert len(findings) == 0

    def test_skips_global_models(self):
        schema = parse_prisma_schema("""
model Tenant {
  id   String @id
  name String
}

model User {
  id    String @id
  name  String
  email String
  role  String
}

model Role {
  id   String @id
  name String
  code String
  perm String
}
""")
        findings = check_tenant_isolation(schema)
        models_flagged = {f.model for f in findings}
        assert "User" not in models_flagged
        assert "Role" not in models_flagged

    def test_skips_small_join_tables(self):
        """Models with fewer than 4 fields are likely join tables."""
        schema = parse_prisma_schema("""
model Tenant {
  id   String @id
  name String
}

model UserRole {
  user_id String
  role_id String
}
""")
        findings = check_tenant_isolation(schema)
        models_flagged = {f.model for f in findings}
        assert "UserRole" not in models_flagged


# ===================================================================
# SCHEMA-008: Magic String Pseudo-Enum
# ===================================================================

class TestCheckPseudoEnums:
    def test_detects_pseudo_enum_with_comment(self):
        schema = parse_prisma_schema(
            'model Asset {\n'
            '  id        String @id\n'
            '  condition String @default("good") // excellent, good, fair, poor, critical\n'
            '}\n'
        )
        findings = check_pseudo_enums(schema)
        assert len(findings) == 1
        assert findings[0].check == "SCHEMA-008"
        assert findings[0].field == "condition"
        assert findings[0].model == "Asset"

    def test_detects_status_pseudo_enum(self):
        schema = parse_prisma_schema(
            'model Tenant {\n'
            '  id     String @id\n'
            '  status String @default("provisioning") // provisioning, active, suspended, terminated, archived\n'
            '}\n'
        )
        findings = check_pseudo_enums(schema)
        assert len(findings) == 1
        assert "status" in findings[0].field

    def test_no_finding_without_comment(self):
        schema = parse_prisma_schema("""
model Setting {
  id       String @id
  currency String @default("USD")
}
""")
        findings = check_pseudo_enums(schema)
        assert len(findings) == 0

    def test_no_finding_on_non_string_field(self):
        schema = parse_prisma_schema(
            'model Item {\n'
            '  id    String @id\n'
            '  count Int    @default(0) // 0, 1, 2, 3\n'
            '}\n'
        )
        findings = check_pseudo_enums(schema)
        assert len(findings) == 0

    def test_no_finding_on_two_value_comment(self):
        """Two values is too few to be an enum pattern."""
        schema = parse_prisma_schema(
            'model Feature {\n'
            '  id      String @id\n'
            '  enabled String @default("yes") // yes, no\n'
            '}\n'
        )
        findings = check_pseudo_enums(schema)
        assert len(findings) == 0

    def test_detects_multiple_pseudo_enums(self):
        schema = parse_prisma_schema(
            'model WorkOrder {\n'
            '  id       String @id\n'
            '  status   String @default("open") // open, in_progress, completed, closed\n'
            '  priority String @default("medium") // low, medium, high, urgent\n'
            '  type     String @default("corrective") // corrective, preventive, predictive, emergency\n'
            '}\n'
        )
        findings = check_pseudo_enums(schema)
        assert len(findings) == 3

    def test_no_finding_without_default(self):
        schema = parse_prisma_schema(
            'model Item {\n'
            '  id   String @id\n'
            '  type String // foo, bar, baz\n'
            '}\n'
        )
        findings = check_pseudo_enums(schema)
        assert len(findings) == 0


# ===================================================================
# Integration: validate_schema
# ===================================================================

class TestValidateSchema:
    def test_returns_sorted_findings(self):
        schema_content = """
model Tenant {
  id   String @id
  name String
}

model WarrantyClaim {
  id          String @id
  warranty_id String @default("")
  name        String
  desc        String
}
"""
        findings = validate_schema(schema_content)
        # Should have SCHEMA-003 (critical) and SCHEMA-007 + SCHEMA-004 + SCHEMA-002
        assert len(findings) >= 1
        # Critical findings should come first
        severities = [f.severity for f in findings]
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        orders = [severity_order[s] for s in severities]
        assert orders == sorted(orders)

    def test_empty_schema_returns_no_findings(self):
        findings = validate_schema("")
        assert findings == []

    def test_clean_schema_returns_no_findings(self):
        schema_content = """
model User {
  id   String @id @default(uuid())
  name String
}
"""
        findings = validate_schema(schema_content)
        assert findings == []


# ===================================================================
# Integration: run_schema_validation (project-level)
# ===================================================================

class TestRunSchemaValidation:
    def test_finds_schema_prisma_file(self, tmp_path):
        _write_file(tmp_path, "prisma/schema.prisma", """
model Broken {
  id          String @id
  warranty_id String @default("")
}
""")
        findings = run_schema_validation(tmp_path)
        assert len(findings) >= 1

    def test_returns_schema_000_when_no_schema(self, tmp_path):
        _write_file(tmp_path, "src/index.ts", "console.log('hello');")
        findings = run_schema_validation(tmp_path)
        assert len(findings) == 1
        assert findings[0].check == "SCHEMA-000"

    def test_skips_node_modules(self, tmp_path):
        _write_file(tmp_path, "node_modules/prisma/schema.prisma", """
model Broken {
  id          String @id
  warranty_id String @default("")
}
""")
        findings = run_schema_validation(tmp_path)
        # Only SCHEMA-000 (no schema found) — the node_modules one is skipped
        assert len(findings) == 1
        assert findings[0].check == "SCHEMA-000"


# ===================================================================
# SCHEMA-010: Multi-Tenant Missing @@unique with tenant_id
# ===================================================================

class TestCheckTenantUniqueConstraints:
    def test_detects_unique_without_tenant_id(self):
        schema = parse_prisma_schema("""
model Tenant {
  id   String @id
  name String
}

model NotificationPref {
  id        String @id
  tenant_id String
  user_id   String
  event     String

  @@unique([user_id, event])
}
""")
        findings = check_tenant_unique_constraints(schema)
        assert len(findings) == 1
        assert findings[0].check == "SCHEMA-010"
        assert findings[0].model == "NotificationPref"

    def test_no_finding_when_unique_includes_tenant(self):
        schema = parse_prisma_schema("""
model Tenant {
  id   String @id
  name String
}

model NotificationPref {
  id        String @id
  tenant_id String
  user_id   String
  event     String

  @@unique([tenant_id, user_id, event])
}
""")
        findings = check_tenant_unique_constraints(schema)
        assert len(findings) == 0

    def test_no_finding_without_unique_constraint(self):
        schema = parse_prisma_schema("""
model Tenant {
  id   String @id
  name String
}

model Building {
  id        String @id
  tenant_id String
  name      String
}
""")
        findings = check_tenant_unique_constraints(schema)
        assert len(findings) == 0

    def test_no_finding_without_tenant_model(self):
        schema = parse_prisma_schema("""
model Item {
  id   String @id
  code String

  @@unique([code])
}
""")
        findings = check_tenant_unique_constraints(schema)
        assert len(findings) == 0

    def test_no_finding_model_without_tenant_id(self):
        schema = parse_prisma_schema("""
model Tenant {
  id   String @id
  name String
}

model GlobalConfig {
  id  String @id
  key String

  @@unique([key])
}
""")
        findings = check_tenant_unique_constraints(schema)
        assert len(findings) == 0


# ===================================================================
# validate_prisma_schema (SchemaValidationReport)
# ===================================================================

class TestValidatePrismaSchema:
    def test_returns_report_with_counts(self, tmp_path):
        _write_file(tmp_path, "prisma/schema.prisma", """
model Asset {
  id   String @id
  docs AssetDocument[]
}

model AssetDocument {
  id       String @id
  asset_id String
  asset    Asset  @relation(fields: [asset_id], references: [id])
}
""")
        report = validate_prisma_schema(tmp_path)
        assert isinstance(report, SchemaValidationReport)
        assert report.models_checked == 2
        assert report.relations_checked >= 1

    def test_passed_false_when_critical_findings(self, tmp_path):
        _write_file(tmp_path, "prisma/schema.prisma", """
model Broken {
  id          String @id
  warranty_id String @default("")
}
""")
        report = validate_prisma_schema(tmp_path)
        assert report.passed is False

    def test_passed_true_when_clean(self, tmp_path):
        _write_file(tmp_path, "prisma/schema.prisma", """
model User {
  id   String @id @default(uuid())
  name String
}
""")
        report = validate_prisma_schema(tmp_path)
        assert report.passed is True

    def test_schema_000_when_no_file(self, tmp_path):
        report = validate_prisma_schema(tmp_path)
        assert report.models_checked == 0
        assert len(report.violations) == 1
        assert report.violations[0].check == "SCHEMA-000"


# ===================================================================
# get_schema_models
# ===================================================================

class TestGetSchemaModels:
    def test_returns_model_dict(self, tmp_path):
        _write_file(tmp_path, "prisma/schema.prisma", """
model User {
  id   String @id
  name String
}

model Post {
  id    String @id
  title String
}
""")
        models = get_schema_models(tmp_path)
        assert "User" in models
        assert "Post" in models
        assert len(models["User"].fields) == 2

    def test_returns_empty_when_no_schema(self, tmp_path):
        models = get_schema_models(tmp_path)
        assert models == {}


# ===================================================================
# Suggestion field
# ===================================================================

class TestSuggestionField:
    def test_cascade_finding_has_suggestion(self):
        schema = parse_prisma_schema("""
model Parent {
  id       String  @id
  children Child[]
}

model Child {
  id        String @id
  parent_id String
  parent    Parent @relation(fields: [parent_id], references: [id])
}
""")
        findings = check_missing_cascades(schema)
        assert len(findings) == 1
        assert "onDelete" in findings[0].suggestion

    def test_bare_fk_finding_has_suggestion(self):
        schema = parse_prisma_schema("""
model Item {
  id          String @id
  building_id String
}
""")
        findings = check_missing_relations(schema)
        assert len(findings) == 1
        assert "@relation" in findings[0].suggestion

    def test_default_suggestion_is_empty(self):
        """SchemaFinding defaults to empty suggestion."""
        f = SchemaFinding(
            check="TEST", severity="low", message="test",
            model="M", field="f", line=1,
        )
        assert f.suggestion == ""


# ===================================================================
# format_findings_report
# ===================================================================

class TestFormatReport:
    def test_empty_findings(self):
        report = format_findings_report([])
        assert "No schema issues found" in report

    def test_report_contains_check_codes(self):
        findings = [
            SchemaFinding(
                check="SCHEMA-001",
                severity="critical",
                message="Missing cascade",
                model="AssetDoc",
                field="asset",
                line=10,
            ),
        ]
        report = format_findings_report(findings)
        assert "SCHEMA-001" in report
        assert "Missing onDelete Cascade" in report
        assert "AssetDoc" in report


# ===================================================================
# Helper: _pascal_to_kebab
# ===================================================================

class TestPascalToKebab:
    def test_simple_case(self):
        assert _pascal_to_kebab("WorkOrder") == "work-order"

    def test_single_word(self):
        assert _pascal_to_kebab("Asset") == "asset"

    def test_three_words(self):
        assert _pascal_to_kebab("WorkOrderAssignment") == "work-order-assignment"

    def test_acronym_in_name(self):
        assert _pascal_to_kebab("SLATimer") == "s-l-a-timer"
