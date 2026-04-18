"""Contract compliance scanning for service contracts (CONTRACT-001 through CONTRACT-004).

Provides static analysis scans that verify implementation against service contracts:

1. **CONTRACT-001** (Endpoint Schema) — Verifies response DTO fields match contracted fields
2. **CONTRACT-002** (Missing Endpoint) — Verifies all contracted endpoints have route handlers
3. **CONTRACT-003** (Event Schema) — Verifies event payloads match contracted schemas
4. **CONTRACT-004** (Shared Model) — Verifies shared models match across language boundaries

Each scan is crash-isolated (independent try/except), respects ScanScope, and caps at
_MAX_VIOLATIONS to avoid output flooding.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .quality_checks import Violation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_VIOLATIONS = 100

_SEVERITY_ORDER: dict[str, int] = {"error": 0, "warning": 1, "info": 2}

# Route decorator patterns by framework
_FLASK_ROUTE_PATTERNS = [
    re.compile(r"""@\w+\.route\(\s*['"]([^'"]+)['"](?:.*?methods\s*=\s*\[([^\]]+)\])?"""),
    re.compile(r"""@\w+\.(get|post|put|delete|patch)\(\s*['"]([^'"]+)['"]"""),
]

_FASTAPI_ROUTE_PATTERNS = [
    re.compile(r"""@\w+\.(get|post|put|delete|patch)\(\s*['"]([^'"]+)['"]"""),
]

_EXPRESS_ROUTE_PATTERNS = [
    re.compile(r"""(?:router|app)\.(get|post|put|delete|patch)\(\s*['"]([^'"]+)['"]"""),
]

_ASPNET_ROUTE_PATTERNS = [
    re.compile(r"""\[Http(Get|Post|Put|Delete|Patch)(?:\(\s*['"]([^'"]*)['"]\s*\))?\]""", re.IGNORECASE),
    re.compile(r"""\[Route\(\s*['"]([^'"]+)['"]\s*\)\]"""),
]

# File extensions by language
_TYPESCRIPT_EXTENSIONS = {".ts", ".tsx"}
_PYTHON_EXTENSIONS = {".py"}
_CSHARP_EXTENSIONS = {".cs"}
_JAVASCRIPT_EXTENSIONS = {".js", ".jsx"}

_ALL_CODE_EXTENSIONS = _TYPESCRIPT_EXTENSIONS | _PYTHON_EXTENSIONS | _CSHARP_EXTENSIONS | _JAVASCRIPT_EXTENSIONS

# Controller/route file detection patterns
_CONTROLLER_PATTERNS = [
    re.compile(r"controller", re.IGNORECASE),
    re.compile(r"route[sr]?", re.IGNORECASE),
    re.compile(r"handler", re.IGNORECASE),
    re.compile(r"endpoint", re.IGNORECASE),
    re.compile(r"api", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Precondition helpers
# ---------------------------------------------------------------------------

def _has_svc_table(project_root: Path) -> bool:
    """Check if REQUIREMENTS.md contains an SVC-xxx wiring table.

    Searches root, .agent-team, and milestone REQUIREMENTS.md files.
    """
    req_paths = [
        project_root / "REQUIREMENTS.md",
        project_root / ".agent-team" / "REQUIREMENTS.md",
    ]
    milestones_dir = project_root / ".agent-team" / "milestones"
    if milestones_dir.is_dir():
        for ms_dir in sorted(milestones_dir.iterdir()):
            if ms_dir.is_dir():
                req_path = ms_dir / "REQUIREMENTS.md"
                if req_path.is_file():
                    req_paths.append(req_path)

    svc_pattern = re.compile(r"SVC-\d{3}")
    for req_path in req_paths:
        if req_path.is_file():
            try:
                content = req_path.read_text(encoding="utf-8", errors="replace")
                if svc_pattern.search(content):
                    return True
            except OSError:
                continue
    return False


def _should_scan_file(file_path: Path, scope: Any | None) -> bool:
    """Check if a file should be scanned given the ScanScope."""
    if scope is None:
        return True
    if getattr(scope, "mode", "full") == "full":
        return True
    changed_files = getattr(scope, "changed_files", [])
    if not changed_files:
        return True
    resolved = file_path.resolve()
    return resolved in changed_files


def _collect_code_files(
    project_root: Path,
    extensions: set[str] | None = None,
    name_patterns: list[re.Pattern[str]] | None = None,
) -> list[Path]:
    """Collect source code files from project, optionally filtering by patterns."""
    exts = extensions or _ALL_CODE_EXTENSIONS
    files: list[Path] = []
    # Safe walker — prunes node_modules / .git / dist / .next at
    # descent so pnpm's .pnpm/ symlink tree can't raise WinError 3
    # (project_walker.py post smoke #9/#10). Merge local skip set
    # with DEFAULT_SKIP_DIRS so we never regress on coverage.
    from .project_walker import DEFAULT_SKIP_DIRS, iter_project_files

    local_skips = {
        "node_modules", ".git", "__pycache__", ".venv", "venv",
        "dist", "build", ".next",
    }
    merged_skips = set(DEFAULT_SKIP_DIRS) | local_skips

    for item in iter_project_files(project_root, skip_dirs=merged_skips):
        if item.suffix not in exts:
            continue
        if name_patterns:
            name_lower = item.stem.lower()
            if any(p.search(name_lower) for p in name_patterns):
                files.append(item)
        else:
            files.append(item)

    return files


def _posix_relative(file_path: Path, project_root: Path) -> str:
    """Get POSIX-normalized relative path."""
    try:
        return file_path.relative_to(project_root).as_posix()
    except ValueError:
        return file_path.as_posix()


# ---------------------------------------------------------------------------
# CONTRACT-001: Endpoint Schema Scan
# ---------------------------------------------------------------------------

def _extract_openapi_endpoints(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract endpoints from an OpenAPI spec with their response schemas."""
    endpoints: list[dict[str, Any]] = []
    paths = spec.get("paths", {})

    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.lower() in ("get", "post", "put", "delete", "patch"):
                if not isinstance(operation, dict):
                    continue
                # Extract response schema fields
                responses = operation.get("responses", {})
                for status_code, response in responses.items():
                    if not isinstance(response, dict):
                        continue
                    schema = (
                        response.get("content", {})
                        .get("application/json", {})
                        .get("schema", {})
                    )
                    if schema:
                        fields = _extract_schema_fields(schema, spec)
                        if fields:
                            endpoints.append({
                                "path": path,
                                "method": method.upper(),
                                "status_code": status_code,
                                "fields": fields,
                                "operation_id": operation.get("operationId", ""),
                            })

    return endpoints


def _extract_schema_fields(schema: dict[str, Any], root_spec: dict[str, Any]) -> list[str]:
    """Extract field names from a JSON schema, resolving $ref."""
    if "$ref" in schema:
        ref_path = schema["$ref"]
        # Resolve #/components/schemas/Foo
        parts = ref_path.lstrip("#/").split("/")
        resolved = root_spec
        for part in parts:
            resolved = resolved.get(part, {})
            if not isinstance(resolved, dict):
                return []
        return _extract_schema_fields(resolved, root_spec)

    properties = schema.get("properties", {})
    if properties:
        return list(properties.keys())

    # Array items
    items = schema.get("items", {})
    if items and isinstance(items, dict):
        return _extract_schema_fields(items, root_spec)

    return []


def _extract_dto_fields_typescript(content: str, class_name: str = "") -> list[str]:
    """Extract field names from TypeScript interface/class definitions."""
    fields: list[str] = []

    # Match interface or class blocks
    patterns = [
        re.compile(r"(?:interface|class|type)\s+\w+\s*(?:extends\s+\w+\s*)?\{([^}]+)\}", re.DOTALL),
    ]

    for pattern in patterns:
        for match in pattern.finditer(content):
            body = match.group(1)
            # Extract field names (e.g. "fieldName: type" or "fieldName?: type")
            for field_match in re.finditer(r"(\w+)\s*\??\s*:", body):
                fields.append(field_match.group(1))

    return fields


def _extract_dto_fields_python(content: str) -> list[str]:
    """Extract field names from Python dataclass/Pydantic model definitions."""
    fields: list[str] = []

    # Dataclass fields: field_name: type = default
    for match in re.finditer(r"^\s+(\w+)\s*:\s*\w", content, re.MULTILINE):
        name = match.group(1)
        if not name.startswith("_"):
            fields.append(name)

    return fields


def _extract_dto_fields_csharp(content: str) -> list[str]:
    """Extract property names from C# class definitions."""
    fields: list[str] = []

    # Match public properties: public Type Name { get; set; }
    for match in re.finditer(
        r"public\s+\w[\w<>\[\],\s]*?\s+(\w+)\s*\{",
        content,
    ):
        fields.append(match.group(1))

    return fields


def run_endpoint_schema_scan(
    project_root: Path,
    contracts: list[dict[str, Any]],
    scope: Any | None = None,
) -> list[Violation]:
    """CONTRACT-001: Verify response DTO fields match contracted fields.

    For each OpenAPI contract, extracts expected response fields and compares
    against actual DTO/model fields found in controller/route files.

    Parameters
    ----------
    project_root : Path
        Project root directory.
    contracts : list[dict]
        Service contract dicts with 'spec' containing OpenAPI/AsyncAPI spec.
    scope : ScanScope | None
        Optional scan scope for limiting file scanning.

    Returns
    -------
    list[Violation]
        CONTRACT-001 violations for field mismatches.
    """
    violations: list[Violation] = []

    # Only scan OpenAPI contracts
    openapi_contracts = [
        c for c in contracts
        if c.get("contract_type") == "openapi" and c.get("spec")
    ]

    if not openapi_contracts:
        return violations

    # Collect controller/route files
    code_files = _collect_code_files(project_root)

    for contract in openapi_contracts:
        if len(violations) >= _MAX_VIOLATIONS:
            break

        spec = contract.get("spec", {})
        contract_id = contract.get("contract_id", "unknown")
        endpoints = _extract_openapi_endpoints(spec)

        for endpoint in endpoints:
            if len(violations) >= _MAX_VIOLATIONS:
                break

            expected_fields = endpoint["fields"]
            if not expected_fields:
                continue

            # Search for matching response handling in code files
            for code_file in code_files:
                if not _should_scan_file(code_file, scope):
                    continue

                try:
                    content = code_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                # Extract actual DTO fields based on language
                actual_fields: list[str] = []
                if code_file.suffix in _TYPESCRIPT_EXTENSIONS:
                    actual_fields = _extract_dto_fields_typescript(content)
                elif code_file.suffix in _PYTHON_EXTENSIONS:
                    actual_fields = _extract_dto_fields_python(content)
                elif code_file.suffix in _CSHARP_EXTENSIONS:
                    actual_fields = _extract_dto_fields_csharp(content)

                if not actual_fields:
                    continue

                # Check for missing fields
                actual_set = set(actual_fields)
                for expected_field in expected_fields:
                    if expected_field not in actual_set:
                        # Check case variations
                        lower_actual = {f.lower() for f in actual_fields}
                        if expected_field.lower() in lower_actual:
                            continue  # Case mismatch is handled by CONTRACT-004

                        violations.append(Violation(
                            check=f"CONTRACT-001:{contract_id}",
                            message=(
                                f"Response field '{expected_field}' from contract "
                                f"'{contract_id}' ({endpoint['method']} {endpoint['path']}) "
                                f"not found in {_posix_relative(code_file, project_root)}"
                            ),
                            file_path=_posix_relative(code_file, project_root),
                            line=0,
                            severity="error",
                        ))
                        if len(violations) >= _MAX_VIOLATIONS:
                            break

    return violations[:_MAX_VIOLATIONS]


# ---------------------------------------------------------------------------
# CONTRACT-002: Missing Endpoint Scan
# ---------------------------------------------------------------------------

def _extract_routes_from_file(content: str, file_path: Path) -> list[dict[str, str]]:
    """Extract route definitions from a source file.

    Returns list of dicts with 'method' and 'path' keys.
    """
    routes: list[dict[str, str]] = []

    if file_path.suffix in _PYTHON_EXTENSIONS:
        # Flask/FastAPI patterns
        for pattern in _FLASK_ROUTE_PATTERNS + _FASTAPI_ROUTE_PATTERNS:
            for match in pattern.finditer(content):
                groups = match.groups()
                if len(groups) == 2:
                    if groups[1] is not None:
                        # @app.route with methods= or @router.method
                        method = groups[0].upper() if groups[0] else "GET"
                        path = groups[1] if "/" in str(groups[1]) else groups[0]
                        if "/" in str(groups[1]):
                            path = groups[1]
                            method = groups[0].upper()
                        else:
                            path = groups[0]
                            methods_str = groups[1]
                            for m in re.findall(r"'(\w+)'|\"(\w+)\"", methods_str):
                                method = (m[0] or m[1]).upper()
                                routes.append({"method": method, "path": path})
                            continue
                    else:
                        path = groups[0]
                        method = "GET"
                    routes.append({"method": method, "path": path})

    elif file_path.suffix in _TYPESCRIPT_EXTENSIONS | _JAVASCRIPT_EXTENSIONS:
        # Express patterns
        for pattern in _EXPRESS_ROUTE_PATTERNS:
            for match in pattern.finditer(content):
                method = match.group(1).upper()
                path = match.group(2)
                routes.append({"method": method, "path": path})

    elif file_path.suffix in _CSHARP_EXTENSIONS:
        # ASP.NET patterns
        for pattern in _ASPNET_ROUTE_PATTERNS:
            for match in pattern.finditer(content):
                groups = match.groups()
                if len(groups) >= 1:
                    method = groups[0].upper() if groups[0] else "GET"
                    path = groups[1] if len(groups) > 1 and groups[1] else ""
                    routes.append({"method": method, "path": path})

    return routes


def _normalize_path(path: str) -> str:
    """Normalize a route path for comparison (strip trailing slash, lower)."""
    path = path.strip().rstrip("/").lower()
    # Normalize path parameters: /users/{id} -> /users/:param
    path = re.sub(r"\{[^}]+\}", ":param", path)
    path = re.sub(r"<[^>]+>", ":param", path)  # Flask <type:name>
    path = re.sub(r":\w+", ":param", path)  # Express :name
    return path


def run_missing_endpoint_scan(
    project_root: Path,
    contracts: list[dict[str, Any]],
    scope: Any | None = None,
) -> list[Violation]:
    """CONTRACT-002: Verify all contracted endpoints have route handlers.

    For each OpenAPI contract, checks that every endpoint (method + path) has
    a corresponding route decorator/handler in the codebase.

    Parameters
    ----------
    project_root : Path
        Project root directory.
    contracts : list[dict]
        Service contract dicts with 'spec' containing OpenAPI spec.
    scope : ScanScope | None
        Optional scan scope.

    Returns
    -------
    list[Violation]
        CONTRACT-002 violations for missing endpoints.
    """
    violations: list[Violation] = []

    openapi_contracts = [
        c for c in contracts
        if c.get("contract_type") == "openapi" and c.get("spec")
    ]

    if not openapi_contracts:
        return violations

    # Collect all route handlers in the project
    code_files = _collect_code_files(project_root)
    all_routes: list[dict[str, str]] = []

    for code_file in code_files:
        try:
            content = code_file.read_text(encoding="utf-8", errors="replace")
            routes = _extract_routes_from_file(content, code_file)
            all_routes.extend(routes)
        except OSError:
            continue

    # Normalize all discovered routes for comparison
    normalized_routes = {
        (_normalize_path(r["path"]), r["method"].upper())
        for r in all_routes
        if r.get("path")
    }

    # Check each contracted endpoint
    for contract in openapi_contracts:
        if len(violations) >= _MAX_VIOLATIONS:
            break

        spec = contract.get("spec", {})
        contract_id = contract.get("contract_id", "unknown")
        paths = spec.get("paths", {})

        for path, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            for method in methods:
                if method.lower() not in ("get", "post", "put", "delete", "patch"):
                    continue

                norm_path = _normalize_path(path)
                norm_method = method.upper()

                # Check if any route matches (path + method)
                found = False
                for route_path, route_method in normalized_routes:
                    if route_method == norm_method and (
                        route_path == norm_path
                        or norm_path.rstrip("/") == route_path.rstrip("/")
                    ):
                        found = True
                        break

                if not found:
                    violations.append(Violation(
                        check=f"CONTRACT-002:{contract_id}",
                        message=(
                            f"Contracted endpoint {norm_method} {path} from "
                            f"contract '{contract_id}' has no matching route handler"
                        ),
                        file_path="",
                        line=0,
                        severity="error",
                    ))
                    if len(violations) >= _MAX_VIOLATIONS:
                        break

    return violations[:_MAX_VIOLATIONS]


# ---------------------------------------------------------------------------
# CONTRACT-003: Event Schema Scan
# ---------------------------------------------------------------------------

def _extract_asyncapi_events(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract event channels and their payload schemas from an AsyncAPI spec."""
    events: list[dict[str, Any]] = []
    channels = spec.get("channels", {})

    for channel_name, channel in channels.items():
        if not isinstance(channel, dict):
            continue

        # Check publish and subscribe operations
        for op_type in ("publish", "subscribe"):
            operation = channel.get(op_type, {})
            if not isinstance(operation, dict):
                continue
            message = operation.get("message", {})
            if not isinstance(message, dict):
                continue
            payload = message.get("payload", {})
            if isinstance(payload, dict):
                fields = _extract_schema_fields(payload, spec)
                if fields:
                    events.append({
                        "channel": channel_name,
                        "operation": op_type,
                        "fields": fields,
                    })

    return events


def run_event_schema_scan(
    project_root: Path,
    contracts: list[dict[str, Any]],
    scope: Any | None = None,
) -> list[Violation]:
    """CONTRACT-003: Verify event payloads match contracted schemas.

    For each AsyncAPI contract, checks that publish/subscribe call sites
    emit payloads with the correct fields.

    Parameters
    ----------
    project_root : Path
        Project root directory.
    contracts : list[dict]
        Service contract dicts with 'spec' containing AsyncAPI spec.
    scope : ScanScope | None
        Optional scan scope.

    Returns
    -------
    list[Violation]
        CONTRACT-003 violations for event schema mismatches.
    """
    violations: list[Violation] = []

    asyncapi_contracts = [
        c for c in contracts
        if c.get("contract_type") == "asyncapi" and c.get("spec")
    ]

    if not asyncapi_contracts:
        return violations

    # Patterns for event emission
    emit_patterns = [
        re.compile(r"""(?:emit|publish|dispatch|send|trigger)\s*\(\s*['"]([^'"]+)['"]"""),
        re.compile(r"""(?:\.emit|\.publish|\.dispatch)\s*\(\s*['"]([^'"]+)['"]"""),
    ]

    code_files = _collect_code_files(project_root)

    for contract in asyncapi_contracts:
        if len(violations) >= _MAX_VIOLATIONS:
            break

        spec = contract.get("spec", {})
        contract_id = contract.get("contract_id", "unknown")
        events = _extract_asyncapi_events(spec)

        for event in events:
            if len(violations) >= _MAX_VIOLATIONS:
                break

            channel = event["channel"]
            expected_fields = event["fields"]

            # Search for matching event emissions in code
            for code_file in code_files:
                if not _should_scan_file(code_file, scope):
                    continue

                try:
                    content = code_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                # Check if this file references the event channel
                channel_found = False
                for pattern in emit_patterns:
                    for match in pattern.finditer(content):
                        event_name = match.group(1)
                        if event_name == channel or channel.endswith(event_name):
                            channel_found = True
                            break
                    if channel_found:
                        break

                if not channel_found:
                    continue

                # Extract fields from surrounding code context
                if code_file.suffix in _TYPESCRIPT_EXTENSIONS:
                    actual_fields = _extract_dto_fields_typescript(content)
                elif code_file.suffix in _PYTHON_EXTENSIONS:
                    actual_fields = _extract_dto_fields_python(content)
                elif code_file.suffix in _CSHARP_EXTENSIONS:
                    actual_fields = _extract_dto_fields_csharp(content)
                else:
                    actual_fields = []

                if not actual_fields:
                    continue

                actual_set = set(actual_fields)
                for expected_field in expected_fields:
                    if expected_field not in actual_set:
                        lower_actual = {f.lower() for f in actual_fields}
                        if expected_field.lower() in lower_actual:
                            continue

                        violations.append(Violation(
                            check=f"CONTRACT-003:{contract_id}",
                            message=(
                                f"Event payload field '{expected_field}' for channel "
                                f"'{channel}' from contract '{contract_id}' "
                                f"not found in {_posix_relative(code_file, project_root)}"
                            ),
                            file_path=_posix_relative(code_file, project_root),
                            line=0,
                            severity="warning",
                        ))
                        if len(violations) >= _MAX_VIOLATIONS:
                            break

    return violations[:_MAX_VIOLATIONS]


# ---------------------------------------------------------------------------
# CONTRACT-004: Shared Model Scan
# ---------------------------------------------------------------------------

def _to_snake_case(name: str) -> str:
    """Convert camelCase/PascalCase to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _to_camel_case(name: str) -> str:
    """Convert snake_case to camelCase."""
    components = name.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def run_shared_model_scan(
    project_root: Path,
    contracts: list[dict[str, Any]],
    scope: Any | None = None,
) -> list[Violation]:
    """CONTRACT-004: Verify shared models match across language boundaries.

    Checks that fields defined in contract schemas (typically camelCase for JSON)
    have matching representations in TypeScript (camelCase), Python (snake_case),
    and C# (PascalCase) source files.

    Parameters
    ----------
    project_root : Path
        Project root directory.
    contracts : list[dict]
        Service contract dicts with 'spec'.
    scope : ScanScope | None
        Optional scan scope.

    Returns
    -------
    list[Violation]
        CONTRACT-004 violations for field drift between languages.
    """
    violations: list[Violation] = []

    # Extract all schema field names from contracts
    schema_fields_by_contract: list[tuple[str, list[str]]] = []
    for contract in contracts:
        spec = contract.get("spec", {})
        contract_id = contract.get("contract_id", "unknown")

        # Extract from OpenAPI components/schemas
        schemas = spec.get("components", {}).get("schemas", {})
        for schema_name, schema_def in schemas.items():
            if isinstance(schema_def, dict):
                fields = list(schema_def.get("properties", {}).keys())
                if fields:
                    schema_fields_by_contract.append((contract_id, fields))

        # Extract from paths response schemas
        endpoints = _extract_openapi_endpoints(spec)
        for ep in endpoints:
            if ep.get("fields"):
                schema_fields_by_contract.append((contract_id, ep["fields"]))

    if not schema_fields_by_contract:
        return violations

    # Collect model/DTO files
    code_files = _collect_code_files(project_root)

    for contract_id, expected_fields in schema_fields_by_contract:
        if len(violations) >= _MAX_VIOLATIONS:
            break

        for code_file in code_files:
            if not _should_scan_file(code_file, scope):
                continue

            try:
                content = code_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Extract actual fields from this file
            actual_fields: list[str] = []
            if code_file.suffix in _TYPESCRIPT_EXTENSIONS:
                actual_fields = _extract_dto_fields_typescript(content)
            elif code_file.suffix in _PYTHON_EXTENSIONS:
                actual_fields = _extract_dto_fields_python(content)
            elif code_file.suffix in _CSHARP_EXTENSIONS:
                actual_fields = _extract_dto_fields_csharp(content)

            if not actual_fields:
                continue

            actual_lower = {f.lower() for f in actual_fields}
            actual_set = set(actual_fields)

            for expected_field in expected_fields:
                if len(violations) >= _MAX_VIOLATIONS:
                    break

                # Check if field exists with exact name
                if expected_field in actual_set:
                    continue

                # Check snake_case equivalent (for Python)
                snake = _to_snake_case(expected_field)
                if snake in actual_set:
                    continue

                # Check camelCase equivalent (for TypeScript)
                camel = _to_camel_case(expected_field) if "_" in expected_field else expected_field
                if camel in actual_set:
                    continue

                # Check PascalCase equivalent (for C#)
                pascal = expected_field[0].upper() + expected_field[1:] if expected_field else ""
                if pascal in actual_set:
                    continue

                # Check case-insensitive match (drift detected)
                if expected_field.lower() in actual_lower:
                    violations.append(Violation(
                        check=f"CONTRACT-004:{contract_id}",
                        message=(
                            f"Shared model field '{expected_field}' has naming drift "
                            f"in {_posix_relative(code_file, project_root)}. "
                            f"Expected camelCase/snake_case/PascalCase variant."
                        ),
                        file_path=_posix_relative(code_file, project_root),
                        line=0,
                        severity="warning",
                    ))

    return violations[:_MAX_VIOLATIONS]


# ---------------------------------------------------------------------------
# Orchestrator: run_contract_compliance_scan
# ---------------------------------------------------------------------------

def run_contract_compliance_scan(
    project_root: Path,
    contracts: list[dict[str, Any]],
    scope: Any | None = None,
    *,
    config: Any | None = None,
) -> list[Violation]:
    """Run all 4 contract compliance scans and combine results.

    Each scan is crash-isolated: a failure in one scan does not prevent
    the others from running. Results are combined and capped at
    _MAX_VIOLATIONS.

    Parameters
    ----------
    project_root : Path
        Project root directory.
    contracts : list[dict]
        Service contract dicts with 'contract_id', 'contract_type', 'spec', etc.
    scope : ScanScope | None
        Optional scan scope for limiting file scanning.
    config : ContractScanConfig | None
        Optional scan config to enable/disable individual scans.
        When None, all scans run.

    Returns
    -------
    list[Violation]
        Combined violations from all enabled scans, capped at _MAX_VIOLATIONS.
    """
    if not contracts:
        return []

    violations: list[Violation] = []

    # CONTRACT-001: Endpoint Schema Scan
    if config is None or getattr(config, "endpoint_schema_scan", True):
        try:
            v001 = run_endpoint_schema_scan(project_root, contracts, scope)
            violations.extend(v001)
            logger.debug("CONTRACT-001: %d violation(s)", len(v001))
        except Exception as exc:
            logger.warning("CONTRACT-001 scan crashed: %s", exc, exc_info=True)

    # CONTRACT-002: Missing Endpoint Scan
    if config is None or getattr(config, "missing_endpoint_scan", True):
        try:
            v002 = run_missing_endpoint_scan(project_root, contracts, scope)
            violations.extend(v002)
            logger.debug("CONTRACT-002: %d violation(s)", len(v002))
        except Exception as exc:
            logger.warning("CONTRACT-002 scan crashed: %s", exc, exc_info=True)

    # CONTRACT-003: Event Schema Scan
    if config is None or getattr(config, "event_schema_scan", True):
        try:
            v003 = run_event_schema_scan(project_root, contracts, scope)
            violations.extend(v003)
            logger.debug("CONTRACT-003: %d violation(s)", len(v003))
        except Exception as exc:
            logger.warning("CONTRACT-003 scan crashed: %s", exc, exc_info=True)

    # CONTRACT-004: Shared Model Scan
    if config is None or getattr(config, "shared_model_scan", True):
        try:
            v004 = run_shared_model_scan(project_root, contracts, scope)
            violations.extend(v004)
            logger.debug("CONTRACT-004: %d violation(s)", len(v004))
        except Exception as exc:
            logger.warning("CONTRACT-004 scan crashed: %s", exc, exc_info=True)

    # Cap and sort
    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )
    return violations
