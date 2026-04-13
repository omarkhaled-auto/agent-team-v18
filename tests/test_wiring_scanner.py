"""Tests for scan_request_body_casing wiring scanner (WIRING-CASE-001)."""

from __future__ import annotations

from pathlib import Path

from agent_team_v15.quality_checks import (
    Violation,
    scan_generated_client_field_alignment,
    scan_generated_client_import_usage,
    scan_request_body_casing,
)


# ---------------------------------------------------------------------------
# Positive detection — scanner flags correctly
# ---------------------------------------------------------------------------


def test_snake_case_in_post_body_flagged(tmp_path: Path):
    """Frontend sending snake_case in POST body when DTO expects camelCase."""
    dto_dir = tmp_path / "backend" / "src" / "vehicles"
    dto_dir.mkdir(parents=True)
    (dto_dir / "create-vehicle.dto.ts").write_text(
        "export class CreateVehicleDto {\n"
        "  vehicleId: string;\n"
        "}\n",
        encoding="utf-8",
    )
    fe_dir = tmp_path / "apps" / "web" / "src"
    fe_dir.mkdir(parents=True)
    (fe_dir / "page.tsx").write_text(
        "const res = await fetch('/api/vehicles', {\n"
        "  method: 'POST',\n"
        "  body: JSON.stringify({ vehicle_id: '123' }),\n"
        "});\n",
        encoding="utf-8",
    )
    violations = scan_request_body_casing(tmp_path)
    assert len(violations) >= 1
    v = violations[0]
    assert v.check == "WIRING-CASE-001"
    assert "vehicle_id" in v.message
    assert "vehicleId" in v.message


def test_nps_score_snake_case_flagged(tmp_path: Path):
    """nps_score in frontend POST body when DTO expects npsScore."""
    dto_dir = tmp_path / "backend" / "src" / "feedback"
    dto_dir.mkdir(parents=True)
    (dto_dir / "submit-feedback.dto.ts").write_text(
        "export class SubmitFeedbackDto {\n"
        "  npsScore: number;\n"
        "}\n",
        encoding="utf-8",
    )
    fe_dir = tmp_path / "apps" / "web" / "src"
    fe_dir.mkdir(parents=True)
    (fe_dir / "feedback.tsx").write_text(
        "await fetch('/api/feedback', {\n"
        "  method: 'POST',\n"
        "  body: JSON.stringify({ nps_score: 9 }),\n"
        "});\n",
        encoding="utf-8",
    )
    violations = scan_request_body_casing(tmp_path)
    assert len(violations) >= 1
    assert any("nps_score" in v.message and "npsScore" in v.message for v in violations)


def test_multiple_mismatches_same_file(tmp_path: Path):
    """DTO has vehicleId + serviceTypeId, frontend has snake_case versions."""
    dto_dir = tmp_path / "backend" / "src" / "bookings"
    dto_dir.mkdir(parents=True)
    (dto_dir / "create-booking.dto.ts").write_text(
        "export class CreateBookingDto {\n"
        "  vehicleId: string;\n"
        "  serviceTypeId: string;\n"
        "}\n",
        encoding="utf-8",
    )
    fe_dir = tmp_path / "apps" / "web" / "src"
    fe_dir.mkdir(parents=True)
    (fe_dir / "booking.tsx").write_text(
        "await fetch('/api/bookings', {\n"
        "  method: 'POST',\n"
        "  body: JSON.stringify({ vehicle_id: 'v1', service_type_id: 'st1' }),\n"
        "});\n",
        encoding="utf-8",
    )
    violations = scan_request_body_casing(tmp_path)
    assert len(violations) >= 2
    messages = " ".join(v.message for v in violations)
    assert "vehicle_id" in messages
    assert "service_type_id" in messages


def test_different_casing_name_mismatch(tmp_path: Path):
    """DTO has branchId, frontend has branch_id."""
    dto_dir = tmp_path / "backend" / "src" / "branches"
    dto_dir.mkdir(parents=True)
    (dto_dir / "create-branch.dto.ts").write_text(
        "export class CreateBranchDto {\n"
        "  branchId: string;\n"
        "}\n",
        encoding="utf-8",
    )
    fe_dir = tmp_path / "apps" / "web" / "src"
    fe_dir.mkdir(parents=True)
    (fe_dir / "branches.tsx").write_text(
        "fetch('/api/branches', { method: 'POST', body: JSON.stringify({ branch_id: 'b1' }) });\n",
        encoding="utf-8",
    )
    violations = scan_request_body_casing(tmp_path)
    assert len(violations) >= 1
    assert any("branch_id" in v.message for v in violations)


