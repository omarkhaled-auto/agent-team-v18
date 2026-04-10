"""OpenAPI contract generation and client packaging for Wave C.

This module is intentionally standalone from the wave executor. It owns:

1. OpenAPI spec generation
2. Milestone-local scoping from Wave B module artifacts
3. Cumulative-vs-previous diffing for breaking changes
4. Client generation from the cumulative spec
5. Regex fallback when a project-level OpenAPI script is unavailable

Phase 2 scope only:
- No live endpoint probing
- No Docker startup
- No evidence gating
- No Phase 3/4 runtime behavior
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")
_SCRIPT_CANDIDATES = (
    "scripts/generate-openapi.ts",
    "scripts/generate-openapi.js",
    "scripts/generate-openapi.mjs",
)


@dataclass
class ContractResult:
    """Wave C contract generation result."""

    success: bool = True
    milestone_spec_path: str = ""
    cumulative_spec_path: str = ""
    client_exports: list[str] = field(default_factory=list)
    breaking_changes: list[str] = field(default_factory=list)
    endpoints_summary: list[dict[str, Any]] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    error_message: str = ""


def generate_openapi_contracts(cwd: str, milestone: Any) -> ContractResult:
    """Generate milestone-local and cumulative OpenAPI artifacts for Wave C."""

    result = ContractResult()
    project_root = Path(cwd)
    contracts_dir = project_root / "contracts" / "openapi"
    contracts_dir.mkdir(parents=True, exist_ok=True)

    spec_result = _generate_openapi_specs(project_root, milestone, contracts_dir)
    if not spec_result.get("success"):
        logger.warning(
            "OpenAPI script generation unavailable for %s: %s. Falling back to regex extraction.",
            getattr(milestone, "id", ""),
            spec_result.get("error", "unknown error"),
        )
        result.error_message = str(spec_result.get("error", "OpenAPI generation failed"))
        return _fallback_to_regex_extraction(cwd, milestone, result)

    result.milestone_spec_path = str(spec_result.get("milestone_spec_path", "") or "")
    result.cumulative_spec_path = str(spec_result.get("cumulative_spec_path", "") or "")
    result.files_created.extend(list(spec_result.get("files", []) or []))

    result.breaking_changes = _diff_cumulative_specs(contracts_dir)

    cumulative_spec = (
        Path(result.cumulative_spec_path)
        if result.cumulative_spec_path
        else contracts_dir / "current.json"
    )
    client_result = _generate_client_package(project_root, cumulative_spec)
    result.client_exports = list(client_result.get("exports", []) or [])
    result.files_created.extend(list(client_result.get("files", []) or []))

    if not client_result.get("success", True):
        result.success = False
        result.error_message = str(client_result.get("error", "Client generation failed"))

    summary_spec = _summary_spec_path(result, contracts_dir)
    result.endpoints_summary = _extract_endpoints_from_spec(summary_spec)
    _run_regex_crosscheck(project_root, milestone, result)

    if result.success and not cumulative_spec.exists():
        result.success = False
        result.error_message = "Cumulative spec not generated"

    result.files_created = sorted({path for path in result.files_created if path})
    return result


def _generate_openapi_specs(
    project_root: Path,
    milestone: Any,
    contracts_dir: Path,
) -> dict[str, Any]:
    """Prefer the project-level script. Fall back to regex generation if needed."""

    script_path = _find_generation_script(project_root)
    if script_path is None:
        return {"success": False, "error": "generate-openapi script not found"}

    module_files = _load_wave_b_module_files(project_root, getattr(milestone, "id", ""))
    env = _get_process_env(
        MILESTONE_ID=str(getattr(milestone, "id", "")),
        OUTPUT_DIR=str(contracts_dir),
        MILESTONE_MODULE_FILES=",".join(module_files),
    )

    command = _script_command(script_path)
    try:
        proc = subprocess.run(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "OpenAPI generation timed out (60s)"}
    except OSError as exc:
        return {"success": False, "error": str(exc)}

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        return {
            "success": False,
            "error": stderr[:500] or stdout[:500] or "OpenAPI generation failed",
        }

    cumulative_spec_path = contracts_dir / "current.json"
    milestone_spec_path = contracts_dir / f"{getattr(milestone, 'id', '')}.json"

    if not cumulative_spec_path.exists():
        return {"success": False, "error": "Cumulative spec not generated"}

    files_written = [_rel(project_root, cumulative_spec_path)]

    milestone_path_str = ""
    if module_files and milestone_spec_path.exists():
        milestone_path_str = str(milestone_spec_path)
        files_written.append(_rel(project_root, milestone_spec_path))
    elif not module_files and milestone_spec_path.exists():
        # Phase 2C rule: no Wave B module artifact -> cumulative-only output.
        try:
            milestone_spec_path.unlink()
        except OSError:
            logger.warning("Unable to remove unscoped milestone spec %s", milestone_spec_path)

    return {
        "success": True,
        "milestone_spec_path": milestone_path_str,
        "cumulative_spec_path": str(cumulative_spec_path),
        "files": files_written,
    }


def _find_generation_script(project_root: Path) -> Path | None:
    for candidate in _SCRIPT_CANDIDATES:
        path = project_root / candidate
        if path.exists():
            return path
    return None


def _script_command(script_path: Path) -> list[str]:
    suffix = script_path.suffix.lower()
    if suffix == ".ts":
        return ["npx", "ts-node", str(script_path)]
    return ["node", str(script_path)]


def _get_process_env(**extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update({key: value for key, value in extra.items() if value is not None})
    return env


def _load_wave_b_module_files(project_root: Path, milestone_id: str) -> list[str]:
    """Load actual module file paths from the Wave B artifact, not feature refs."""

    artifact_path = (
        project_root / ".agent-team" / "artifacts" / f"{milestone_id}-wave-B.json"
    )
    if not artifact_path.exists():
        return []

    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        logger.warning("Invalid Wave B artifact at %s", artifact_path)
        return []

    module_files = [
        _posix(path)
        for path in artifact.get("files_created", [])
        if isinstance(path, str)
        and path.endswith(".module.ts")
        and "app.module" not in path.replace("\\", "/").lower()
    ]
    return sorted(dict.fromkeys(module_files))


def _diff_cumulative_specs(contracts_dir: Path) -> list[str]:
    """Diff current cumulative spec against the previous cumulative version."""

    current_path = contracts_dir / "current.json"
    previous_path = contracts_dir / "previous.json"
    if not current_path.exists():
        return []

    if not previous_path.exists():
        try:
            shutil.copy2(current_path, previous_path)
        except OSError as exc:
            logger.warning("Unable to seed previous OpenAPI spec: %s", exc)
        return []

    try:
        old_spec = json.loads(previous_path.read_text(encoding="utf-8"))
        new_spec = json.loads(current_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logger.warning("Contract diff failed while reading specs: %s", exc)
        return []

    old_ops = _extract_operation_map(old_spec)
    new_ops = _extract_operation_map(new_spec)
    breaking_changes: list[str] = []

    for key in sorted(old_ops):
        if key not in new_ops:
            path, method = key
            breaking_changes.append(f"REMOVED: {method} {path}")

    for key in sorted(set(old_ops) & set(new_ops)):
        if _operation_signature(old_ops[key]) != _operation_signature(new_ops[key]):
            path, method = key
            breaking_changes.append(f"CHANGED: {method} {path}")

    try:
        shutil.copy2(current_path, previous_path)
    except OSError as exc:
        logger.warning("Unable to update previous OpenAPI spec: %s", exc)

    return breaking_changes


def _extract_operation_map(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    operations: dict[tuple[str, str], dict[str, Any]] = {}
    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            operations[(str(path), method.upper())] = operation
    return operations


def _operation_signature(operation: dict[str, Any]) -> str:
    stable_bits = {
        "parameters": operation.get("parameters", []),
        "requestBody": operation.get("requestBody", {}),
        "responses": operation.get("responses", {}),
    }
    return json.dumps(stable_bits, sort_keys=True, separators=(",", ":"))


def _generate_client_package(project_root: Path, spec_path: Path) -> dict[str, Any]:
    """Generate a typed client from the cumulative spec."""

    if not spec_path.exists():
        return {"success": False, "exports": [], "files": [], "error": "Spec not found"}

    orval_config = _find_orval_config(project_root)
    if orval_config and shutil.which("npx"):
        try:
            proc = subprocess.run(
                ["npx", "orval", "--config", str(orval_config)],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode == 0:
                client_dir = project_root / "packages" / "api-client"
                exports = _scan_client_exports(client_dir)
                files = _scan_client_files(project_root, client_dir)
                if exports or files:
                    return {
                        "success": True,
                        "exports": exports,
                        "files": files,
                    }
                logger.warning("Orval completed without producing client files; using minimal client fallback")
            logger.warning("Orval generation failed: %s", (proc.stderr or "")[:500])
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Orval generation failed: %s", exc)

    return _generate_minimal_ts_client(project_root, spec_path)


def _find_orval_config(project_root: Path) -> Path | None:
    for name in ("orval.config.ts", "orval.config.js", "orval.config.cjs", "orval.config.mjs"):
        path = project_root / name
        if path.exists():
            return path
    return None


def _generate_minimal_ts_client(project_root: Path, spec_path: Path) -> dict[str, Any]:
    """Write a small generated TypeScript client when Orval is unavailable."""

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return {"success": False, "exports": [], "files": [], "error": str(exc)}

    client_dir = project_root / "packages" / "api-client"
    client_dir.mkdir(parents=True, exist_ok=True)

    types_path = client_dir / "types.ts"
    index_path = client_dir / "index.ts"
    package_json_path = client_dir / "package.json"

    type_lines = _render_types_file(spec)
    client_lines, exports = _render_client_file(spec)
    package_json = {
        "name": "@project/api-client",
        "private": True,
        "version": "0.0.0",
        "type": "module",
        "main": "./index.ts",
        "types": "./index.ts",
    }

    files = [
        _write_text(project_root, types_path, "\n".join(type_lines) + "\n"),
        _write_text(project_root, index_path, "\n".join(client_lines) + "\n"),
        _write_text(project_root, package_json_path, json.dumps(package_json, indent=2) + "\n"),
    ]

    return {
        "success": True,
        "exports": exports,
        "files": files,
    }


def _render_types_file(spec: dict[str, Any]) -> list[str]:
    schemas = (((spec.get("components") or {}).get("schemas")) or {})
    lines = [
        "// Generated by agent_team_v15.openapi_generator",
        "",
    ]
    for name in sorted(schemas):
        schema = schemas[name]
        if not isinstance(schema, dict):
            continue
        if schema.get("enum"):
            values = " | ".join(json.dumps(value) for value in schema.get("enum", []))
            lines.append(f"export type {name} = {values or 'string'};")
            lines.append("")
            continue

        if schema.get("type") == "object" or schema.get("properties"):
            lines.append(f"export interface {name} {{")
            required = set(schema.get("required", []) or [])
            properties = schema.get("properties", {}) or {}
            for prop_name, prop_schema in properties.items():
                ts_type = _schema_to_ts_type(prop_schema)
                optional = "" if prop_name in required else "?"
                lines.append(f"  {prop_name}{optional}: {ts_type};")
            lines.append("}")
            lines.append("")
            continue

        lines.append(f"export type {name} = {_schema_to_ts_type(schema)};")
        lines.append("")

    if len(lines) == 2:
        lines.append("export type ApiClientNever = never;")
    return lines


def _render_client_file(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    exports: list[str] = []
    lines = [
        "// Generated by agent_team_v15.openapi_generator",
        "export * from './types';",
        "",
        "export interface RequestOptions {",
        "  baseUrl?: string;",
        "  init?: RequestInit;",
        "}",
        "",
        "async function request<T>(",
        "  method: string,",
        "  path: string,",
        "  args: { query?: Record<string, unknown>; body?: unknown } = {},",
        "  options: RequestOptions = {},",
        "): Promise<T> {",
        "  const baseUrl = (options.baseUrl || '').replace(/\\/$/, '');",
        "  const url = new URL(baseUrl + path, typeof window !== 'undefined' ? window.location.origin : 'http://localhost');",
        "  if (args.query) {",
        "    for (const [key, value] of Object.entries(args.query)) {",
        "      if (value !== undefined && value !== null) {",
        "        url.searchParams.set(key, String(value));",
        "      }",
        "    }",
        "  }",
        "  const response = await fetch(url.toString(), {",
        "    method,",
        "    headers: args.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,",
        "    body: args.body !== undefined ? JSON.stringify(args.body) : undefined,",
        "    ...(options.init || {}),",
        "  });",
        "  if (!response.ok) {",
        "    throw new Error(`API request failed: ${response.status} ${response.statusText}`);",
        "  }",
        "  if (response.status === 204) {",
        "    return undefined as T;",
        "  }",
        "  return (await response.json()) as T;",
        "}",
        "",
    ]

    paths = spec.get("paths") or {}
    for path in sorted(paths):
        path_item = paths[path]
        if not isinstance(path_item, dict):
            continue
        for method in _HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            export_name = _operation_name(path, method.upper(), operation)
            exports.append(export_name)

            path_params = _path_parameter_names(path)
            query_params = _query_parameter_names(operation)
            has_body = "requestBody" in operation
            response_type = _response_ts_type(operation)

            arg_lines = ["{"]
            for param in path_params:
                arg_lines.append(f"  {param}: string;")
            if query_params:
                arg_lines.append("  query?: {")
                for param in query_params:
                    arg_lines.append(f"    {param}?: string | number | boolean;")
                arg_lines.append("  };")
            if has_body:
                arg_lines.append("  body?: unknown;")
            arg_lines.append("}")
            args_type = "\n".join(arg_lines)

            path_expr = _render_path_expression(path, path_params)
            lines.append(f"export async function {export_name}(")
            lines.append(f"  args: {args_type},")
            lines.append("  options: RequestOptions = {},")
            lines.append(f"): Promise<{response_type}> {{")
            lines.append(f"  return request<{response_type}>(")
            lines.append(f"    '{method.upper()}',")
            lines.append(f"    {path_expr},")
            lines.append("    {")
            if query_params:
                lines.append("      query: args.query,")
            if has_body:
                lines.append("      body: args.body,")
            lines.append("    },")
            lines.append("    options,")
            lines.append("  );")
            lines.append("}")
            lines.append("")

    return lines, exports


def _path_parameter_names(path: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(r"\{([^}]+)\}", path):
        names.append(match.group(1))
    return names


def _query_parameter_names(operation: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for parameter in operation.get("parameters", []) or []:
        if not isinstance(parameter, dict):
            continue
        if parameter.get("in") == "query" and parameter.get("name"):
            names.append(str(parameter["name"]))
    return names


def _render_path_expression(path: str, path_params: list[str]) -> str:
    if not path_params:
        return json.dumps(path)

    expression = path
    for param in path_params:
        expression = expression.replace("{" + param + "}", "${args." + param + "}")
    return "`" + expression + "`"


def _response_ts_type(operation: dict[str, Any]) -> str:
    responses = operation.get("responses") or {}
    for status_code in ("200", "201", "202", "204", "default"):
        response = responses.get(status_code)
        if not isinstance(response, dict):
            continue
        schema = _response_schema(response)
        if schema:
            return _schema_to_ts_type(schema)
        if status_code == "204":
            return "void"
    return "unknown"


def _response_schema(response: dict[str, Any]) -> dict[str, Any] | None:
    content = response.get("content") or {}
    app_json = content.get("application/json")
    if isinstance(app_json, dict) and isinstance(app_json.get("schema"), dict):
        return app_json["schema"]
    return None


def _operation_name(path: str, method: str, operation: dict[str, Any]) -> str:
    operation_id = str(operation.get("operationId", "") or "").strip()
    if operation_id:
        return _safe_identifier(operation_id)

    segments = [
        segment
        for segment in re.split(r"[/{}/_-]+", path)
        if segment and not segment.startswith(":")
    ]
    title = "".join(part[:1].upper() + part[1:] for part in segments)
    return _safe_identifier(method.lower() + title or method.lower() + "Request")


def _safe_identifier(value: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z_]", "", value)
    if not sanitized:
        sanitized = "apiRequest"
    if sanitized[0].isdigit():
        sanitized = "api_" + sanitized
    return sanitized


def _schema_to_ts_type(schema: dict[str, Any] | None) -> str:
    if not isinstance(schema, dict):
        return "unknown"

    ref = schema.get("$ref")
    if isinstance(ref, str) and ref:
        return ref.rsplit("/", 1)[-1]

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return " | ".join(json.dumps(value) for value in enum_values)

    schema_type = schema.get("type")
    if schema_type == "array":
        return f"{_schema_to_ts_type(schema.get('items'))}[]"
    if schema_type in {"integer", "number"}:
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "string":
        return "string"
    if schema_type == "object":
        properties = schema.get("properties") or {}
        required = set(schema.get("required", []) or [])
        if not properties:
            return "Record<string, unknown>"
        members = []
        for name, prop_schema in properties.items():
            optional = "" if name in required else "?"
            members.append(f"{name}{optional}: {_schema_to_ts_type(prop_schema)}")
        return "{ " + "; ".join(members) + " }"
    return "unknown"


def _scan_client_exports(client_dir: Path) -> list[str]:
    if not client_dir.exists():
        return []
    pattern = re.compile(
        r"export\s+(?:async\s+)?function\s+([A-Za-z_]\w*)|export\s+const\s+([A-Za-z_]\w*)\s*=",
    )
    exports: list[str] = []
    for path in sorted(client_dir.rglob("*.ts")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in pattern.finditer(text):
            name = match.group(1) or match.group(2)
            if name and name not in exports:
                exports.append(name)
    return exports


def _scan_client_files(project_root: Path, client_dir: Path) -> list[str]:
    if not client_dir.exists():
        return []
    return sorted(
        _rel(project_root, path)
        for path in client_dir.rglob("*")
        if path.is_file()
    )


def _fallback_to_regex_extraction(
    cwd: str,
    milestone: Any,
    result: ContractResult,
) -> ContractResult:
    """Fallback path when a project OpenAPI script is missing or fails."""

    try:
        bundle = _extract_api_bundle(Path(cwd), getattr(milestone, "id", ""))
    except Exception as exc:  # pragma: no cover - guarded for runtime safety
        result.success = False
        result.error_message = (
            f"{result.error_message}; regex extraction failed: {exc}".strip("; ")
        )
        return result

    project_root = Path(cwd)
    contracts_dir = project_root / "contracts" / "openapi"
    contracts_dir.mkdir(parents=True, exist_ok=True)

    cumulative_spec = _bundle_to_openapi(
        bundle,
        title=f"{getattr(milestone, 'title', getattr(milestone, 'id', 'Project'))} API",
        version="1.0.0",
    )
    current_path = contracts_dir / "current.json"
    result.files_created.append(_write_json(project_root, current_path, cumulative_spec))
    result.cumulative_spec_path = str(current_path)

    module_files = _load_wave_b_module_files(project_root, getattr(milestone, "id", ""))
    if module_files:
        scoped_bundle = _scope_bundle_to_modules(bundle, module_files)
        if scoped_bundle.get("endpoints"):
            milestone_spec = _bundle_dict_to_openapi(
                scoped_bundle,
                title=f"{getattr(milestone, 'title', getattr(milestone, 'id', 'Milestone'))} Milestone API",
                version="1.0.0",
            )
            milestone_path = contracts_dir / f"{getattr(milestone, 'id', '')}.json"
            result.files_created.append(_write_json(project_root, milestone_path, milestone_spec))
            result.milestone_spec_path = str(milestone_path)

    result.breaking_changes = _diff_cumulative_specs(contracts_dir)

    client_result = _generate_client_package(project_root, current_path)
    result.client_exports = list(client_result.get("exports", []) or [])
    result.files_created.extend(list(client_result.get("files", []) or []))
    result.endpoints_summary = _extract_endpoints_from_spec(
        _summary_spec_path(result, contracts_dir)
    )
    _run_regex_crosscheck(
        project_root,
        milestone,
        result,
        regex_summary=result.endpoints_summary,
    )

    if not client_result.get("success", True):
        result.success = False
        result.error_message = str(client_result.get("error", result.error_message))
    else:
        result.success = True
        result.error_message = ""
    result.files_created = sorted({path for path in result.files_created if path})
    return result


def _extract_api_bundle(project_root: Path, milestone_id: str) -> Any:
    try:
        from .api_contract_extractor import extract_api_contracts
    except ImportError:  # pragma: no cover - standalone import fallback
        from api_contract_extractor import extract_api_contracts

    return extract_api_contracts(project_root, milestone_id=milestone_id)


def _scope_bundle_to_modules(bundle: Any, module_files: list[str]) -> dict[str, Any]:
    """Scope milestone-local output using module file paths from Wave B artifacts."""

    scope_dirs = {str(Path(path).parent).replace("\\", "/") for path in module_files}
    endpoints: list[dict[str, Any]] = []

    for endpoint in getattr(bundle, "endpoints", []) or []:
        controller_file = _posix(getattr(endpoint, "controller_file", ""))
        if any(
            controller_file.startswith(scope_dir + "/") or controller_file == scope_dir
            for scope_dir in scope_dirs
        ):
            endpoints.append(
                {
                    "path": getattr(endpoint, "path", ""),
                    "method": getattr(endpoint, "method", ""),
                    "handler_name": getattr(endpoint, "handler_name", ""),
                    "controller_file": controller_file,
                    "request_params": list(getattr(endpoint, "request_params", []) or []),
                    "request_body_fields": list(
                        getattr(endpoint, "request_body_fields", []) or []
                    ),
                    "response_fields": list(getattr(endpoint, "response_fields", []) or []),
                    "response_type": getattr(endpoint, "response_type", ""),
                }
            )

    return {
        "version": getattr(bundle, "version", "1.0"),
        "extracted_from_milestone": getattr(bundle, "extracted_from_milestone", ""),
        "field_naming_convention": getattr(
            bundle,
            "field_naming_convention",
            "camelCase",
        ),
        "endpoints": endpoints,
        # Keep cumulative models/enums out of the local spec unless specifically scoped.
        "models": [],
        "enums": [],
    }


def _bundle_to_openapi(bundle: Any, *, title: str, version: str) -> dict[str, Any]:
    bundle_dict = {
        "version": getattr(bundle, "version", "1.0"),
        "extracted_from_milestone": getattr(bundle, "extracted_from_milestone", ""),
        "field_naming_convention": getattr(bundle, "field_naming_convention", "camelCase"),
        "endpoints": [
            {
                "path": getattr(endpoint, "path", ""),
                "method": getattr(endpoint, "method", ""),
                "handler_name": getattr(endpoint, "handler_name", ""),
                "controller_file": getattr(endpoint, "controller_file", ""),
                "request_params": list(getattr(endpoint, "request_params", []) or []),
                "request_body_fields": list(
                    getattr(endpoint, "request_body_fields", []) or []
                ),
                "response_fields": list(getattr(endpoint, "response_fields", []) or []),
                "response_type": getattr(endpoint, "response_type", ""),
            }
            for endpoint in getattr(bundle, "endpoints", []) or []
        ],
        "models": [
            {
                "name": getattr(model, "name", ""),
                "fields": list(getattr(model, "fields", []) or []),
            }
            for model in getattr(bundle, "models", []) or []
        ],
        "enums": [
            {
                "name": getattr(enum, "name", ""),
                "values": list(getattr(enum, "values", []) or []),
            }
            for enum in getattr(bundle, "enums", []) or []
        ],
    }
    return _bundle_dict_to_openapi(bundle_dict, title=title, version=version)


def _bundle_dict_to_openapi(
    bundle: dict[str, Any],
    *,
    title: str,
    version: str,
) -> dict[str, Any]:
    components = {"schemas": {}}

    for model in bundle.get("models", []) or []:
        name = str(model.get("name", "") or "").strip()
        if not name:
            continue
        required: list[str] = []
        properties: dict[str, Any] = {}
        for field in model.get("fields", []) or []:
            field_name = str(field.get("name", "") or "").strip()
            if not field_name:
                continue
            properties[field_name] = _type_to_schema(str(field.get("type", "") or "string"))
            if not bool(field.get("nullable", False)):
                required.append(field_name)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        components["schemas"][name] = schema

    for enum in bundle.get("enums", []) or []:
        name = str(enum.get("name", "") or "").strip()
        if not name:
            continue
        components["schemas"][name] = {
            "type": "string",
            "enum": list(enum.get("values", []) or []),
        }

    paths: dict[str, dict[str, Any]] = {}
    for endpoint in bundle.get("endpoints", []) or []:
        raw_path = str(endpoint.get("path", "") or "/")
        normalized_path = _normalize_openapi_path(raw_path)
        method = str(endpoint.get("method", "GET") or "GET").lower()
        operation = {
            "operationId": _operation_name(
                normalized_path,
                method.upper(),
                {"operationId": endpoint.get("handler_name", "")},
            ),
            "tags": [_tag_for_path(normalized_path)],
            "responses": {
                _success_status_for_method(method.upper()): {
                    "description": "Generated response",
                }
            },
        }

        parameters: list[dict[str, Any]] = []
        for param_name in list(endpoint.get("request_params", []) or []):
            if param_name.startswith("__"):
                continue
            if _is_path_param(raw_path, param_name):
                parameters.append(
                    {
                        "name": param_name,
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                )
            else:
                parameters.append(
                    {
                        "name": param_name,
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                    }
                )
        if parameters:
            operation["parameters"] = parameters

        request_body_fields = list(endpoint.get("request_body_fields", []) or [])
        if request_body_fields:
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": _fields_to_object_schema(request_body_fields),
                    }
                },
            }

        response_schema = _response_schema_for_endpoint(
            endpoint,
            components["schemas"],
        )
        if response_schema:
            status_key = _success_status_for_method(method.upper())
            operation["responses"][status_key]["content"] = {
                "application/json": {"schema": response_schema}
            }

        paths.setdefault(normalized_path, {})[method] = operation

    doc: dict[str, Any] = {
        "openapi": "3.0.0",
        "info": {
            "title": title,
            "version": version,
        },
        "paths": paths,
    }
    if components["schemas"]:
        doc["components"] = components
    return doc


def _normalize_openapi_path(path: str) -> str:
    normalized = path if path.startswith("/") else "/" + path
    normalized = re.sub(r":([A-Za-z_]\w*)", r"{\1}", normalized)
    normalized = re.sub(r"<(?:[^:>]+:)?([A-Za-z_]\w*)>", r"{\1}", normalized)
    normalized = re.sub(r"//+", "/", normalized)
    return normalized.rstrip("/") or "/"


def _success_status_for_method(method: str) -> str:
    if method == "POST":
        return "201"
    if method == "DELETE":
        return "204"
    return "200"


def _tag_for_path(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part and not part.startswith("{")]
    return parts[0] if parts else "default"


def _is_path_param(path: str, param_name: str) -> bool:
    return (
        f":{param_name}" in path
        or "{" + param_name + "}" in path
        or re.search(rf"<(?:[^:>]+:)?{re.escape(param_name)}>", path) is not None
    )


def _fields_to_object_schema(fields: list[dict[str, Any]]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in fields:
        name = str(field.get("name", "") or "").strip()
        if not name:
            continue
        properties[name] = _type_to_schema(str(field.get("type", "") or "string"))
        required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _response_schema_for_endpoint(
    endpoint: dict[str, Any],
    component_schemas: dict[str, Any],
) -> dict[str, Any] | None:
    response_type = str(endpoint.get("response_type", "") or "").strip()
    if response_type:
        ref_schema = _response_type_ref_schema(response_type, component_schemas)
        if ref_schema is not None:
            return ref_schema

    response_fields = list(endpoint.get("response_fields", []) or [])
    if response_fields:
        return _fields_to_object_schema(response_fields)
    return None


def _response_type_ref_schema(
    response_type: str,
    component_schemas: dict[str, Any],
) -> dict[str, Any] | None:
    array_match = re.fullmatch(r"([A-Za-z_]\w*)\[\]", response_type)
    if array_match:
        name = array_match.group(1)
        if name in component_schemas:
            return {"type": "array", "items": {"$ref": f"#/components/schemas/{name}"}}

    promise_match = re.fullmatch(r"Promise<(.+)>", response_type)
    if promise_match:
        return _response_type_ref_schema(promise_match.group(1), component_schemas)

    if response_type in component_schemas:
        return {"$ref": f"#/components/schemas/{response_type}"}

    primitive = _primitive_type_schema(response_type)
    if primitive is not None:
        return primitive

    return None


def _type_to_schema(type_name: str) -> dict[str, Any]:
    type_name = type_name.strip()
    if type_name.endswith("[]"):
        return {"type": "array", "items": _type_to_schema(type_name[:-2])}

    primitive = _primitive_type_schema(type_name)
    if primitive is not None:
        return primitive

    union_values = [part.strip().strip("'\"") for part in type_name.split("|")]
    if (
        len(union_values) > 1
        and all(value and re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in union_values)
    ):
        return {"type": "string", "enum": union_values}

    return {"$ref": f"#/components/schemas/{type_name}"} if type_name else {"type": "string"}


def _primitive_type_schema(type_name: str) -> dict[str, Any] | None:
    normalized = type_name.strip().lower()
    if normalized in {"string", "date", "datetime", "uuid"}:
        return {"type": "string"}
    if normalized in {"int", "integer", "float", "double", "number"}:
        return {"type": "number"}
    if normalized in {"bool", "boolean"}:
        return {"type": "boolean"}
    if normalized in {"dict", "object", "record<string,unknown>", "record<string, any>", "json"}:
        return {"type": "object", "additionalProperties": True}
    if normalized in {"any", "unknown"}:
        return {}
    return None


def _extract_endpoints_from_spec(spec_path: Path) -> list[dict[str, Any]]:
    if not spec_path.exists():
        return []
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []

    endpoints: list[dict[str, Any]] = []
    for path, path_item in sorted((spec.get("paths") or {}).items()):
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            endpoints.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operationId": operation.get("operationId", ""),
                    "tag": (operation.get("tags") or [""])[0],
                }
            )
    return endpoints


def _run_regex_crosscheck(
    project_root: Path,
    milestone: Any,
    result: ContractResult,
    *,
    regex_summary: list[dict[str, Any]] | None = None,
) -> None:
    """Best-effort cross-check between generated spec endpoints and regex extraction."""

    try:
        if regex_summary is None:
            bundle = _extract_api_bundle(project_root, getattr(milestone, "id", ""))
            regex_summary = [
                {"method": getattr(endpoint, "method", ""), "path": getattr(endpoint, "path", "")}
                for endpoint in getattr(bundle, "endpoints", []) or []
            ]
    except Exception as exc:  # pragma: no cover - non-fatal safety net
        logger.warning("Regex cross-check failed for %s: %s", getattr(milestone, "id", ""), exc)
        return

    generated_pairs = {
        (
            str(item.get("method", "")).upper(),
            _normalize_openapi_path(str(item.get("path", "") or "/")),
        )
        for item in result.endpoints_summary
    }
    regex_pairs = {
        (
            str(item.get("method", "")).upper(),
            _normalize_openapi_path(str(item.get("path", "") or "/")),
        )
        for item in regex_summary or []
    }

    missing_from_generated = sorted(regex_pairs - generated_pairs)
    missing_from_regex = sorted(generated_pairs - regex_pairs)
    if missing_from_generated or missing_from_regex:
        logger.info(
            "Wave C regex cross-check for %s: generated-only=%d regex-only=%d",
            getattr(milestone, "id", ""),
            len(missing_from_regex),
            len(missing_from_generated),
        )


def _summary_spec_path(result: ContractResult, contracts_dir: Path) -> Path:
    if result.milestone_spec_path:
        return Path(result.milestone_spec_path)
    if result.cumulative_spec_path:
        return Path(result.cumulative_spec_path)
    return contracts_dir / "current.json"


def _write_json(project_root: Path, path: Path, payload: dict[str, Any]) -> str:
    return _write_text(
        project_root,
        path,
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def _write_text(project_root: Path, path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return _rel(project_root, path)


def _rel(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _posix(path: str) -> str:
    return path.replace("\\", "/")


__all__ = [
    "ContractResult",
    "generate_openapi_contracts",
]
