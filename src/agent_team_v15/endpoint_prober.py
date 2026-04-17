"""Live endpoint verification utilities for V18.1 Phase 3.

Runs after Wave B compile succeeds and before Wave C starts.
Owns Docker lifecycle reuse, probe manifest generation, probe execution,
evidence collection, and probe telemetry persistence.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from .runtime_verification import (
    _find_container_name,
    check_docker_available,
    docker_build,
    docker_start,
    find_compose_file,
    run_migrations,
    run_seed_scripts,
)

logger = logging.getLogger(__name__)

_PATH_PARAM_RE = re.compile(r":([A-Za-z0-9_]+)|{([^}]+)}")
_ACTION_SEGMENTS = {
    "approve",
    "reject",
    "sync",
    "archive",
    "activate",
    "deactivate",
    "cancel",
    "complete",
    "submit",
}
_DEFAULT_UUID = "00000000-0000-0000-0000-000000000001"
_NONEXISTENT_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
_SEED_MISSING = object()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProbeSpec:
    """A single probe to execute against a running endpoint."""

    endpoint: str
    method: str
    path: str
    probe_type: str
    expected_status: int
    request_body: Optional[dict[str, Any]] = None
    headers: dict[str, str] = field(default_factory=dict)
    path_params: dict[str, str] = field(default_factory=dict)
    description: str = ""


@dataclass
class ProbeResult:
    """Result of executing one probe."""

    spec: ProbeSpec
    actual_status: int = 0
    passed: bool = False
    response_body: str = ""
    duration_ms: float = 0.0
    error: str = ""


@dataclass
class ProbeManifest:
    """Complete probe plan and results for a milestone."""

    milestone_id: str
    total_probes: int = 0
    happy_pass: int = 0
    happy_fail: int = 0
    negative_pass: int = 0
    negative_fail: int = 0
    probes: list[ProbeSpec] = field(default_factory=list)
    results: list[ProbeResult] = field(default_factory=list)
    failures: list[ProbeResult] = field(default_factory=list)


@dataclass
class DockerContext:
    """Running Docker environment for probing.

    ``infra_missing`` is True ONLY when the host genuinely lacks the
    infrastructure to probe — Docker not installed, no compose file,
    no reachable external app. It is NOT set when Docker and compose
    exist but a container-level or app-level failure occurred (e.g.
    host-port binding conflict, app never became healthy). That
    distinction lets callers decide between graceful CI-skip (infra
    missing) and hard failure (infra present, probe failed) — the
    fragile string-matching that predates the flag always leaked.

    Phase F §7.5: ``runtime_infra`` carries the auto-detected
    ``RuntimeInfra`` snapshot (api_prefix, CORS_ORIGIN, DATABASE_URL,
    JWT audience). Callers should build probe URLs via
    :func:`infra_detector.build_probe_url(ctx.app_url, route,
    infra=ctx.runtime_infra)` so ``api_prefix`` is honored when the
    NestJS boot sets one via ``setGlobalPrefix``. ``None`` when the
    detector was disabled or produced no hits.
    """

    app_url: str = ""
    containers_running: bool = False
    api_healthy: bool = False
    external_app: bool = False
    startup_error: str = ""
    infra_missing: bool = False
    runtime_infra: Any = None


def generate_probe_manifest(
    milestone_id: str,
    wave_b_artifact: dict[str, Any],
    openapi_spec_path: Optional[Path],
    ir: dict[str, Any],
    seed_fixtures: dict[str, Any],
) -> ProbeManifest:
    """Generate a schema-aware probe manifest from current milestone metadata."""

    manifest = ProbeManifest(milestone_id=milestone_id)
    endpoints = _collect_endpoints(wave_b_artifact, openapi_spec_path, ir)

    for endpoint in endpoints:
        happy_body = _build_valid_request_body(endpoint, seed_fixtures)
        happy_params = _build_valid_path_params(endpoint, seed_fixtures)
        happy_headers = _build_auth_headers(endpoint, ir)

        manifest.probes.append(
            ProbeSpec(
                endpoint=f"{endpoint['method']} {endpoint['path']}",
                method=endpoint["method"],
                path=endpoint["path"],
                probe_type="happy_path",
                expected_status=_expected_happy_status(endpoint),
                request_body=happy_body,
                headers=happy_headers,
                path_params=happy_params,
                description=f"Happy path: {endpoint['method']} {endpoint['path']}",
            )
        )

        is_protected = _is_protected_route(endpoint, ir)
        is_mutating = endpoint["method"] in {"POST", "PUT", "PATCH", "DELETE"}
        is_creation = endpoint["method"] == "POST" and not _is_action_route(endpoint)
        is_parameterized = bool(_extract_path_params(endpoint["path"]))

        if is_protected:
            manifest.probes.append(
                ProbeSpec(
                    endpoint=f"{endpoint['method']} {endpoint['path']}",
                    method=endpoint["method"],
                    path=endpoint["path"],
                    probe_type="401_unauthenticated",
                    expected_status=401,
                    request_body=happy_body,
                    headers={},
                    path_params=happy_params,
                    description=f"401: No auth for {endpoint['method']} {endpoint['path']}",
                )
            )

        if is_mutating and happy_body:
            manifest.probes.append(
                ProbeSpec(
                    endpoint=f"{endpoint['method']} {endpoint['path']}",
                    method=endpoint["method"],
                    path=endpoint["path"],
                    probe_type="400_invalid_body",
                    expected_status=400,
                    request_body=_build_invalid_request_body(endpoint),
                    headers=happy_headers,
                    path_params=happy_params,
                    description=f"400: Invalid body for {endpoint['method']} {endpoint['path']}",
                )
            )

        if is_creation and _has_seed_record(endpoint, seed_fixtures):
            manifest.probes.append(
                ProbeSpec(
                    endpoint=f"{endpoint['method']} {endpoint['path']}",
                    method=endpoint["method"],
                    path=endpoint["path"],
                    probe_type="409_duplicate",
                    expected_status=409,
                    request_body=_build_duplicate_body(endpoint, seed_fixtures),
                    headers=happy_headers,
                    path_params=happy_params,
                    description=f"409: Duplicate create at {endpoint['method']} {endpoint['path']}",
                )
            )

        if is_parameterized:
            manifest.probes.append(
                ProbeSpec(
                    endpoint=f"{endpoint['method']} {endpoint['path']}",
                    method=endpoint["method"],
                    path=endpoint["path"],
                    probe_type="404_not_found",
                    expected_status=404,
                    request_body=happy_body,
                    headers=happy_headers,
                    path_params=_build_nonexistent_params(endpoint),
                    description=f"404: Missing resource for {endpoint['method']} {endpoint['path']}",
                )
            )

    manifest.total_probes = len(manifest.probes)
    return manifest


def _collect_endpoints(
    wave_b_artifact: dict[str, Any],
    spec_path: Optional[Path],
    ir: dict[str, Any],
) -> list[dict[str, Any]]:
    """Collect endpoint metadata with Wave B as authority for new routes."""

    endpoints: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    artifact_dtos = list(wave_b_artifact.get("dtos", []) or [])

    for controller in list(wave_b_artifact.get("controllers", []) or []):
        for endpoint in list(controller.get("endpoints", []) or []):
            method = str(endpoint.get("method", "GET")).upper()
            path = str(endpoint.get("path", "")).strip() or "/"
            key = _endpoint_key(method, path)
            entry = {
                "method": method,
                "path": path,
                "parameters": [],
                "requestBody": {},
                "responses": {},
                "security": [],
                "tags": [],
                "handler": endpoint.get("handler", ""),
                "controller": controller.get("name", ""),
                "dto_fields": _select_dto_fields_for_endpoint(method, path, artifact_dtos),
            }
            by_key[key] = entry
            endpoints.append(entry)

    spec_operations = _load_spec_operations(spec_path)
    for key, metadata in spec_operations.items():
        if key in by_key:
            by_key[key].update(
                {
                    "parameters": metadata.get("parameters", []),
                    "requestBody": metadata.get("requestBody", {}),
                    "responses": metadata.get("responses", {}),
                    "security": metadata.get("security", []),
                    "tags": metadata.get("tags", []),
                }
            )
        elif not endpoints:
            by_key[key] = metadata
            endpoints.append(metadata)

    if not endpoints:
        for ir_endpoint in list(ir.get("endpoints", []) or []):
            method = str(ir_endpoint.get("method", "GET")).upper()
            path = str(ir_endpoint.get("path", "")).strip() or "/"
            key = _endpoint_key(method, path)
            if key in by_key:
                continue
            metadata = {
                "method": method,
                "path": path,
                "parameters": [],
                "requestBody": {},
                "responses": {},
                "security": [],
                "tags": list(ir_endpoint.get("tags", []) or []),
                "owner_feature": ir_endpoint.get("owner_feature", ""),
                "auth": ir_endpoint.get("auth") or ir_endpoint.get("protected"),
                "dto_fields": [],
            }
            by_key[key] = metadata
            endpoints.append(metadata)

    return endpoints


def _endpoint_key(method: str, path: str) -> tuple[str, str]:
    normalized_path = _PATH_PARAM_RE.sub("{param}", str(path or "").strip() or "/")
    normalized_path = re.sub(r"/+", "/", normalized_path)
    return str(method or "GET").upper(), normalized_path


def _load_spec_operations(spec_path: Optional[Path]) -> dict[tuple[str, str], dict[str, Any]]:
    operations: dict[tuple[str, str], dict[str, Any]] = {}
    if spec_path is None or not spec_path.is_file():
        return operations

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load OpenAPI spec %s: %s", spec_path, exc)
        return operations

    for path, methods in spec.get("paths", {}).items():
        if not isinstance(methods, dict):
            continue
        for method, details in methods.items():
            method_upper = str(method).upper()
            if method_upper not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            operations[_endpoint_key(method_upper, path)] = {
                "method": method_upper,
                "path": path,
                "parameters": list(details.get("parameters", []) or []),
                "requestBody": dict(details.get("requestBody", {}) or {}),
                "responses": dict(details.get("responses", {}) or {}),
                "security": list(details.get("security", []) or []),
                "tags": list(details.get("tags", []) or []),
                "dto_fields": [],
            }
    return operations


def _select_dto_fields_for_endpoint(
    method: str,
    path: str,
    dtos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if method not in {"POST", "PUT", "PATCH"} or not dtos:
        return []

    resource = _resource_name_from_path(path)
    candidates: list[dict[str, Any]] = []
    for dto in dtos:
        dto_name = str(dto.get("name", "")).lower()
        if method == "POST" and dto_name.startswith("create"):
            candidates.append(dto)
            continue
        if method in {"PUT", "PATCH"} and dto_name.startswith("update"):
            candidates.append(dto)
            continue
        if resource and resource.rstrip("s") in dto_name:
            candidates.append(dto)

    chosen = candidates[0] if candidates else dtos[0]
    return list(chosen.get("fields", []) or [])


def _build_valid_request_body(
    endpoint: dict[str, Any],
    seed_fixtures: dict[str, Any],
) -> Optional[dict[str, Any]]:
    request_body = dict(endpoint.get("requestBody", {}) or {})
    if request_body:
        schema = (
            request_body.get("content", {})
            .get("application/json", {})
            .get("schema", {})
        )
        if schema:
            return _generate_body_from_schema(schema, seed_fixtures)

    dto_fields = list(endpoint.get("dto_fields", []) or [])
    if dto_fields:
        return _generate_body_from_dto_fields(dto_fields, seed_fixtures)
    return None


def _generate_body_from_schema(schema: dict[str, Any], seed_fixtures: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    properties = dict(schema.get("properties", {}) or {})
    required = set(schema.get("required", []) or properties.keys())

    for field_name, field_schema in properties.items():
        if field_name not in required and not field_schema.get("default") and not seed_fixtures.get(field_name):
            continue
        body[field_name] = _schema_value(field_name, field_schema, seed_fixtures)
    return body


def _generate_body_from_dto_fields(
    dto_fields: list[dict[str, Any]],
    seed_fixtures: dict[str, Any],
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for field in dto_fields:
        if field.get("optional"):
            continue
        field_name = str(field.get("name", "")).strip()
        if not field_name:
            continue
        body[field_name] = _type_value(field_name, str(field.get("type", "string")), seed_fixtures)
    return body


def _schema_value(field_name: str, field_schema: dict[str, Any], seed_fixtures: dict[str, Any]) -> Any:
    seeded = _resolve_seed_value(
        field_name,
        seed_fixtures,
        prefer_existing=False,
        field_type=str(field_schema.get("type", "")),
    )
    if seeded is not _SEED_MISSING:
        return seeded
    enum_values = list(field_schema.get("enum", []) or [])
    if enum_values:
        return enum_values[0]
    return _type_value(field_name, str(field_schema.get("type", "string")), seed_fixtures)


def _type_value(field_name: str, field_type: str, seed_fixtures: dict[str, Any]) -> Any:
    seeded = _resolve_seed_value(
        field_name,
        seed_fixtures,
        prefer_existing=False,
        field_type=field_type,
    )
    if seeded is not _SEED_MISSING:
        return seeded
    return _default_type_value(field_name, field_type)


def _default_type_value(field_name: str, field_type: str) -> Any:
    field_lower = field_name.lower()
    type_lower = field_type.lower()

    if "email" in field_lower:
        return "test@example.com"
    if "date" in field_lower or type_lower == "datetime":
        return "2026-01-15T00:00:00Z"
    if "uuid" in field_lower or (field_lower.endswith("id") and "grid" not in field_lower):
        return _DEFAULT_UUID
    if type_lower in {"integer", "int", "number", "float", "double"}:
        return 1
    if type_lower in {"boolean", "bool"}:
        return True
    if type_lower == "array":
        return []
    if type_lower == "object":
        return {}
    return f"test_{field_name}"


def _resolve_seed_value(
    field_name: str,
    seed_fixtures: dict[str, Any],
    *,
    prefer_existing: bool,
    field_type: str = "",
) -> Any:
    if not isinstance(seed_fixtures, dict):
        return _SEED_MISSING

    existing_record = _existing_fixture_record(seed_fixtures)

    if prefer_existing:
        for key in (f"duplicate_{field_name}", f"existing_{field_name}"):
            if key in seed_fixtures:
                return seed_fixtures[key]
        if field_name in existing_record:
            return existing_record[field_name]
        if field_name in seed_fixtures:
            return seed_fixtures[field_name]
        return _SEED_MISSING

    for key in (f"valid_{field_name}", f"new_{field_name}", f"fresh_{field_name}"):
        if key in seed_fixtures:
            return seed_fixtures[key]

    if field_name in seed_fixtures:
        if _seed_value_conflicts_for_happy_path(field_name, field_type, seed_fixtures, existing_record):
            return _SEED_MISSING
        return seed_fixtures[field_name]

    return _SEED_MISSING


def _existing_fixture_record(seed_fixtures: dict[str, Any]) -> dict[str, Any]:
    existing_record = seed_fixtures.get("existing_record")
    if isinstance(existing_record, dict):
        return dict(existing_record)
    return {}


def _seed_value_conflicts_for_happy_path(
    field_name: str,
    field_type: str,
    seed_fixtures: dict[str, Any],
    existing_record: dict[str, Any],
) -> bool:
    if field_name in existing_record:
        return True
    return bool(seed_fixtures.get("existing_record")) and _field_likely_unique(field_name, field_type)


def _field_likely_unique(field_name: str, field_type: str) -> bool:
    field_lower = field_name.lower()
    type_lower = field_type.lower()
    if field_lower.endswith("email") or "email" in field_lower:
        return True
    if field_lower.endswith("slug") or field_lower.endswith("code"):
        return True
    if field_lower.endswith("name") or field_lower in {"name", "username", "handle"}:
        return True
    if field_lower.endswith("uuid"):
        return True
    if field_lower.endswith("id") and "grid" not in field_lower:
        return True
    return type_lower == "uuid"


def _build_invalid_request_body(endpoint: dict[str, Any]) -> dict[str, Any]:
    body = _build_valid_request_body(endpoint, {})
    if not body:
        return {"__invalid_field__": "unexpected"}

    invalid: dict[str, Any] = {}
    for key, value in body.items():
        if isinstance(value, bool):
            invalid[key] = "not-a-bool"
        elif isinstance(value, (int, float)):
            invalid[key] = "not-a-number"
        elif isinstance(value, list):
            invalid[key] = {"not": "an-array"}
        elif isinstance(value, dict):
            invalid[key] = "not-an-object"
        else:
            invalid[key] = None
    invalid["__invalid_field__"] = "unexpected"
    return invalid


def _build_valid_path_params(endpoint: dict[str, Any], seed_fixtures: dict[str, Any]) -> dict[str, str]:
    params: dict[str, str] = {}
    for param_name in _extract_path_params(str(endpoint.get("path", ""))):
        params[param_name] = str(
            seed_fixtures.get(param_name)
            or seed_fixtures.get(param_name.rstrip("s"))
            or seed_fixtures.get("id")
            or _DEFAULT_UUID
        )
    return params


def _build_nonexistent_params(endpoint: dict[str, Any]) -> dict[str, str]:
    params: dict[str, str] = {}
    for param_name in _extract_path_params(str(endpoint.get("path", ""))):
        if "id" in param_name.lower():
            params[param_name] = _NONEXISTENT_UUID
        else:
            params[param_name] = f"missing-{param_name}"
    return params


def _extract_path_params(path: str) -> list[str]:
    params: list[str] = []
    for match in _PATH_PARAM_RE.finditer(path):
        params.append(match.group(1) or match.group(2) or "")
    return [param for param in params if param]


def _build_auth_headers(endpoint: dict[str, Any], ir: dict[str, Any]) -> dict[str, str]:
    if _is_protected_route(endpoint, ir):
        return {"Authorization": "Bearer test-token"}
    return {}


def _is_protected_route(endpoint: dict[str, Any], ir: dict[str, Any]) -> bool:
    if endpoint.get("security"):
        return True

    method = str(endpoint.get("method", "GET")).upper()
    path = str(endpoint.get("path", ""))
    for ir_endpoint in list(ir.get("endpoints", []) or []):
        if str(ir_endpoint.get("method", "GET")).upper() != method:
            continue
        if str(ir_endpoint.get("path", "")) != path:
            continue
        if ir_endpoint.get("auth") or ir_endpoint.get("protected") or ir_endpoint.get("requires_auth"):
            return True
        security = ir_endpoint.get("security", [])
        if isinstance(security, list) and security:
            return True
    return False


def _is_action_route(endpoint: dict[str, Any]) -> bool:
    segments = [segment for segment in str(endpoint.get("path", "")).split("/") if segment]
    if not segments:
        return False
    last = segments[-1].lower()
    if last.startswith(":") or last.startswith("{"):
        return False
    return last in _ACTION_SEGMENTS


def _expected_happy_status(endpoint: dict[str, Any]) -> int:
    responses = dict(endpoint.get("responses", {}) or {})
    for status in sorted(responses):
        status_str = str(status)
        if status_str.startswith("2") and status_str[:3].isdigit():
            return int(status_str[:3])

    method = str(endpoint.get("method", "GET")).upper()
    if method == "POST":
        return 201
    if method == "DELETE":
        return 200
    return 200


def _has_seed_record(endpoint: dict[str, Any], seed_fixtures: dict[str, Any]) -> bool:
    resource = _resource_name_from_path(str(endpoint.get("path", "")))
    if not resource:
        return bool(seed_fixtures)
    singular = resource.rstrip("s")
    return any(
        key in seed_fixtures
        for key in {resource, singular, f"{singular}_id", f"{resource}_id", "existing_record"}
    )


def _build_duplicate_body(endpoint: dict[str, Any], seed_fixtures: dict[str, Any]) -> dict[str, Any]:
    body = _build_valid_request_body(endpoint, seed_fixtures) or {}
    existing_record = _existing_fixture_record(seed_fixtures)
    if not body:
        duplicate_name = _resolve_seed_value("name", seed_fixtures, prefer_existing=True)
        if duplicate_name is not _SEED_MISSING:
            return {"name": duplicate_name}
        if existing_record:
            return dict(existing_record)
        return {"name": "duplicate"}
    for key in list(body):
        seeded = _resolve_seed_value(key, seed_fixtures, prefer_existing=True)
        if seeded is not _SEED_MISSING:
            body[key] = seeded
        elif key.lower().endswith("email"):
            body[key] = "existing@example.com"
    return body


def _resource_name_from_path(path: str) -> str:
    segments = [
        segment
        for segment in path.split("/")
        if segment and not segment.startswith(":") and not segment.startswith("{")
    ]
    if not segments:
        return ""
    last = segments[-1].lower()
    if last in _ACTION_SEGMENTS and len(segments) > 1:
        return segments[-2].lower()
    return last


def load_seed_fixtures(cwd: str) -> dict[str, Any]:
    """Load simple seed-fixture values from common project locations."""

    project_root = Path(cwd)
    candidates = [
        project_root / ".agent-team" / "seed-fixtures.json",
        project_root / "seed" / "fixtures.json",
        project_root / "seeds" / "fixtures.json",
        project_root / "database" / "seed" / "fixtures.json",
        project_root / "prisma" / "seed-data.json",
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


async def start_docker_for_probing(cwd: str, config: Any) -> DockerContext:
    """Start or reuse Docker containers for endpoint probing."""

    project_root = Path(cwd)
    compose_file = find_compose_file(
        project_root,
        override=getattr(getattr(config, "runtime_verification", None), "compose_file", "") if config else "",
    )
    context = DockerContext(
        app_url=_detect_app_url(project_root, config),
        runtime_infra=_detect_runtime_infra(project_root, config),
    )
    if compose_file is None:
        context.external_app = True
        context.api_healthy = await _poll_health(context.app_url, timeout=10)
        if context.api_healthy:
            return context
        context.startup_error = (
            f"live_endpoint_check=True but no compose file was found under {project_root} "
            f"and no healthy external app responded at {context.app_url}"
        )
        context.infra_missing = True
        logger.warning("%s", context.startup_error)
        return context

    if not check_docker_available():
        context.external_app = True
        context.api_healthy = await _poll_health(context.app_url, timeout=10)
        if context.api_healthy:
            return context
        context.startup_error = (
            f"live_endpoint_check=True but Docker is unavailable and no healthy external app responded at {context.app_url}"
        )
        context.infra_missing = True
        logger.warning("%s", context.startup_error)
        return context

    try:
        if _containers_running(project_root, compose_file):
            context.containers_running = True
            _restart_api_process(project_root, compose_file)
        else:
            build_results = docker_build(project_root, compose_file)
            if any(not result.success for result in build_results):
                context.startup_error = "Docker build failed during live endpoint probing startup"
                logger.warning("Docker build reported failures: %s", build_results)
                return context
            service_statuses = docker_start(project_root, compose_file)
            context.containers_running = any(status.healthy for status in service_statuses)

        # D-02: after docker compose brings containers up, verify the host
        # ports declared in the compose file actually bound. When another
        # process on the host owns the port (e.g. a long-running postgres
        # from a different project), compose silently starts the container
        # with a container-only network binding — internally "healthy" but
        # unreachable from the host, so every host-side migrate/seed/test
        # routes to the OTHER process and fails. Detect this BEFORE the
        # 60-second health poll so the error message names the actual
        # cause, not just "never became healthy".
        unbound = _detect_unbound_host_ports(project_root, compose_file)
        if unbound:
            context.startup_error = (
                "live_endpoint_check=True but declared host port(s) are not bound — "
                + "; ".join(
                    f"service '{service}' host port {port} unbound "
                    f"(another process on the host likely owns {port}; "
                    f"run `docker ps --filter publish={port}` to confirm)"
                    for service, port in unbound
                )
            )
            logger.warning("%s", context.startup_error)
            return context

        context.api_healthy = await _poll_health(context.app_url, timeout=60)

        if not context.api_healthy:
            logger.warning("Warm probe start failed health check; attempting full restart")
            _stop_containers(project_root, compose_file)
            build_results = docker_build(project_root, compose_file)
            if any(not result.success for result in build_results):
                context.startup_error = "Docker rebuild failed during live endpoint probing recovery"
                return context
            service_statuses = docker_start(project_root, compose_file)
            context.containers_running = any(status.healthy for status in service_statuses)
            # Re-check host-port binding after the restart — the restart may
            # have raced with the port's original owner releasing it, or may
            # still conflict. Same diagnostic either way.
            unbound = _detect_unbound_host_ports(project_root, compose_file)
            if unbound:
                context.startup_error = (
                    "live_endpoint_check=True but declared host port(s) are not bound after restart — "
                    + "; ".join(
                        f"service '{service}' host port {port} unbound"
                        for service, port in unbound
                    )
                )
                logger.warning("%s", context.startup_error)
                return context
            context.api_healthy = await _poll_health(context.app_url, timeout=60)
        if not context.api_healthy:
            context.startup_error = (
                f"live_endpoint_check=True but the application never became healthy at {context.app_url}"
            )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Docker startup failed for probing: %s", exc, exc_info=True)
        context.containers_running = False
        context.api_healthy = False
        context.startup_error = f"Docker startup failed for live endpoint probing: {exc}"

    return context


def _parse_compose_host_ports(compose_file: Path) -> list[tuple[str, str]]:
    """Return [(service, host_port), ...] for each host-bound port in compose.

    Best-effort YAML parse. If PyYAML isn't installed we fall back to a
    regex walk — the D-02 diagnostic is a nice-to-have, not load-bearing;
    we prefer degrading to an empty list over raising so the probe
    continues its existing recovery path.
    """
    try:
        text = compose_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(text) or {}
    except Exception:
        return _parse_compose_host_ports_regex(text)

    services = data.get("services") or {}
    if not isinstance(services, dict):
        return []
    host_ports: list[tuple[str, str]] = []
    for service_name, service_cfg in services.items():
        if not isinstance(service_cfg, dict):
            continue
        ports = service_cfg.get("ports") or []
        if not isinstance(ports, list):
            continue
        for entry in ports:
            host_port = _extract_host_port(entry)
            if host_port:
                host_ports.append((str(service_name), host_port))
    return host_ports


def _extract_host_port(entry: Any) -> str:
    """Extract the host port from a compose port entry.

    Accepts:
      - Short form string: ``"5432:5432"`` or ``"127.0.0.1:5432:5432"``.
      - Long form dict:    ``{"published": 5432, "target": 5432, ...}``.
    Returns "" for container-only bindings (``"5432"``) since those don't
    participate in the conflict we're diagnosing.
    """
    if isinstance(entry, dict):
        published = entry.get("published")
        if published is not None:
            return str(published)
        return ""
    if isinstance(entry, str):
        parts = entry.split(":")
        # "HOST:CONTAINER" → host is parts[0]; "IP:HOST:CONTAINER" → parts[1];
        # "CONTAINER" alone → no host binding (skip).
        if len(parts) == 2:
            return parts[0]
        if len(parts) == 3:
            return parts[1]
    return ""


def _parse_compose_host_ports_regex(text: str) -> list[tuple[str, str]]:
    """Fallback when PyYAML is unavailable. Recognises the short-form
    ``"HOST:CONTAINER"`` string entries and associates them with the
    most recently seen ``^  <service>:`` line. Long-form dicts and
    unusual layouts return empty — acceptable degradation for a
    diagnostic helper."""
    host_ports: list[tuple[str, str]] = []
    current_service = ""
    in_services = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if line.startswith("services:"):
            in_services = True
            continue
        if in_services and re.match(r"^[A-Za-z_][\w-]*:\s*$", line):
            # top-level sibling key (e.g. "volumes:") — end of services block
            in_services = False
            continue
        if in_services and re.match(r"^ {2}[A-Za-z_][\w-]*:\s*$", line):
            current_service = stripped.rstrip(":")
            continue
        if not current_service:
            continue
        match = re.match(r'^\s*-\s*"?(?P<spec>[\d.:]+)"?\s*$', line)
        if match:
            host_port = _extract_host_port(match.group("spec"))
            if host_port:
                host_ports.append((current_service, host_port))
    return host_ports


def _detect_unbound_host_ports(
    project_root: Path, compose_file: Path
) -> list[tuple[str, str]]:
    """Return [(service, host_port)] for each declared host port that
    failed to bind after ``docker compose up``.

    Uses ``docker compose port <service> <container_port>`` for each
    declared mapping. An empty return string means compose brought up
    the container network-internally only — i.e., another process on
    the host already owns the port. Container-only declarations (no
    host binding) are excluded at parse time.
    """
    declared = _parse_compose_host_ports(compose_file)
    if not declared:
        return []

    unbound: list[tuple[str, str]] = []
    for service, host_port in declared:
        # `docker compose port` prints "0.0.0.0:<published>" if bound, nothing
        # if not. We don't know the container port from the host port alone,
        # so inspect the container directly for its NetworkSettings.Ports.
        try:
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(compose_file),
                    "ps",
                    "--format",
                    "{{.Name}}",
                    service,
                ],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            continue
        container_name = (result.stdout or "").strip().splitlines()
        if not container_name:
            continue
        name = container_name[0]
        try:
            inspect = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{json .NetworkSettings.Ports}}",
                    name,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            continue
        if inspect.returncode != 0:
            continue
        payload = (inspect.stdout or "").strip()
        try:
            ports_map = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            continue
        if not isinstance(ports_map, dict):
            continue
        bound_host_ports: set[str] = set()
        for bindings in ports_map.values():
            if not isinstance(bindings, list):
                continue
            for binding in bindings:
                if isinstance(binding, dict) and binding.get("HostPort"):
                    bound_host_ports.add(str(binding["HostPort"]))
        if host_port not in bound_host_ports:
            unbound.append((service, host_port))
    return unbound


def _containers_running(project_root: Path, compose_file: Path) -> bool:
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "ps", "--status=running", "-q"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _restart_api_process(project_root: Path, compose_file: Path) -> None:
    for service_name in ("api", "backend", "app"):
        try:
            subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "restart", service_name],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return
        except Exception:
            continue


def _stop_containers(project_root: Path, compose_file: Optional[Path] = None) -> None:
    try:
        command = ["docker", "compose"]
        if compose_file is not None:
            command.extend(["-f", str(compose_file)])
        command.append("down")
        subprocess.run(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        pass


def stop_docker_containers(cwd: str) -> None:
    project_root = Path(cwd)
    compose_file = find_compose_file(project_root)
    _stop_containers(project_root, compose_file)


def _detect_runtime_infra(project_root: Path, config: Any) -> Any:
    """Phase F §7.5: run infra_detector and return a RuntimeInfra snapshot.

    Returns ``None`` when detection is disabled via
    ``v18.runtime_infra_detection_enabled`` or when the module import
    fails (defensive — the detector is additive, a failure here must
    not break probing).
    """
    try:
        from .infra_detector import detect_runtime_infra
    except Exception:  # pragma: no cover — defensive
        return None
    try:
        return detect_runtime_infra(project_root, config=config)
    except Exception:  # pragma: no cover — defensive
        return None


def _detect_app_url(project_root: Path, config: Any) -> str:
    # 1. config.browser_testing.app_port (highest precedence)
    port = getattr(getattr(config, "browser_testing", None), "app_port", 0) if config else 0
    if port:
        return f"http://localhost:{int(port)}"

    # 2. <root>/.env PORT=<n>
    port = _port_from_env_file(project_root / ".env")
    if port:
        return f"http://localhost:{port}"

    # 3. <root>/apps/api/.env.example PORT=<n>
    port = _port_from_env_file(project_root / "apps" / "api" / ".env.example")
    if port:
        return f"http://localhost:{port}"

    # 4. <root>/apps/api/src/main.ts app.listen(<port>)
    port = _port_from_main_ts(project_root / "apps" / "api" / "src" / "main.ts")
    if port:
        return f"http://localhost:{port}"

    # 5. <root>/docker-compose.yml services.api.ports first mapping
    port = _port_from_compose(project_root / "docker-compose.yml")
    if port:
        return f"http://localhost:{port}"

    # 6. Loud fallback — previous behavior was silent
    logger.warning(
        "endpoint_prober: no PORT detected in config.browser_testing.app_port, "
        ".env, apps/api/.env.example, apps/api/src/main.ts, or docker-compose.yml; "
        "falling back to http://localhost:3080 (N-01)"
    )
    return "http://localhost:3080"


def _port_from_env_file(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"^\s*PORT\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    if match:
        return int(match.group(1))
    return None


def _port_from_main_ts(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # app.listen(4000) or app.listen(process.env.PORT ?? 4000) or app.listen(PORT, ...)
    for pattern in (
        r"\.listen\s*\(\s*process\.env\.PORT\s*\?\?\s*(\d+)",
        r"\.listen\s*\(\s*process\.env\.PORT\s*\|\|\s*(\d+)",
        r"\.listen\s*\(\s*(\d+)\b",
    ):
        m = re.search(pattern, text)
        if m:
            return int(m.group(1))
    return None


def _port_from_compose(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    services = data.get("services") or {}
    api = services.get("api") if isinstance(services, dict) else None
    if not isinstance(api, dict):
        return None
    ports = api.get("ports") or []
    if not isinstance(ports, list):
        return None
    for entry in ports:
        if isinstance(entry, str):
            # "4000:4000" or "127.0.0.1:4000:4000" — host port is the PENULTIMATE number
            parts = entry.split(":")
            try:
                return int(parts[-2]) if len(parts) >= 2 else None
            except (ValueError, TypeError):
                continue
        if isinstance(entry, dict):
            published = entry.get("published")
            if isinstance(published, (int, str)):
                try:
                    return int(published)
                except (ValueError, TypeError):
                    continue
    return None


async def _poll_health(app_url: str, timeout: int = 60) -> bool:
    base_url = app_url.rstrip("/")
    health_paths = ["/api/health", "/health", "/", "/api"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for path in health_paths:
            try:
                request = urllib.request.Request(base_url + path, method="GET")
                with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310
                    if response.status < 500:
                        return True
            except urllib.error.HTTPError as exc:
                if exc.code < 500:
                    return True
            except Exception:
                continue
        await asyncio.sleep(1)
    return False


async def reset_db_and_seed(cwd: str) -> bool:
    """Reset the database to a deterministic seed state."""

    project_root = Path(cwd)
    compose_file = find_compose_file(project_root)

    try:
        if (project_root / "prisma" / "schema.prisma").is_file():
            reset_result = subprocess.run(
                ["npx", "prisma", "migrate", "reset", "--force", "--skip-seed"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if reset_result.returncode != 0:
                logger.warning("Prisma reset failed: %s", (reset_result.stderr or "")[:300])
                return False
        elif compose_file is not None:
            if not await _truncate_tables(project_root, compose_file):
                logger.warning("Database truncate failed during DB reset")
                return False
            migration_ok, migration_error = run_migrations(project_root, compose_file)
            if not migration_ok:
                logger.warning("Migration rerun failed during DB reset: %s", migration_error)
                return False

        if not _run_seed(project_root):
            return False
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("DB reset failed: %s", exc, exc_info=True)
        return False


async def _truncate_tables(project_root: Path, compose_file: Path) -> bool:
    from .runtime_verification import _retry_docker_op

    candidate_services = ("postgres", "db", "database")
    truncate_sql = (
        "DO $$ DECLARE r RECORD; BEGIN "
        "FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP "
        "EXECUTE 'TRUNCATE TABLE ' || quote_ident(r.tablename) || ' RESTART IDENTITY CASCADE'; "
        "END LOOP; END $$;"
    )
    for service_name in candidate_services:
        def _truncate_op(svc: str = service_name) -> tuple[int, str, str]:
            try:
                result = subprocess.run(
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "exec",
                        "-T",
                        svc,
                        "psql",
                        "-U",
                        "postgres",
                        "-d",
                        "postgres",
                        "-c",
                        truncate_sql,
                    ],
                    cwd=str(project_root),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return (result.returncode, result.stdout or "", result.stderr or "")
            except Exception as exc:
                # Surface the exception text in stderr so the retry classifier
                # can decide; subprocess.TimeoutExpired etc. won't match a
                # transient daemon error and so won't be retried — same as
                # before.
                return (1, "", str(exc))

        # Retry transient Docker daemon failures on the truncate exec call (PR #9).
        rc, _, _ = _retry_docker_op(_truncate_op, op_name="compose exec truncate")
        if rc == 0:
            return True
    return False


def _run_seed(project_root: Path) -> bool:
    if (project_root / "prisma").is_dir():
        seed_result = subprocess.run(
            ["npx", "prisma", "db", "seed"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if seed_result.returncode == 0:
            return True
        logger.warning("Prisma seed failed: %s", (seed_result.stderr or "")[:300])

    seed_ok, seed_error = run_seed_scripts(project_root)
    if not seed_ok and seed_error:
        logger.warning("Seed script rerun failed during DB reset: %s", seed_error)
        return False
    return True


async def execute_probes(
    manifest: ProbeManifest,
    docker_ctx: DockerContext,
    cwd: str,
) -> ProbeManifest:
    """Execute probes against the running application."""

    del cwd
    manifest.results = []
    manifest.failures = []
    manifest.happy_pass = 0
    manifest.happy_fail = 0
    manifest.negative_pass = 0
    manifest.negative_fail = 0

    if not docker_ctx.api_healthy:
        logger.warning("Skipping probes because API is not healthy")
        return manifest

    http_client = _get_http_client()
    base_url = docker_ctx.app_url.rstrip("/")

    # Phase F §7.5: honor any detected api_prefix (e.g. NestJS
    # setGlobalPrefix('api') turns /health into /api/health). When no
    # prefix is detected ``build_probe_url`` falls through to the
    # pre-Phase-F concatenation shape byte-identically.
    try:
        from .infra_detector import build_probe_url as _build_probe_url
    except Exception:  # pragma: no cover — defensive
        _build_probe_url = None
    infra = docker_ctx.runtime_infra

    try:
        for probe in manifest.probes:
            result = ProbeResult(spec=probe)
            if _build_probe_url is not None:
                base_with_prefix = _build_probe_url(
                    base_url, "", infra=infra,
                )
                url = _resolve_path(
                    base_with_prefix.rstrip("/") + probe.path,
                    probe.path_params,
                )
            else:
                url = _resolve_path(base_url + probe.path, probe.path_params)
            try:
                start = time.monotonic()
                response = await http_client.request(
                    method=probe.method,
                    url=url,
                    json_body=probe.request_body,
                    headers=probe.headers,
                    timeout=10,
                )
                result.actual_status = response.status_code
                result.response_body = response.text
                result.duration_ms = (time.monotonic() - start) * 1000
                result.passed = result.actual_status == probe.expected_status
            except Exception as exc:  # pragma: no cover - defensive
                result.error = str(exc)
                result.passed = False

            manifest.results.append(result)
            if not result.passed:
                manifest.failures.append(result)

        for probe_result in manifest.results:
            if probe_result.spec.probe_type == "happy_path":
                if probe_result.passed:
                    manifest.happy_pass += 1
                else:
                    manifest.happy_fail += 1
            else:
                if probe_result.passed:
                    manifest.negative_pass += 1
                else:
                    manifest.negative_fail += 1
    finally:
        close = getattr(http_client, "aclose", None)
        if callable(close):
            await close()

    return manifest


class _StdlibResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


class _StdlibHttpClient:
    async def request(
        self,
        *,
        method: str,
        url: str,
        json_body: Optional[dict[str, Any]],
        headers: dict[str, str],
        timeout: int,
    ) -> _StdlibResponse:
        return await asyncio.to_thread(
            self._request_sync,
            method,
            url,
            json_body,
            headers,
            timeout,
        )

    def _request_sync(
        self,
        method: str,
        url: str,
        json_body: Optional[dict[str, Any]],
        headers: dict[str, str],
        timeout: int,
    ) -> _StdlibResponse:
        payload = None
        request_headers = dict(headers)
        if json_body is not None:
            payload = json.dumps(json_body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        request = urllib.request.Request(url, data=payload, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8", errors="replace")
                return _StdlibResponse(response.status, body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return _StdlibResponse(exc.code, body)


class _HttpxClient:
    def __init__(self) -> None:
        import httpx

        self._client = httpx.AsyncClient()

    async def request(
        self,
        *,
        method: str,
        url: str,
        json_body: Optional[dict[str, Any]],
        headers: dict[str, str],
        timeout: int,
    ) -> Any:
        response = await self._client.request(
            method=method,
            url=url,
            json=json_body,
            headers=headers,
            timeout=timeout,
        )
        return type(
            "HttpxResponse",
            (),
            {
                "status_code": response.status_code,
                "text": response.text,
            },
        )()

    async def aclose(self) -> None:
        await self._client.aclose()


def _get_http_client() -> Any:
    try:
        import httpx  # noqa: F401
    except Exception:
        return _StdlibHttpClient()
    return _HttpxClient()


def _resolve_path(path: str, path_params: dict[str, str]) -> str:
    resolved = path
    for key, value in path_params.items():
        resolved = resolved.replace(f":{key}", str(value))
        resolved = resolved.replace(f"{{{key}}}", str(value))
    return resolved


def collect_probe_evidence(manifest: ProbeManifest, cwd: str) -> list[tuple[str, Any]]:
    """Convert probe results into http-transcript evidence records."""

    from .evidence_ledger import EvidenceRecord, map_endpoint_to_acs

    evidence_pairs: list[tuple[str, Any]] = []
    for result in manifest.results:
        ac_ids = map_endpoint_to_acs(result.spec.method, result.spec.path, cwd)
        for ac_id in ac_ids:
            evidence_pairs.append(
                (
                    ac_id,
                    EvidenceRecord(
                        type="http_transcript",
                        content=json.dumps(
                            {
                                "method": result.spec.method,
                                "path": result.spec.path,
                                "probe_type": result.spec.probe_type,
                                "expected_status": result.spec.expected_status,
                                "actual_status": result.actual_status,
                                "passed": result.passed,
                                "duration_ms": result.duration_ms,
                                "error": result.error,
                            },
                            ensure_ascii=False,
                        ),
                        source="wave_b_probe",
                        timestamp=_now_iso(),
                    ),
                )
            )
    return evidence_pairs


async def collect_db_assertion_evidence(
    manifest: ProbeManifest,
    docker_ctx: DockerContext,
    cwd: str,
) -> list[tuple[str, Any]]:
    """Generate db-assertion evidence after successful mutation probes."""

    from .evidence_ledger import EvidenceRecord, map_endpoint_to_acs

    del docker_ctx
    evidence_pairs: list[tuple[str, Any]] = []
    for result in manifest.results:
        if not result.passed:
            continue
        if result.spec.probe_type != "happy_path":
            continue
        if result.spec.method not in {"POST", "PUT", "PATCH"}:
            continue

        db_check = await _verify_db_mutation(result.spec, result.response_body, cwd)
        if not db_check:
            continue

        ac_ids = map_endpoint_to_acs(result.spec.method, result.spec.path, cwd)
        for ac_id in ac_ids:
            evidence_pairs.append(
                (
                    ac_id,
                    EvidenceRecord(
                        type="db_assertion",
                        content=json.dumps(db_check, ensure_ascii=False),
                        source="wave_b_probe_db_check",
                        timestamp=_now_iso(),
                    ),
                )
            )
    return evidence_pairs


async def _verify_db_mutation(
    probe_spec: ProbeSpec,
    response_body: str,
    cwd: str,
) -> Optional[dict[str, Any]]:
    try:
        parsed = json.loads(response_body)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None

    record_id = _extract_response_id(parsed)
    if record_id is None:
        return None

    project_root = Path(cwd)
    target = _select_prisma_table(project_root, parsed)
    if not target:
        return None

    runtime = _discover_db_runtime(project_root)
    table_name = str(target.get("table", "") or "").strip()
    if not table_name:
        return None

    if _query_via_prisma(runtime.get("api_container", ""), table_name, record_id, project_root):
        return {
            "method": probe_spec.method,
            "path": probe_spec.path,
            "table": table_name,
            "record_id": str(record_id),
            "verification_method": "prisma",
            "verified": True,
        }

    if _query_via_direct_sql(
        runtime.get("db_container", ""),
        runtime.get("db_user", ""),
        runtime.get("db_name", ""),
        runtime.get("db_password", ""),
        table_name,
        record_id,
        project_root,
    ):
        return {
            "method": probe_spec.method,
            "path": probe_spec.path,
            "table": table_name,
            "record_id": str(record_id),
            "verification_method": "direct_sql",
            "verified": True,
        }

    return None


def _extract_response_id(payload: dict[str, Any]) -> str | None:
    for key in ("id", "uuid"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)

    nested = payload.get("data")
    if isinstance(nested, dict):
        for key in ("id", "uuid"):
            value = nested.get(key)
            if value not in (None, ""):
                return str(value)

    return None


def _select_prisma_table(project_root: Path, payload: dict[str, Any]) -> dict[str, Any] | None:
    schema_path = project_root / "prisma" / "schema.prisma"
    if not schema_path.is_file():
        return None

    try:
        schema_text = schema_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    models = _parse_prisma_models(schema_text)
    if not models:
        return None

    response_fields = {
        key
        for key, value in payload.items()
        if not isinstance(value, (dict, list))
    }
    nested = payload.get("data")
    if isinstance(nested, dict):
        response_fields.update(nested.keys())

    scored: list[tuple[int, dict[str, Any]]] = []
    for model in models:
        fields = set(model.get("fields", []))
        if "id" not in fields:
            continue
        overlap = {
            field
            for field in response_fields & fields
            if field not in {"id", "createdAt", "updatedAt", "created_at", "updated_at"}
        }
        scored.append((len(overlap), model))

    if not scored:
        return models[0] if len(models) == 1 else None

    best_score = max(score for score, _ in scored)
    if best_score <= 0:
        return scored[0][1] if len(scored) == 1 else None

    best_models = [model for score, model in scored if score == best_score]
    if len(best_models) != 1:
        return None
    return best_models[0]


def _parse_prisma_models(schema_text: str) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for match in re.finditer(r"^\s*model\s+(\w+)\s*\{(.*?)^\s*\}", schema_text, re.MULTILINE | re.DOTALL):
        name = match.group(1)
        body = match.group(2)
        table_name = name
        table_match = re.search(r'@@map\(\s*"([^"]+)"\s*\)', body)
        if table_match:
            table_name = table_match.group(1)

        fields: set[str] = set()
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("@@"):
                continue
            field_match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s+[A-Za-z_][A-Za-z0-9_\[\]\?]*", stripped)
            if field_match:
                fields.add(field_match.group(1))

        models.append({"model": name, "table": table_name, "fields": sorted(fields)})
    return models


def _discover_db_runtime(project_root: Path) -> dict[str, str]:
    env_values = _load_env_values(project_root / ".env")
    compose_file = find_compose_file(project_root)
    compose_text = ""
    if compose_file is not None:
        try:
            compose_text = compose_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            compose_text = ""

    db_url = env_values.get("DATABASE_URL") or _extract_compose_value(
        compose_text,
        ("DATABASE_URL",),
        env_values,
    )
    parsed_db_url = _parse_database_url(db_url) if db_url else {}

    db_user = (
        env_values.get("POSTGRES_USER")
        or env_values.get("DB_USER")
        or parsed_db_url.get("user", "")
        or _extract_compose_value(compose_text, ("POSTGRES_USER", "DB_USER"), env_values)
    )
    db_name = (
        env_values.get("POSTGRES_DB")
        or env_values.get("DB_NAME")
        or parsed_db_url.get("database", "")
        or _extract_compose_value(compose_text, ("POSTGRES_DB", "DB_NAME"), env_values)
    )
    db_password = (
        env_values.get("POSTGRES_PASSWORD")
        or env_values.get("DB_PASSWORD")
        or parsed_db_url.get("password", "")
        or _extract_compose_value(compose_text, ("POSTGRES_PASSWORD", "DB_PASSWORD"), env_values)
    )

    service_blocks = _parse_compose_service_blocks(compose_text)
    api_service = next(
        (
            name
            for name in service_blocks
            if name.lower() in {"api", "backend", "app", "server"}
        ),
        "",
    )
    db_service = next(
        (
            name
            for name, block in service_blocks.items()
            if "postgres" in block.lower()
            or name.lower() in {"db", "database", "postgres", "postgresql"}
        ),
        "",
    )

    api_container = _find_container_name(compose_file, api_service) if compose_file and api_service else api_service
    db_container = _find_container_name(compose_file, db_service) if compose_file and db_service else db_service

    return {
        "api_container": api_container,
        "db_container": db_container,
        "db_user": db_user,
        "db_name": db_name,
        "db_password": db_password,
    }


def _load_env_values(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    try:
        text = env_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _parse_database_url(database_url: str) -> dict[str, str]:
    try:
        parsed = urlparse(database_url)
    except Exception:
        return {}

    return {
        "user": parsed.username or "",
        "password": parsed.password or "",
        "database": parsed.path.lstrip("/") if parsed.path else "",
    }


def _extract_compose_value(compose_text: str, keys: tuple[str, ...], env_values: dict[str, str]) -> str:
    if not compose_text:
        return ""

    for key in keys:
        match = re.search(
            rf"{re.escape(key)}\s*[:=]\s*(?:\$\{{(?P<env>[A-Za-z_][A-Za-z0-9_]*)\}}|(?P<value>[^#\s]+))",
            compose_text,
        )
        if not match:
            continue
        env_key = match.group("env")
        if env_key:
            return env_values.get(env_key, "")
        value = match.group("value")
        if value:
            return value.strip().strip("'\"")
    return ""


def _parse_compose_service_blocks(compose_text: str) -> dict[str, str]:
    if not compose_text:
        return {}

    blocks: dict[str, str] = {}
    lines = compose_text.splitlines()
    in_services = False
    service_indent: int | None = None
    current_name = ""
    current_lines: list[str] = []

    for line in lines:
        if not in_services:
            if re.match(r"^\s*services:\s*$", line):
                in_services = True
            continue

        stripped = line.strip()
        if not stripped and current_name:
            current_lines.append(line)
            continue

        indent = len(line) - len(line.lstrip(" "))
        if service_indent is None and stripped:
            service_indent = indent
        if service_indent is None:
            continue
        if stripped and indent < service_indent:
            break

        match = re.match(rf"^\s{{{service_indent}}}([A-Za-z0-9_.-]+):\s*$", line)
        if match:
            if current_name:
                blocks[current_name] = "\n".join(current_lines)
            current_name = match.group(1)
            current_lines = []
            continue

        if current_name:
            current_lines.append(line)

    if current_name:
        blocks[current_name] = "\n".join(current_lines)
    return blocks


def _query_via_prisma(api_container: str, table_name: str, record_id: str, project_root: Path) -> bool:
    if not api_container:
        return False

    sql = (
        f"SELECT id FROM {_quote_identifier(table_name)} "
        f"WHERE CAST(id AS text) = {_quote_literal(record_id)} LIMIT 1;"
    )
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                api_container,
                "npx",
                "prisma",
                "db",
                "execute",
                "--stdin",
                "--schema",
                "prisma/schema.prisma",
            ],
            input=sql,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(project_root),
        )
    except Exception as exc:
        logger.warning("Prisma db_assertion query failed: %s", exc)
        return False

    if result.returncode != 0:
        return False
    output = f"{result.stdout}\n{result.stderr}".strip()
    return bool(record_id and record_id in output)


def _query_via_direct_sql(
    db_container: str,
    db_user: str,
    db_name: str,
    db_password: str,
    table_name: str,
    record_id: str,
    project_root: Path,
) -> bool:
    if not db_container or not db_user or not db_name:
        return False

    sql = (
        f"SELECT COUNT(*) FROM {_quote_identifier(table_name)} "
        f"WHERE CAST(id AS text) = {_quote_literal(record_id)};"
    )
    command = ["docker", "exec"]
    if db_password:
        command.extend(["-e", f"PGPASSWORD={db_password}"])
    command.extend(
        [
            db_container,
            "psql",
            "-U",
            db_user,
            "-d",
            db_name,
            "-t",
            "-A",
            "-c",
            sql,
        ]
    )

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(project_root),
        )
    except Exception as exc:
        logger.warning("Direct SQL db_assertion query failed: %s", exc)
        return False

    if result.returncode != 0:
        return False
    output = (result.stdout or "").strip()
    match = re.search(r"(\d+)", output)
    return bool(match and int(match.group(1)) > 0)


def _quote_identifier(identifier: str) -> str:
    return ".".join(f'"{part.replace(chr(34), chr(34) * 2)}"' for part in identifier.split(".") if part)


def _quote_literal(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


async def collect_simulator_evidence(cwd: str) -> list[tuple[str, Any]]:
    """Read adapter simulator state files into simulator-state evidence."""

    from .evidence_ledger import EvidenceRecord, map_integration_to_acs

    evidence_pairs: list[tuple[str, Any]] = []
    simulators_dir = Path(cwd) / "apps" / "api" / "src" / "integrations"
    if not simulators_dir.exists():
        return evidence_pairs

    for state_file in simulators_dir.rglob("*.simulator-state.json"):
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read simulator state %s: %s", state_file, exc)
            continue

        vendor = str(state.get("vendor", state_file.parent.name))
        for call in list(state.get("recorded_calls", []) or []):
            ac_ids = map_integration_to_acs(vendor, str(call.get("method", "")), cwd)
            for ac_id in ac_ids:
                evidence_pairs.append(
                    (
                        ac_id,
                        EvidenceRecord(
                            type="simulator_state",
                            content=json.dumps({"vendor": vendor, "call": call}, ensure_ascii=False),
                            source=f"simulator_{vendor}",
                            timestamp=_now_iso(),
                        ),
                    )
                )
    return evidence_pairs


def format_probe_failures_for_fix(manifest: ProbeManifest) -> str:
    """Render probe failures into a focused Wave B.1 fix prompt section."""

    if not manifest.failures:
        return ""

    lines = [
        f"[ENDPOINT PROBE FAILURES - {len(manifest.failures)} of {manifest.total_probes} probes failed]",
        "",
    ]
    for failure in manifest.failures:
        lines.append(f"{failure.spec.probe_type}: {failure.spec.method} {failure.spec.path}")
        lines.append(
            f"Expected {failure.spec.expected_status}, got {failure.actual_status or 'request error'}"
        )
        if failure.error:
            lines.append(f"Error: {failure.error}")
        if failure.response_body:
            lines.append(f"Response: {failure.response_body[:200]}")
        lines.append("")

    lines.append("Fix these endpoint issues. Read the controller and service code before editing.")
    return "\n".join(lines)


def save_probe_telemetry(manifest: ProbeManifest, cwd: str, milestone_id: str) -> str:
    """Persist probe telemetry for gating and later regression checks."""

    telemetry_dir = Path(cwd) / ".agent-team" / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    path = telemetry_dir / f"{milestone_id}-probes.json"
    payload = {
        "milestone_id": milestone_id,
        "total_probes": manifest.total_probes,
        "happy_pass": manifest.happy_pass,
        "happy_fail": manifest.happy_fail,
        "negative_pass": manifest.negative_pass,
        "negative_fail": manifest.negative_fail,
        "probes": [asdict(probe) for probe in manifest.probes],
        "results": [
            {
                "spec": asdict(result.spec),
                "actual_status": result.actual_status,
                "passed": result.passed,
                "response_body": result.response_body,
                "duration_ms": result.duration_ms,
                "error": result.error,
            }
            for result in manifest.results
        ],
        "failures": [
            {
                "spec": asdict(result.spec),
                "actual_status": result.actual_status,
                "passed": result.passed,
                "response_body": result.response_body,
                "duration_ms": result.duration_ms,
                "error": result.error,
            }
            for result in manifest.failures
        ],
        "timestamp": _now_iso(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def save_probe_manifest(manifest: ProbeManifest, cwd: str, milestone_id: str) -> str:
    """Persist the full probe specification set for later re-execution."""

    from .evidence_ledger import map_endpoint_to_acs

    resolved_milestone_id = str(milestone_id or manifest.milestone_id or "current").strip() or "current"
    telemetry_dir = Path(cwd) / ".agent-team" / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    path = telemetry_dir / f"{resolved_milestone_id}-probe-manifest.json"
    payload = {
        "milestone_id": resolved_milestone_id,
        "probes": [
            {
                "endpoint": probe.endpoint,
                "method": probe.method,
                "path": probe.path,
                "probe_type": probe.probe_type,
                "expected_status": probe.expected_status,
                "request_body": probe.request_body,
                "headers": probe.headers,
                "path_params": probe.path_params,
                "description": probe.description,
                "mapped_ac_ids": map_endpoint_to_acs(probe.method, probe.path, cwd),
            }
            for probe in manifest.probes
        ],
        "timestamp": _now_iso(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


__all__ = [
    "DockerContext",
    "ProbeManifest",
    "ProbeResult",
    "ProbeSpec",
    "collect_db_assertion_evidence",
    "collect_probe_evidence",
    "collect_simulator_evidence",
    "execute_probes",
    "format_probe_failures_for_fix",
    "generate_probe_manifest",
    "load_seed_fixtures",
    "reset_db_and_seed",
    "save_probe_manifest",
    "save_probe_telemetry",
    "start_docker_for_probing",
    "stop_docker_containers",
]