# ---------------------------------------------------------------------------
# Negative tests — no false positives
# ---------------------------------------------------------------------------


def test_camelcase_in_post_body_not_flagged(tmp_path: Path):
    """Frontend already uses camelCase matching DTO — no violations."""
    dto_dir = tmp_path / "backend" / "src" / "vehicles"
    dto_dir.mkdir(parents=True)
    (dto_dir / "create-vehicle.dto.ts").write_text(
        "export class CreateVehicleDto {\n"
        "  vehicleId: string;\n"
        "}\n",
        encoding="utf-8",
    )
    fe_dir = tmp_path / "apps" / "web" / "src"
    fe_dir.mkdir(parents=True)
    (fe_dir / "page.tsx").write_text(
        "await fetch('/api/vehicles', {\n"
        "  method: 'POST',\n"
        "  body: JSON.stringify({ vehicleId: '123' }),\n"
        "});\n",
        encoding="utf-8",
    )
    violations = scan_request_body_casing(tmp_path)
    assert violations == []


def test_snake_case_in_get_call_not_flagged(tmp_path: Path):
    """snake_case in a GET call (no write method) should not be flagged."""
    dto_dir = tmp_path / "backend" / "src" / "vehicles"
    dto_dir.mkdir(parents=True)
    (dto_dir / "create-vehicle.dto.ts").write_text(
        "export class CreateVehicleDto {\n"
        "  vehicleId: string;\n"
        "}\n",
        encoding="utf-8",
    )
    fe_dir = tmp_path / "apps" / "web" / "src"
    fe_dir.mkdir(parents=True)
    (fe_dir / "page.tsx").write_text(
        "// Fetching vehicle data with vehicle_id param\n"
        "const res = await fetch(`/api/vehicles?vehicle_id=123`);\n"
        "const data = await res.json();\n",
        encoding="utf-8",
    )
    violations = scan_request_body_casing(tmp_path)
    assert violations == []


def test_snake_case_in_comment_not_flagged(tmp_path: Path):
    """snake_case in a comment line should be ignored."""
    dto_dir = tmp_path / "backend" / "src" / "vehicles"
    dto_dir.mkdir(parents=True)
    (dto_dir / "create-vehicle.dto.ts").write_text(
        "export class CreateVehicleDto {\n"
        "  vehicleId: string;\n"
        "}\n",
        encoding="utf-8",
    )
    fe_dir = tmp_path / "apps" / "web" / "src"
    fe_dir.mkdir(parents=True)
    (fe_dir / "page.tsx").write_text(
        "// vehicle_id is the snake case version\n"
        "await fetch('/api/vehicles', {\n"
        "  method: 'POST',\n"
        "  body: JSON.stringify({ vehicleId: '123' }),\n"
        "});\n",
        encoding="utf-8",
    )
    violations = scan_request_body_casing(tmp_path)
    assert violations == []


def test_no_dto_files_returns_empty(tmp_path: Path):
    """No DTO files present — scanner returns empty."""
    fe_dir = tmp_path / "apps" / "web" / "src"
    fe_dir.mkdir(parents=True)
    (fe_dir / "page.tsx").write_text(
        "await fetch('/api/x', { method: 'POST', body: JSON.stringify({ foo_bar: 1 }) });\n",
        encoding="utf-8",
    )
    violations = scan_request_body_casing(tmp_path)
    assert violations == []


def test_no_frontend_dir_returns_empty(tmp_path: Path):
    """No frontend directory — scanner returns empty."""
    dto_dir = tmp_path / "backend" / "src" / "vehicles"
    dto_dir.mkdir(parents=True)
    (dto_dir / "create-vehicle.dto.ts").write_text(
        "export class CreateVehicleDto {\n"
        "  vehicleId: string;\n"
        "}\n",
        encoding="utf-8",
    )
    violations = scan_request_body_casing(tmp_path)
    assert violations == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_project_dir(tmp_path: Path):
    """Completely empty directory — no crash, returns empty."""
    violations = scan_request_body_casing(tmp_path)
    assert violations == []


