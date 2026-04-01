"""Prisma schema validator for Agent Team.

Parses Prisma schema files and checks for common issues:
missing cascades, bare FK fields, invalid defaults, missing indexes,
type inconsistencies, soft-delete gaps, and tenant isolation gaps.

All checks are regex-based, require no external dependencies (stdlib only),
and are designed to run as part of the post-orchestration verification pipeline.

Typical usage::

    from pathlib import Path
    from agent_team_v15.schema_validator import run_schema_validation

    findings = run_schema_validation(Path("/path/to/project"))
    for f in findings:
        print(f"[{f.check}] {f.severity}: {f.message} ({f.model}.{f.field} line {f.line})")
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SchemaFinding:
    """A single schema issue detected during validation."""

    check: str       # e.g. "SCHEMA-001", "SCHEMA-002"
    severity: str    # "critical", "high", "medium", "low"
    message: str
    model: str       # Prisma model name
    field: str       # Field name (if applicable)
    line: int        # Line number in schema file
    suggestion: str = ""  # Actionable fix suggestion


@dataclass
class SchemaValidationReport:
    """Aggregate result of schema validation."""

    violations: list[SchemaFinding]
    models_checked: int
    relations_checked: int
    passed: bool     # True if zero error/critical-severity violations


@dataclass
class PrismaField:
    """A parsed field from a Prisma model."""

    name: str
    type: str
    modifiers: str        # everything after the type on the same line
    line_number: int
    is_relation: bool     # True if a relation object field (type is another model)
    is_optional: bool
    has_default: bool
    default_value: str    # raw default value string
    has_relation_attr: bool   # True if @relation(...) is present
    has_unique: bool
    raw_line: str


@dataclass
class PrismaModel:
    """A parsed Prisma model."""

    name: str
    fields: list[PrismaField]
    indexes: list[str]        # field names from @@index directives
    unique_constraints: list[str]  # field names from @@unique directives
    start_line: int
    end_line: int
    has_deleted_at: bool


@dataclass
class PrismaEnum:
    """A parsed Prisma enum."""

    name: str
    values: list[str]
    start_line: int


@dataclass
class ParsedSchema:
    """Complete parsed representation of a Prisma schema."""

    models: dict[str, PrismaModel]
    enums: dict[str, PrismaEnum]
    raw_lines: list[str]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_FINDINGS = 500

EXCLUDED_DIRS: frozenset[str] = frozenset({
    ".venv", "venv", "node_modules", "__pycache__", ".git",
    "dist", "build", "vendor", ".next",
})

# Fields that commonly need indexes
_INDEX_CANDIDATE_SUFFIXES = ("_id",)
_INDEX_CANDIDATE_NAMES = frozenset({
    "tenant_id", "deleted_at", "status", "created_at", "email",
})

# Common FK field suffix
_FK_SUFFIX = "_id"

# Fields that should NOT be treated as FK fields even if they end in _id
_FK_EXCEPTIONS = frozenset({
    "id", "external_id", "stripe_id", "plaid_id", "device_id",
    "tracking_id", "transaction_id", "reference_id", "correlation_id",
    "session_id", "request_id",
})

# Financial field name patterns
_FINANCIAL_FIELD_PATTERNS = re.compile(
    r"(amount|price|cost|rate|fee|balance|total|subtotal|tax|discount|"
    r"payment|charge|revenue|profit|income|expense|salary|wage|rent|deposit)",
    re.IGNORECASE,
)

# Size/file fields
_SIZE_FIELD_PATTERN = re.compile(r"(file_size|size|length|width|height|weight)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Regex patterns for Prisma schema parsing
# ---------------------------------------------------------------------------

RE_MODEL_START = re.compile(r"^model\s+(\w+)\s*\{")
RE_ENUM_START = re.compile(r"^enum\s+(\w+)\s*\{")
RE_BLOCK_END = re.compile(r"^\s*\}")

# Field line: name Type? @modifiers
# e.g. "  asset_id  String  @relation(...) @default("") @db.Uuid"
RE_FIELD = re.compile(
    r"^\s+(\w+)\s+([\w\[\]]+)(\??)\s*(.*?)\s*$"
)

# @default("value") or @default(value)
RE_DEFAULT = re.compile(r'@default\(\s*"([^"]*)"\s*\)')
RE_DEFAULT_RAW = re.compile(r"@default\(\s*(\w+)\s*\)")

# @relation("name", fields: [...], references: [...], onDelete: Cascade)
RE_RELATION = re.compile(r"@relation\(")
RE_ON_DELETE = re.compile(r"onDelete\s*:\s*(\w+)")
RE_RELATION_FIELDS = re.compile(r"fields\s*:\s*\[([^\]]*)\]")
RE_RELATION_REFERENCES = re.compile(r"references\s*:\s*\[([^\]]*)\]")

# @@index([field1, field2])
RE_INDEX = re.compile(r"@@index\(\s*\[([^\]]*)\]")

# @@unique([field1, field2])
RE_UNIQUE = re.compile(r"@@unique\(\s*\[([^\]]*)\]")

# @unique on a field
RE_FIELD_UNIQUE = re.compile(r"@unique\b")

# @db.Decimal(precision, scale)
RE_DECIMAL = re.compile(r"@db\.Decimal\(\s*(\d+)\s*,\s*(\d+)\s*\)")

# @db.BigInt or BigInt type
RE_BIGINT = re.compile(r"BigInt")

# Pseudo-enum: inline comment listing allowed values after a String field default
# Matches patterns like: // value1, value2, value3
RE_PSEUDO_ENUM_COMMENT = re.compile(
    r"//\s*([a-zA-Z_][\w]*(?:\s*,\s*[a-zA-Z_][\w]*){2,})"
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_prisma_schema(content: str) -> ParsedSchema:
    """Parse a Prisma schema string into structured data.

    Extracts models with their fields, indexes, and unique constraints,
    plus top-level enums.
    """
    lines = content.splitlines()
    models: dict[str, PrismaModel] = {}
    enums: dict[str, PrismaEnum] = {}

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check for model start
        m = RE_MODEL_START.match(line)
        if m:
            model_name = m.group(1)
            start_line = i + 1  # 1-indexed
            fields: list[PrismaField] = []
            indexes: list[str] = []
            uniques: list[str] = []
            i += 1

            while i < len(lines) and not RE_BLOCK_END.match(lines[i]):
                field_line = lines[i]
                stripped = field_line.strip()

                # Skip comments and empty lines
                if not stripped or stripped.startswith("//"):
                    i += 1
                    continue

                # Check for @@index
                idx_match = RE_INDEX.search(stripped)
                if idx_match:
                    idx_fields = [f.strip() for f in idx_match.group(1).split(",")]
                    indexes.extend(idx_fields)
                    i += 1
                    continue

                # Check for @@unique
                uniq_match = RE_UNIQUE.search(stripped)
                if uniq_match:
                    uniq_fields = [f.strip() for f in uniq_match.group(1).split(",")]
                    uniques.extend(uniq_fields)
                    i += 1
                    continue

                # Skip other @@ directives (@@map, @@id, etc.)
                if stripped.startswith("@@"):
                    i += 1
                    continue

                # Parse field
                fm = RE_FIELD.match(field_line)
                if fm:
                    fname = fm.group(1)
                    ftype = fm.group(2)
                    is_optional = fm.group(3) == "?"
                    modifiers = fm.group(4)

                    # Check for @default
                    default_match = RE_DEFAULT.search(modifiers)
                    default_raw_match = RE_DEFAULT_RAW.search(modifiers)
                    has_default = bool(default_match or default_raw_match)
                    default_value = ""
                    if default_match:
                        default_value = default_match.group(1)
                    elif default_raw_match:
                        default_value = default_raw_match.group(1)

                    # Check for @relation
                    has_relation_attr = bool(RE_RELATION.search(modifiers))

                    # Determine if this is a relation object field
                    # Relation object fields have types that are other model names
                    # (start with uppercase, not a Prisma scalar)
                    prisma_scalars = {
                        "String", "Int", "Float", "Boolean", "DateTime",
                        "BigInt", "Decimal", "Bytes", "Json",
                    }
                    base_type = ftype.rstrip("[]")
                    is_relation = (
                        base_type[0:1].isupper()
                        and base_type not in prisma_scalars
                    )

                    has_unique = bool(RE_FIELD_UNIQUE.search(modifiers))

                    fields.append(PrismaField(
                        name=fname,
                        type=ftype,
                        modifiers=modifiers,
                        line_number=i + 1,  # 1-indexed
                        is_relation=is_relation,
                        is_optional=is_optional,
                        has_default=has_default,
                        default_value=default_value,
                        has_relation_attr=has_relation_attr,
                        has_unique=has_unique,
                        raw_line=field_line,
                    ))

                i += 1

            end_line = i + 1  # 1-indexed
            has_deleted_at = any(f.name == "deleted_at" for f in fields)

            models[model_name] = PrismaModel(
                name=model_name,
                fields=fields,
                indexes=indexes,
                unique_constraints=uniques,
                start_line=start_line,
                end_line=end_line,
                has_deleted_at=has_deleted_at,
            )
            i += 1
            continue

        # Check for enum start
        em = RE_ENUM_START.match(line)
        if em:
            enum_name = em.group(1)
            enum_start = i + 1
            values: list[str] = []
            i += 1
            while i < len(lines) and not RE_BLOCK_END.match(lines[i]):
                val = lines[i].strip()
                if val and not val.startswith("//"):
                    values.append(val)
                i += 1
            enums[enum_name] = PrismaEnum(
                name=enum_name, values=values, start_line=enum_start,
            )
            i += 1
            continue

        i += 1

    return ParsedSchema(models=models, enums=enums, raw_lines=lines)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_missing_cascades(schema: ParsedSchema) -> list[SchemaFinding]:
    """SCHEMA-001: Check for missing onDelete cascade on parent-child relations.

    For every field that has @relation with fields/references (meaning it's
    the FK side of a relation), verify onDelete: Cascade is present.
    """
    findings: list[SchemaFinding] = []

    for model in schema.models.values():
        for f in model.fields:
            if not f.has_relation_attr:
                continue
            # Only check relation object fields that specify fields: [...]
            # (these are the FK-owning side)
            rel_fields_match = RE_RELATION_FIELDS.search(f.modifiers)
            if not rel_fields_match:
                continue

            on_delete_match = RE_ON_DELETE.search(f.modifiers)
            if not on_delete_match:
                findings.append(SchemaFinding(
                    check="SCHEMA-001",
                    severity="critical",
                    message=(
                        f"Relation '{f.name}' on model '{model.name}' has no "
                        f"onDelete directive. Deleting parent will cause FK "
                        f"constraint error or orphaned records."
                    ),
                    model=model.name,
                    field=f.name,
                    line=f.line_number,
                    suggestion=f"Add 'onDelete: Cascade' (or SetNull for optional relations) to the @relation annotation.",
                ))
            elif on_delete_match.group(1) not in ("Cascade", "SetNull", "SetDefault", "NoAction"):
                # Valid but possibly unintended — info level
                pass

    return findings


def check_missing_relations(schema: ParsedSchema) -> list[SchemaFinding]:
    """SCHEMA-002: Check for FK fields (_id suffix) without @relation.

    For every field ending in _id, verify it has a corresponding relation
    object field with @relation annotation linking it.
    """
    findings: list[SchemaFinding] = []

    for model in schema.models.values():
        # Build set of FK fields that ARE referenced by @relation(fields: [...])
        relation_bound_fks: set[str] = set()
        for f in model.fields:
            if f.has_relation_attr:
                m = RE_RELATION_FIELDS.search(f.modifiers)
                if m:
                    for fk in m.group(1).split(","):
                        relation_bound_fks.add(fk.strip())

        for f in model.fields:
            if (
                f.name.endswith(_FK_SUFFIX)
                and f.name not in _FK_EXCEPTIONS
                and f.name != "id"
                and f.name not in relation_bound_fks
                and not f.is_relation
            ):
                # Infer target model from field name (e.g. building_id -> Building)
                target = f.name.removesuffix("_id").replace("_", " ").title().replace(" ", "")
                findings.append(SchemaFinding(
                    check="SCHEMA-002",
                    severity="high",
                    message=(
                        f"Field '{f.name}' on model '{model.name}' looks like "
                        f"a foreign key but has no @relation annotation. "
                        f"No referential integrity or cascade behavior."
                    ),
                    model=model.name,
                    field=f.name,
                    line=f.line_number,
                    suggestion=(
                        f"Add a relation field: {target.lower()} {target}? "
                        f"@relation(fields: [{f.name}], references: [id], onDelete: Cascade)"
                    ),
                ))

    return findings


def check_invalid_defaults(schema: ParsedSchema) -> list[SchemaFinding]:
    """SCHEMA-003: Check for invalid default values on FK fields.

    Detects @default("") on fields that should be UUID/nullable (FK fields).
    An empty string is not a valid UUID and will cause FK constraint violations.
    """
    findings: list[SchemaFinding] = []

    for model in schema.models.values():
        for f in model.fields:
            if not f.has_default:
                continue

            # Empty string default on a field ending in _id
            if f.name.endswith(_FK_SUFFIX) and f.default_value == "":
                findings.append(SchemaFinding(
                    check="SCHEMA-003",
                    severity="critical",
                    message=(
                        f"Field '{f.name}' on model '{model.name}' has "
                        f'@default("") but is a FK field. Empty string is '
                        f"not a valid UUID. Use nullable (String?) instead."
                    ),
                    model=model.name,
                    field=f.name,
                    line=f.line_number,
                    suggestion=f"Change to: {f.name} String? (remove @default(\"\"))",
                ))

            # Empty string default on a UUID-typed field
            if (
                f.default_value == ""
                and f.type == "String"
                and ("@db.Uuid" in f.modifiers or "uuid" in f.name.lower())
            ):
                if not f.name.endswith(_FK_SUFFIX):  # avoid duplicate with above
                    findings.append(SchemaFinding(
                        check="SCHEMA-003",
                        severity="high",
                        message=(
                            f"Field '{f.name}' on model '{model.name}' has "
                            f'@default("") on a UUID-like field. Use '
                            f"@default(uuid()) or make nullable."
                        ),
                        model=model.name,
                        field=f.name,
                        line=f.line_number,
                        suggestion=f"Change to: {f.name} String @default(uuid()) @db.Uuid, or make nullable (String?)",
                    ))

    return findings


def check_missing_indexes(schema: ParsedSchema) -> list[SchemaFinding]:
    """SCHEMA-004: Check for missing database indexes.

    For FK fields, tenant_id, deleted_at, status fields, and other
    commonly-queried fields, verify that @@index exists.
    """
    findings: list[SchemaFinding] = []

    for model in schema.models.values():
        indexed_fields = set(model.indexes) | set(model.unique_constraints)
        # Fields with @unique are implicitly indexed
        for f in model.fields:
            if f.has_unique:
                indexed_fields.add(f.name)
            # @id fields are implicitly indexed
            if "@id" in f.modifiers:
                indexed_fields.add(f.name)

        for f in model.fields:
            needs_index = False
            reason = ""

            if f.name.endswith(_FK_SUFFIX) and f.name not in _FK_EXCEPTIONS and f.name != "id":
                needs_index = True
                reason = "FK field used in joins"
            elif f.name in _INDEX_CANDIDATE_NAMES:
                needs_index = True
                reason = f"commonly queried field '{f.name}'"

            if needs_index and f.name not in indexed_fields:
                findings.append(SchemaFinding(
                    check="SCHEMA-004",
                    severity="medium",
                    message=(
                        f"Field '{f.name}' on model '{model.name}' has no "
                        f"database index ({reason}). Add @@index([{f.name}])."
                    ),
                    model=model.name,
                    field=f.name,
                    line=f.line_number,
                    suggestion=f"Add @@index([{f.name}]) to model {model.name}.",
                ))

    return findings


def check_type_consistency(schema: ParsedSchema) -> list[SchemaFinding]:
    """SCHEMA-005: Check for type/precision inconsistency across similar fields.

    Flags BigInt vs Int inconsistency for size fields, and decimal precision
    inconsistency across financial fields.
    """
    findings: list[SchemaFinding] = []

    # Collect size fields across all models
    size_fields: list[tuple[str, PrismaField]] = []  # (model_name, field)
    financial_fields: list[tuple[str, PrismaField, tuple[int, int]]] = []

    for model in schema.models.values():
        for f in model.fields:
            if _SIZE_FIELD_PATTERN.search(f.name):
                size_fields.append((model.name, f))

            if _FINANCIAL_FIELD_PATTERNS.search(f.name) and f.type in ("Decimal", "Float"):
                dec_match = RE_DECIMAL.search(f.modifiers)
                if dec_match:
                    precision = (int(dec_match.group(1)), int(dec_match.group(2)))
                    financial_fields.append((model.name, f, precision))

    # Check size field type consistency
    if len(size_fields) > 1:
        types_used = {f.type for _, f in size_fields}
        if len(types_used) > 1:
            type_details = [
                f"{model}.{f.name}={f.type}" for model, f in size_fields
            ]
            for model_name, f in size_fields:
                findings.append(SchemaFinding(
                    check="SCHEMA-005",
                    severity="medium",
                    message=(
                        f"Size field '{f.name}' on model '{model_name}' uses "
                        f"'{f.type}' but other size fields use different types: "
                        f"{', '.join(type_details)}. Standardize to one type."
                    ),
                    model=model_name,
                    field=f.name,
                    line=f.line_number,
                    suggestion="Standardize all size fields to Int (or BigInt if values exceed 2^31).",
                ))

    # Check financial field precision consistency
    if len(financial_fields) > 1:
        precisions_used = {p for _, _, p in financial_fields}
        if len(precisions_used) > 1:
            prec_details = [
                f"{model}.{f.name}=Decimal({p[0]},{p[1]})"
                for model, f, p in financial_fields
            ]
            for model_name, f, prec in financial_fields:
                findings.append(SchemaFinding(
                    check="SCHEMA-005",
                    severity="medium",
                    message=(
                        f"Financial field '{f.name}' on model '{model_name}' "
                        f"uses Decimal({prec[0]},{prec[1]}) but other financial "
                        f"fields use different precisions: "
                        f"{', '.join(prec_details)}. Standardize precision."
                    ),
                    model=model_name,
                    field=f.name,
                    line=f.line_number,
                    suggestion="Standardize all financial fields to @db.Decimal(18, 4) for consistent precision.",
                ))

    return findings


def check_soft_delete_filters(
    schema: ParsedSchema,
    service_dir: Path | None = None,
) -> list[SchemaFinding]:
    """SCHEMA-006: Check that models with deleted_at have service-level filters.

    For every model that has a deleted_at field, check that the corresponding
    service file includes `deleted_at: null` in its queries.
    """
    findings: list[SchemaFinding] = []

    if service_dir is None:
        return findings

    for model in schema.models.values():
        if not model.has_deleted_at:
            continue

        # Convert PascalCase model name to kebab-case for service file lookup
        kebab_name = _pascal_to_kebab(model.name)
        service_file = service_dir / f"{kebab_name}.service.ts"

        if not service_file.exists():
            continue

        try:
            service_content = service_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Check for deleted_at filter in findAll/findMany queries
        has_find_all = bool(re.search(r"findAll|findMany|findFirst", service_content))
        has_deleted_filter = bool(re.search(r"deleted_at\s*:\s*null", service_content))

        if has_find_all and not has_deleted_filter:
            findings.append(SchemaFinding(
                check="SCHEMA-006",
                severity="high",
                message=(
                    f"Model '{model.name}' has deleted_at field but service "
                    f"'{kebab_name}.service.ts' queries without "
                    f"'deleted_at: null' filter. Deleted records will appear "
                    f"in results."
                ),
                model=model.name,
                field="deleted_at",
                line=model.start_line,
                suggestion=(
                    f"Add 'where: {{ deleted_at: null }}' to all findMany/findAll "
                    f"calls in {kebab_name}.service.ts, or add Prisma middleware for global soft-delete filtering."
                ),
            ))

    return findings


def check_tenant_isolation(schema: ParsedSchema) -> list[SchemaFinding]:
    """SCHEMA-007: Check for multi-tenant isolation gaps.

    Flags models that should have tenant_id but don't, and models where
    tenant_id is nullable (allowing cross-tenant data leaks).
    """
    findings: list[SchemaFinding] = []

    # Determine if schema uses multi-tenancy (has a Tenant model)
    has_tenant_model = "Tenant" in schema.models
    if not has_tenant_model:
        return findings

    # Models that typically need tenant_id for isolation
    # (skip lookup/config tables that are inherently global)
    _GLOBAL_MODELS = frozenset({
        "Tenant", "User", "Role", "Permission", "Migration",
        "SystemSetting", "AuditLog",
    })

    for model in schema.models.values():
        if model.name in _GLOBAL_MODELS:
            continue

        tenant_field = None
        for f in model.fields:
            if f.name == "tenant_id":
                tenant_field = f
                break

        if tenant_field is None:
            # Only flag if the model has substantial fields (not a join table)
            if len(model.fields) >= 4:
                findings.append(SchemaFinding(
                    check="SCHEMA-007",
                    severity="high",
                    message=(
                        f"Model '{model.name}' has no tenant_id field in a "
                        f"multi-tenant schema. Data may leak across tenants."
                    ),
                    model=model.name,
                    field="tenant_id",
                    line=model.start_line,
                    suggestion=f"Add 'tenant_id String' with @relation to Tenant model.",
                ))
        elif tenant_field.is_optional:
            findings.append(SchemaFinding(
                check="SCHEMA-007",
                severity="high",
                message=(
                    f"Model '{model.name}' has nullable tenant_id "
                    f"(String?). Records without tenant_id could leak "
                    f"across tenants. Make tenant_id required."
                ),
                model=model.name,
                field="tenant_id",
                line=tenant_field.line_number,
                suggestion="Change 'tenant_id String?' to 'tenant_id String' (required, not nullable).",
            ))

    return findings


def check_pseudo_enums(schema: ParsedSchema) -> list[SchemaFinding]:
    """SCHEMA-008: Check for magic string fields used as pseudo-enums.

    Detects String fields with @default("value") followed by an inline comment
    listing valid values (e.g. // active, inactive, suspended). These should
    use proper Prisma enum types for database-level enforcement.
    """
    findings: list[SchemaFinding] = []

    for model in schema.models.values():
        for f in model.fields:
            if f.type != "String":
                continue
            if not f.has_default:
                continue

            # Check if the raw line has a comment listing enum-like values
            comment_match = RE_PSEUDO_ENUM_COMMENT.search(f.raw_line)
            if comment_match:
                values_str = comment_match.group(1).strip()
                values = [v.strip() for v in values_str.split(",")]
                if len(values) >= 3:
                    enum_name = f"{model.name}{f.name.title().replace('_', '')}"
                    findings.append(SchemaFinding(
                        check="SCHEMA-008",
                        severity="high",
                        message=(
                            f"Field '{f.name}' on model '{model.name}' uses "
                            f"String with inline comment listing values "
                            f"({', '.join(values[:4])}{'...' if len(values) > 4 else ''}). "
                            f"Use a Prisma enum type for database-level enforcement."
                        ),
                        model=model.name,
                        field=f.name,
                        line=f.line_number,
                        suggestion=(
                            f"Create enum {enum_name} {{ {' '.join(v.upper() for v in values[:5])} }} "
                            f"and change field to: {f.name} {enum_name} @default({values[0].upper()})"
                        ),
                    ))

    return findings


def check_tenant_unique_constraints(schema: ParsedSchema) -> list[SchemaFinding]:
    """SCHEMA-010: Check multi-tenant models for missing @@unique([tenant_id, ...]).

    In multi-tenant schemas, models with tenant_id often need unique constraints
    that include tenant_id to prevent duplicates within a tenant. Flags models
    that have @@unique constraints NOT including tenant_id.
    """
    findings: list[SchemaFinding] = []

    has_tenant_model = "Tenant" in schema.models
    if not has_tenant_model:
        return findings

    for model in schema.models.values():
        has_tenant_id = any(f.name == "tenant_id" for f in model.fields)
        if not has_tenant_id:
            continue

        # Check if any @@unique constraint includes tenant_id
        if model.unique_constraints and "tenant_id" not in model.unique_constraints:
            findings.append(SchemaFinding(
                check="SCHEMA-010",
                severity="medium",
                message=(
                    f"Model '{model.name}' has @@unique constraint(s) but none "
                    f"include tenant_id. This allows duplicate records across "
                    f"tenants that should be unique per-tenant."
                ),
                model=model.name,
                field="tenant_id",
                line=model.start_line,
                suggestion=(
                    f"Add tenant_id to @@unique constraints, e.g. "
                    f"@@unique([tenant_id, ...existing fields...])"
                ),
            ))

    return findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pascal_to_kebab(name: str) -> str:
    """Convert PascalCase to kebab-case. E.g. 'WorkOrder' -> 'work-order'."""
    result = re.sub(r"([A-Z])", r"-\1", name).lower().lstrip("-")
    return result


def _find_schema_files(project_root: Path) -> list[Path]:
    """Find all schema.prisma files in the project."""
    schema_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        # Skip excluded directories
        dirnames[:] = [
            d for d in dirnames
            if d not in EXCLUDED_DIRS
        ]
        for fn in filenames:
            if fn == "schema.prisma":
                schema_files.append(Path(dirpath) / fn)
    return schema_files


def _find_service_dir(project_root: Path) -> Path | None:
    """Find the NestJS services directory (typically src/ in backend)."""
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for fn in filenames:
            if fn.endswith(".service.ts"):
                return Path(dirpath)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_schema(
    schema_content: str,
    service_dir: Path | None = None,
) -> list[SchemaFinding]:
    """Validate a Prisma schema string and return all findings.

    Args:
        schema_content: The raw content of a schema.prisma file.
        service_dir: Optional path to directory containing .service.ts files
            for soft-delete filter checking (SCHEMA-006).

    Returns:
        List of SchemaFinding objects, sorted by severity then line number.
    """
    schema = parse_prisma_schema(schema_content)
    findings: list[SchemaFinding] = []

    findings.extend(check_missing_cascades(schema))
    findings.extend(check_missing_relations(schema))
    findings.extend(check_invalid_defaults(schema))
    findings.extend(check_missing_indexes(schema))
    findings.extend(check_type_consistency(schema))
    findings.extend(check_soft_delete_filters(schema, service_dir))
    findings.extend(check_tenant_isolation(schema))
    findings.extend(check_pseudo_enums(schema))
    findings.extend(check_tenant_unique_constraints(schema))

    # Sort by severity (critical first), then by line number
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: (severity_order.get(f.severity, 99), f.line))

    return findings[:_MAX_FINDINGS]


def run_schema_validation(
    project_root: Path,
) -> list[SchemaFinding]:
    """Scan a project for Prisma schema files and validate them.

    This is the main entry point for CLI/pipeline integration.

    Args:
        project_root: Root directory of the project to scan.

    Returns:
        List of SchemaFinding objects from all schema files found.
    """
    report = validate_prisma_schema(project_root)
    return report.violations


def validate_prisma_schema(project_root: Path) -> SchemaValidationReport:
    """Find and validate the Prisma schema. Returns report with violations.

    This is the architect-spec public API. Returns a SchemaValidationReport
    with violations, model count, relation count, and pass/fail status.
    Never crashes the pipeline -- returns SCHEMA-000 if schema not found
    or has syntax errors.
    """
    schema_files = _find_schema_files(project_root)
    if not schema_files:
        return SchemaValidationReport(
            violations=[SchemaFinding(
                check="SCHEMA-000",
                severity="medium",
                message="No schema.prisma file found in project.",
                model="",
                field="",
                line=0,
                suggestion="Create a prisma/schema.prisma file.",
            )],
            models_checked=0,
            relations_checked=0,
            passed=True,  # Not finding a schema is not a blocking error
        )

    service_dir = _find_service_dir(project_root)
    all_findings: list[SchemaFinding] = []
    total_models = 0
    total_relations = 0

    for schema_file in schema_files:
        try:
            content = schema_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            all_findings.append(SchemaFinding(
                check="SCHEMA-000",
                severity="high",
                message=f"Could not read schema file: {schema_file}",
                model="",
                field="",
                line=0,
                suggestion="Check file permissions.",
            ))
            continue

        try:
            schema = parse_prisma_schema(content)
        except Exception as exc:
            all_findings.append(SchemaFinding(
                check="SCHEMA-000",
                severity="critical",
                message=f"Schema parse error in {schema_file}: {exc}",
                model="",
                field="",
                line=0,
                suggestion="Fix schema syntax errors before validation.",
            ))
            continue

        total_models += len(schema.models)
        for model in schema.models.values():
            total_relations += sum(1 for f in model.fields if f.has_relation_attr)

        findings = validate_schema(content, service_dir)
        all_findings.extend(findings)

    all_findings = all_findings[:_MAX_FINDINGS]
    has_errors = any(
        f.severity in ("critical", "high") for f in all_findings
        if f.check != "SCHEMA-000"
    )

    return SchemaValidationReport(
        violations=all_findings,
        models_checked=total_models,
        relations_checked=total_relations,
        passed=not has_errors,
    )


def get_schema_models(project_root: Path) -> dict[str, PrismaModel]:
    """Parse schema and return model metadata.

    Used by quality-gate-dev's validators to access model information
    without re-parsing the schema.

    Returns:
        Dictionary mapping model names to PrismaModel objects.
        Returns empty dict if no schema found.
    """
    schema_files = _find_schema_files(project_root)
    all_models: dict[str, PrismaModel] = {}

    for schema_file in schema_files:
        try:
            content = schema_file.read_text(encoding="utf-8", errors="replace")
            schema = parse_prisma_schema(content)
            all_models.update(schema.models)
        except (OSError, Exception):
            continue

    return all_models


def format_findings_report(findings: list[SchemaFinding]) -> str:
    """Format findings into a human-readable report string.

    Returns a multi-line string suitable for inclusion in LLM prompts
    or terminal output.
    """
    if not findings:
        return "No schema issues found."

    lines: list[str] = []
    lines.append(f"Schema Validation: {len(findings)} issue(s) found\n")

    # Group by check code
    by_check: dict[str, list[SchemaFinding]] = {}
    for f in findings:
        by_check.setdefault(f.check, []).append(f)

    check_names = {
        "SCHEMA-000": "Schema Discovery / Parse Issue",
        "SCHEMA-001": "Missing onDelete Cascade",
        "SCHEMA-002": "Missing @relation on FK Field",
        "SCHEMA-003": "Invalid Default Value on FK Field",
        "SCHEMA-004": "Missing Database Index",
        "SCHEMA-005": "Type/Precision Inconsistency",
        "SCHEMA-006": "Soft-Delete Without Filter in Service",
        "SCHEMA-007": "Missing Tenant Isolation (tenant_id)",
        "SCHEMA-008": "Magic String Pseudo-Enum Without DB Enforcement",
        "SCHEMA-010": "Multi-Tenant Model Missing @@unique with tenant_id",
    }

    for check_code in sorted(by_check.keys()):
        check_findings = by_check[check_code]
        name = check_names.get(check_code, check_code)
        lines.append(f"--- {check_code}: {name} ({len(check_findings)} issues) ---")
        for f in check_findings:
            lines.append(
                f"  [{f.severity.upper()}] {f.model}.{f.field} (line {f.line}): "
                f"{f.message}"
            )
        lines.append("")

    return "\n".join(lines)