def test_zero_generated_client_imports_flagged(tmp_path: Path):
    client_dir = tmp_path / "packages" / "api-client"
    client_dir.mkdir(parents=True)
    (client_dir / "index.ts").write_text("export async function listTasks() {}\n", encoding="utf-8")

    frontend_dir = tmp_path / "apps" / "web" / "src"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "page.tsx").write_text(
        "export default function TasksPage() { return <div>Tasks</div>; }\n",
        encoding="utf-8",
    )

    violations = scan_generated_client_import_usage(tmp_path)
    assert len(violations) == 1
    assert violations[0].check == "WIRING-CLIENT-001"


def test_generated_client_imports_clear_zero_import_violation(tmp_path: Path):
    client_dir = tmp_path / "packages" / "api-client"
    client_dir.mkdir(parents=True)
    (client_dir / "index.ts").write_text("export async function listTasks() {}\n", encoding="utf-8")

    frontend_dir = tmp_path / "apps" / "web" / "src"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "page.tsx").write_text(
        "import { listTasks } from '@project/api-client';\n"
        "export default function TasksPage() { void listTasks; return <div>Tasks</div>; }\n",
        encoding="utf-8",
    )

    violations = scan_generated_client_import_usage(tmp_path)
    assert violations == []


def test_generated_client_field_alignment_detects_case_mismatch(tmp_path: Path):
    client_dir = tmp_path / "packages" / "api-client"
    client_dir.mkdir(parents=True)
    (client_dir / "types.ts").write_text(
        "export interface Order {\n  customer_id: string;\n}\n",
        encoding="utf-8",
    )
    (client_dir / "index.ts").write_text(
        "export async function listOrders(): Promise<Order[]> {\n  return [];\n}\n",
        encoding="utf-8",
    )

    frontend_dir = tmp_path / "apps" / "web" / "src"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "orders.tsx").write_text(
        "import { listOrders } from '@project/api-client';\n"
        "interface Order {\n"
        "  customerId: string;\n"
        "}\n"
        "export default function OrdersPage() { void listOrders; return <div />; }\n",
        encoding="utf-8",
    )

    violations = scan_generated_client_field_alignment(tmp_path)

    assert len(violations) == 1
    assert violations[0].check == "CONTRACT-FIELD-002"
    assert "customerId" in violations[0].message
    assert "customer_id" in violations[0].message


def test_generated_client_field_alignment_detects_extra_local_field(tmp_path: Path):
    client_dir = tmp_path / "packages" / "api-client"
    client_dir.mkdir(parents=True)
    (client_dir / "types.ts").write_text(
        "export interface Order {\n  id: string;\n}\n",
        encoding="utf-8",
    )
    (client_dir / "index.ts").write_text(
        "export async function listOrders(): Promise<Order[]> {\n  return [];\n}\n",
        encoding="utf-8",
    )

    frontend_dir = tmp_path / "apps" / "web" / "src"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "orders.tsx").write_text(
        "import { listOrders } from '@project/api-client';\n"
        "interface Order {\n"
        "  id: string;\n"
        "  legacyStatus: string;\n"
        "}\n"
        "export default function OrdersPage() { void listOrders; return <div />; }\n",
        encoding="utf-8",
    )

    violations = scan_generated_client_field_alignment(tmp_path)

    assert len(violations) == 1
    assert violations[0].check == "CONTRACT-FIELD-001"
    assert "legacyStatus" in violations[0].message


def test_generated_client_field_alignment_detects_missing_generated_field(tmp_path: Path):
    client_dir = tmp_path / "packages" / "api-client"
    client_dir.mkdir(parents=True)
    (client_dir / "types.ts").write_text(
        "export interface Order {\n  id: string;\n  status: string;\n}\n",
        encoding="utf-8",
    )
    (client_dir / "index.ts").write_text(
        "export async function listOrders(): Promise<Order[]> {\n  return [];\n}\n",
        encoding="utf-8",
    )

    frontend_dir = tmp_path / "apps" / "web" / "src"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "orders.tsx").write_text(
        "import { listOrders } from '@project/api-client';\n"
        "interface Order {\n"
        "  id: string;\n"
        "}\n"
        "export default function OrdersPage() { void listOrders; return <div />; }\n",
        encoding="utf-8",
    )

    violations = scan_generated_client_field_alignment(tmp_path)

    assert len(violations) == 1
    assert violations[0].check == "CONTRACT-FIELD-001"
    assert "status" in violations[0].message


def test_generated_client_field_alignment_skips_without_client_import(tmp_path: Path):
    client_dir = tmp_path / "packages" / "api-client"
    client_dir.mkdir(parents=True)
    (client_dir / "types.ts").write_text(
        "export interface Order {\n  id: string;\n}\n",
        encoding="utf-8",
    )
    (client_dir / "index.ts").write_text(
        "export async function listOrders(): Promise<Order[]> {\n  return [];\n}\n",
        encoding="utf-8",
    )

    frontend_dir = tmp_path / "apps" / "web" / "src"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "orders.tsx").write_text(
        "interface Order {\n"
        "  id: string;\n"
        "  legacyStatus: string;\n"
        "}\n"
        "export default function OrdersPage() { return <div />; }\n",
        encoding="utf-8",
    )

    violations = scan_generated_client_field_alignment(tmp_path)

    assert violations == []


def test_generated_client_field_alignment_skips_when_client_dir_missing(tmp_path: Path):
    frontend_dir = tmp_path / "apps" / "web" / "src"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "orders.tsx").write_text(
        "import { listOrders } from '@project/api-client';\n"
        "interface Order {\n"
        "  id: string;\n"
        "}\n"
        "export default function OrdersPage() { void listOrders; return <div />; }\n",
        encoding="utf-8",
    )

    violations = scan_generated_client_field_alignment(tmp_path)

    assert violations == []


def test_single_word_dto_props_no_flags(tmp_path: Path):
    """DTO properties that are single-word (no camelCase) produce no violations."""
    dto_dir = tmp_path / "backend" / "src" / "users"
    dto_dir.mkdir(parents=True)
    (dto_dir / "create-user.dto.ts").write_text(
        "export class CreateUserDto {\n"
        "  name: string;\n"
        "  email: string;\n"
        "  phone: string;\n"
        "}\n",
        encoding="utf-8",
    )
    fe_dir = tmp_path / "apps" / "web" / "src"
    fe_dir.mkdir(parents=True)
    (fe_dir / "user.tsx").write_text(
        "await fetch('/api/users', {\n"
        "  method: 'POST',\n"
        "  body: JSON.stringify({ name: 'test', email: 'a@b.c' }),\n"
        "});\n",
        encoding="utf-8",
    )
    violations = scan_request_body_casing(tmp_path)
    assert violations == []


def test_malformed_dto_file_no_crash(tmp_path: Path):
    """Malformed/binary DTO file content should not crash."""
    dto_dir = tmp_path / "backend" / "src"
    dto_dir.mkdir(parents=True)
    (dto_dir / "bad.dto.ts").write_bytes(b"\x00\xff\xfe binary garbage")
    fe_dir = tmp_path / "apps" / "web" / "src"
    fe_dir.mkdir(parents=True)
    (fe_dir / "page.tsx").write_text(
        "await fetch('/api/x', { method: 'POST', body: '{}' });\n",
        encoding="utf-8",
    )
    violations = scan_request_body_casing(tmp_path)
    assert isinstance(violations, list)


def test_encoding_error_no_crash(tmp_path: Path):
    """Files with unusual encoding should not crash."""
    dto_dir = tmp_path / "backend" / "src"
    dto_dir.mkdir(parents=True)
    (dto_dir / "odd.dto.ts").write_text(
        "export class OddDto {\n  vehicleId: string;\n}\n",
        encoding="utf-16",
    )
    fe_dir = tmp_path / "apps" / "web" / "src"
    fe_dir.mkdir(parents=True)
    (fe_dir / "page.tsx").write_text(
        "await fetch('/api/x', { method: 'POST', body: JSON.stringify({ vehicle_id: 1 }) });\n",
        encoding="utf-8",
    )
    # Should not crash
    violations = scan_request_body_casing(tmp_path)
    assert isinstance(violations, list)


# ---------------------------------------------------------------------------
# Strategic fix_suggestion — set at Finding construction time in audit_agent
# ---------------------------------------------------------------------------


def _make_strategic_suggestion(violations: list) -> str:
    """Mirror the fix_suggestion logic from run_deterministic_scan."""
    unique_files = len({v.file_path for v in violations})
    return (
        f"Add a global request body transformer middleware in main.ts that converts "
        f"all incoming snake_case request body keys to camelCase before the "
        f"ValidationPipe processes them. This fixes all {len(violations)} "
        f"affected endpoints in one change rather than renaming fields individually "
        f"across {unique_files} files. Example: NestJS middleware that "
        f"recursively transforms keys via a camelCase function, registered before "
        f"app.useGlobalPipes()."
    )


_CAMEL_NAMES = [
    "vehicleId", "serviceTypeId", "branchId", "appointmentDate",
    "npsScore", "languagePreference", "dayOfWeek", "timeSlot",
    "customerName", "phoneNumber", "emailAddress", "postalCode",
    "invoiceNumber", "paymentMethod", "taxRate", "countryCode",
]


def _to_snake(name: str) -> str:
    import re
    return re.sub(r"([A-Z])", lambda m: "_" + m.group(1).lower(), name).lstrip("_")


def _build_dto_and_frontend(tmp_path: Path, n_fields: int) -> None:
    """Create a project with n_fields snake_case mismatches across two frontend files."""
    assert n_fields <= len(_CAMEL_NAMES), "Increase _CAMEL_NAMES for larger n_fields"
    camel = _CAMEL_NAMES[:n_fields]
    snake = [_to_snake(c) for c in camel]

    dto_dir = tmp_path / "backend" / "src"
    dto_dir.mkdir(parents=True)
    props = "\n".join(f"  {c}: string;" for c in camel)
    (dto_dir / "multi.dto.ts").write_text(
        f"export class MultiDto {{\n{props}\n}}\n", encoding="utf-8"
    )
    fe_dir = tmp_path / "apps" / "web" / "src"
    fe_dir.mkdir(parents=True)
    # Split across two files
    half = max(1, n_fields // 2)
    fields_a = ", ".join(f"{s}: 'v'" for s in snake[:half])
    fields_b = ", ".join(f"{s}: 'v'" for s in snake[half:]) or "'placeholder': 1"
    (fe_dir / "a.tsx").write_text(
        f"await fetch('/api/multi', {{ method: 'POST', body: JSON.stringify({{ {fields_a} }}) }});\n",
        encoding="utf-8",
    )
    (fe_dir / "b.tsx").write_text(
        f"await fetch('/api/multi', {{ method: 'POST', body: JSON.stringify({{ {fields_b} }}) }});\n",
        encoding="utf-8",
    )


def test_strategic_suggestion_contains_middleware(tmp_path: Path):
    """Strategic suggestion built from violations mentions middleware and main.ts."""
    _build_dto_and_frontend(tmp_path, 4)
    violations = scan_request_body_casing(tmp_path)
    assert len(violations) > 0
    suggestion = _make_strategic_suggestion(violations)
    assert "middleware" in suggestion.lower()
    assert "main.ts" in suggestion


def test_strategic_suggestion_includes_violation_count(tmp_path: Path):
    """Strategic suggestion mentions the total number of violations."""
    _build_dto_and_frontend(tmp_path, 4)
    violations = scan_request_body_casing(tmp_path)
    assert len(violations) > 0
    suggestion = _make_strategic_suggestion(violations)
    assert str(len(violations)) in suggestion


def test_strategic_suggestion_includes_file_count(tmp_path: Path):
    """Strategic suggestion mentions the unique file count."""
    _build_dto_and_frontend(tmp_path, 4)
    violations = scan_request_body_casing(tmp_path)
    assert len(violations) > 0
    unique_files = len({v.file_path for v in violations})
    suggestion = _make_strategic_suggestion(violations)
    assert str(unique_files) in suggestion


def test_no_suggestion_built_for_empty_violations(tmp_path: Path):
    """When no violations, the suggestion logic produces an empty string."""
    # Empty project — no DTOs, no frontend
    violations = scan_request_body_casing(tmp_path)
    assert violations == []
    # The run_deterministic_scan logic sets "" when no violations
    suggestion = _make_strategic_suggestion(violations) if violations else ""
    assert suggestion == ""
