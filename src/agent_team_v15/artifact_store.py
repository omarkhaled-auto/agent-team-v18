"""Wave-level artifact extraction and routing.

This module extracts compact JSON artifacts from files touched during a single
wave so downstream wave prompts can consume focused context instead of the
entire milestone history. Extraction is deterministic and file-based only.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ENTITY_CLASS_RE = re.compile(
    r"@Entity(?:\([^)]*\))?\s*(?:export\s+)?class\s+(\w+)",
    re.MULTILINE,
)
_ENTITY_FIELD_RE = re.compile(
    r"(?:@\w+(?:\([^)]*\))?\s*)*"
    r"@(?:PrimaryGeneratedColumn|PrimaryColumn|Column|CreateDateColumn|UpdateDateColumn|DeleteDateColumn)"
    r"(?:\([^)]*\))?\s*"
    r"(?:public\s+|private\s+|protected\s+|readonly\s+)?"
    r"(\w+)\s*[?!]?\s*:\s*([^;=\n]+)",
    re.MULTILINE,
)
_SERVICE_CLASS_RE = re.compile(
    r"@Injectable(?:\([^)]*\))?\s*(?:export\s+)?class\s+(\w+)",
    re.MULTILINE,
)
_SERVICE_METHOD_RE = re.compile(
    r"^\s*(?:public\s+|private\s+|protected\s+)?(?:async\s+)?(\w+)\s*\(([^)]*)\)"
    r"(?:\s*:\s*([^<{=\n]+(?:<[^>\n]+>)?))?",
    re.MULTILINE,
)
_CONTROLLER_CLASS_RE = re.compile(
    r"@Controller\(\s*['\"]([^'\"]*)['\"]?\s*\)\s*(?:export\s+)?class\s+(\w+)",
    re.MULTILINE,
)
_CONTROLLER_ROUTE_RE = re.compile(
    r"@(Get|Post|Put|Patch|Delete)\(\s*(?:['\"]([^'\"]*)['\"])?\s*\)"
    r"(?:[\s\S]{0,400}?)^\s*(?:public\s+|private\s+|protected\s+)?(?:async\s+)?(\w+)\s*\(",
    re.MULTILINE,
)
_DTO_CLASS_RE = re.compile(
    r"(?:export\s+)?class\s+(\w+(?:Dto|DTO|Request|Response)\w*)"
    r"(?:\s+extends\s+\w+)?(?:\s+implements\s+[\w,\s]+)?\s*\{",
    re.MULTILINE,
)
_DTO_FIELD_RE = re.compile(
    r"((?:@\w+(?:\([^)]*\))?\s*)*)"
    r"(?:public\s+|private\s+|protected\s+|readonly\s+)?"
    r"(\w+)\s*(\?)?\s*:\s*([^;=\n]+)",
    re.MULTILINE,
)
_DECORATOR_NAME_RE = re.compile(r"@(\w+)")
_NAMED_EXPORT_RE = re.compile(
    r"export\s+(?:async\s+)?(?:const|function|class|type|interface|enum)\s+(\w+)",
    re.MULTILINE,
)
_BARREL_EXPORT_RE = re.compile(r"export\s*\{([^}]+)\}", re.MULTILINE)
_ASYNC_CHANNEL_RE = re.compile(
    r"(?:@(?:MessagePattern|EventPattern)|\.(?:emit|publish|subscribe|send))"
    r"\(\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_PAGE_IMPORT_RE = re.compile(
    r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_TEST_SUFFIXES = (
    ".spec.ts",
    ".spec.tsx",
    ".test.ts",
    ".test.tsx",
    ".spec.js",
    ".test.js",
)
_GENERATED_FILE_SUFFIXES = (
    ".tsbuildinfo",
)


@dataclass
class WaveArtifact:
    milestone_id: str
    wave: str
    template: str = "full_stack"
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)
    controllers: list[dict[str, Any]] = field(default_factory=list)
    dtos: list[dict[str, Any]] = field(default_factory=list)
    adapter_implementations: list[str] = field(default_factory=list)
    client_exports: list[str] = field(default_factory=list)
    async_channels: list[str] = field(default_factory=list)
    pages: list[dict[str, Any]] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    timestamp: str = ""


def extract_wave_artifacts(
    cwd: str,
    milestone_id: str,
    wave: str,
    changed_files: list[str],
    files_created: list[str] | None = None,
    files_modified: list[str] | None = None,
    template: str = "full_stack",
) -> dict[str, Any]:
    """Extract a structured artifact for one wave from its touched files."""

    project_root = Path(cwd)
    created = _filter_generated_paths(_unique_strings(files_created or []))
    modified = _filter_generated_paths(_unique_strings(files_modified or []))
    changed = _filter_generated_paths(_unique_strings(changed_files or created + modified))

    artifact = WaveArtifact(
        milestone_id=milestone_id,
        wave=wave,
        template=template,
        files_created=created,
        files_modified=modified,
        timestamp=_now_iso(),
    )

    for file_path in changed:
        full_path = project_root / file_path
        if not full_path.is_file():
            continue

        content = _safe_read(full_path)
        if not content:
            continue

        normalized = file_path.replace("\\", "/")
        lowered = normalized.lower()

        if lowered.endswith((".entity.ts", ".model.ts")):
            artifact.entities.extend(_extract_entities(content, normalized))
        if lowered.endswith(".service.ts"):
            artifact.services.extend(_extract_services(content, normalized))
        if lowered.endswith(".controller.ts"):
            artifact.controllers.extend(_extract_controllers(content, normalized))
        if lowered.endswith(".dto.ts"):
            artifact.dtos.extend(_extract_dtos(content, normalized))
        if lowered.endswith(".adapter.ts"):
            artifact.adapter_implementations.append(normalized)
        if lowered.endswith(("page.tsx", "page.ts", "page.jsx", "page.js")):
            artifact.pages.extend(_extract_pages(content, normalized))
        if lowered.endswith(_TEST_SUFFIXES):
            artifact.test_files.append(normalized)

        artifact.client_exports.extend(_extract_client_exports(content, normalized))
        artifact.async_channels.extend(_extract_async_channels(content))

    artifact.entities = _dedupe_dicts(artifact.entities, ("file", "name"))
    artifact.services = _dedupe_dicts(artifact.services, ("file", "name"))
    artifact.controllers = _dedupe_dicts(artifact.controllers, ("file", "name", "base_path"))
    artifact.dtos = _dedupe_dicts(artifact.dtos, ("file", "name"))
    artifact.pages = _dedupe_dicts(artifact.pages, ("file", "route"))
    artifact.adapter_implementations = _unique_strings(artifact.adapter_implementations)
    artifact.client_exports = _unique_strings(artifact.client_exports)
    artifact.async_channels = _unique_strings(artifact.async_channels)
    artifact.test_files = _unique_strings(artifact.test_files)

    return _artifact_to_dict(artifact)


def save_wave_artifact(artifact: dict[str, Any], cwd: str, milestone_id: str, wave: str) -> str:
    """Save a wave artifact under ``.agent-team/artifacts``."""

    artifact_dir = Path(cwd) / ".agent-team" / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"{milestone_id}-wave-{wave}.json"
    path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def load_wave_artifact(cwd: str, milestone_id: str, wave: str) -> dict[str, Any] | None:
    """Load a previously saved wave artifact."""

    path = Path(cwd) / ".agent-team" / "artifacts" / f"{milestone_id}-wave-{wave}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logger.warning("Failed to load wave artifact %s: %s", path, exc)
        return None


def load_dependency_artifacts(milestone: Any, cwd: str) -> dict[str, dict[str, Any]]:
    """Load all available wave artifacts for milestone-level dependencies."""

    artifacts: dict[str, dict[str, Any]] = {}
    for dependency in getattr(milestone, "dependencies", []) or []:
        dep_value = dependency if isinstance(dependency, str) else getattr(dependency, "id", "")
        dep_id = dep_value.split(":", 1)[0]
        if not dep_id:
            continue
        for wave in ("A", "B", "C"):
            artifact = load_wave_artifact(cwd, dep_id, wave)
            if artifact:
                artifacts[f"{dep_id}-wave-{wave}"] = artifact
    return artifacts


def format_artifacts_for_prompt(
    wave_artifacts: dict[str, dict[str, Any]],
    dependency_artifacts: dict[str, dict[str, Any]],
    target_wave: str,
) -> str:
    """Render only the artifact slices relevant to the target wave."""

    sections: list[str] = []

    if target_wave == "A":
        for key, artifact in sorted(dependency_artifacts.items()):
            if artifact.get("entities"):
                sections.append(_format_entity_summary(artifact, key))
    elif target_wave == "B":
        wave_a = wave_artifacts.get("A", {})
        if wave_a.get("entities"):
            sections.append(_format_entity_summary(wave_a, "Wave A (this milestone)"))
        for key, artifact in sorted(dependency_artifacts.items()):
            if artifact.get("entities") or artifact.get("services"):
                sections.append(_format_service_summary(artifact, key))
    elif target_wave == "D":
        wave_c = wave_artifacts.get("C", {})
        if wave_c:
            sections.append(_format_contract_summary(wave_c))
    elif target_wave == "E":
        for wave_name in sorted(wave_artifacts):
            sections.append(_format_full_artifact(wave_artifacts[wave_name], wave_name))

    if not sections:
        return ""

    return "[WAVE ARTIFACTS]\n" + "\n\n".join(section for section in sections if section.strip())


def _extract_entities(content: str, file_path: str) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for match in _ENTITY_CLASS_RE.finditer(content):
        class_name = match.group(1)
        class_body = _slice_class_body(content, match.end())
        fields: list[dict[str, str]] = []
        for field_match in _ENTITY_FIELD_RE.finditer(class_body):
            fields.append(
                {
                    "name": field_match.group(1),
                    "type": field_match.group(2).strip(),
                }
            )
        entities.append({"name": class_name, "file": file_path, "fields": fields})
    return entities


def _extract_services(content: str, file_path: str) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    for match in _SERVICE_CLASS_RE.finditer(content):
        service_name = match.group(1)
        class_body = _slice_class_body(content, match.end())
        methods: list[dict[str, str]] = []
        for method_match in _SERVICE_METHOD_RE.finditer(class_body):
            method_name = method_match.group(1)
            if method_name in {"constructor", "onModuleInit", "onModuleDestroy"}:
                continue
            methods.append(
                {
                    "name": method_name,
                    "params": method_match.group(2).strip(),
                    "returns": (method_match.group(3) or "void").strip(),
                }
            )
        services.append({"name": service_name, "file": file_path, "methods": methods})
    return services


def _extract_controllers(content: str, file_path: str) -> list[dict[str, Any]]:
    controllers: list[dict[str, Any]] = []
    for match in _CONTROLLER_CLASS_RE.finditer(content):
        base_path = match.group(1).strip("/")
        controller_name = match.group(2)
        class_body = _slice_class_body(content, match.end())
        endpoints: list[dict[str, str]] = []
        for route_match in _CONTROLLER_ROUTE_RE.finditer(class_body):
            method = route_match.group(1).upper()
            sub_path = (route_match.group(2) or "").strip("/")
            handler_name = route_match.group(3)
            full_path = "/" + "/".join(part for part in (base_path, sub_path) if part)
            endpoints.append(
                {
                    "method": method,
                    "path": full_path or "/",
                    "handler": handler_name,
                }
            )
        controllers.append(
            {
                "name": controller_name,
                "base_path": f"/{base_path}" if base_path else "/",
                "file": file_path,
                "endpoints": endpoints,
            }
        )
    return controllers


def _extract_dtos(content: str, file_path: str) -> list[dict[str, Any]]:
    dtos: list[dict[str, Any]] = []
    for match in _DTO_CLASS_RE.finditer(content):
        dto_name = match.group(1)
        if dto_name.endswith(
            ("Controller", "Service", "Module", "Guard", "Interceptor", "Filter", "Gateway")
        ):
            continue
        class_body = _slice_class_body(content, match.end())
        fields: list[dict[str, Any]] = []
        for field_match in _DTO_FIELD_RE.finditer(class_body):
            decorators = _DECORATOR_NAME_RE.findall(field_match.group(1))
            field_name = field_match.group(2)
            field_type = field_match.group(4).strip()
            fields.append(
                {
                    "name": field_name,
                    "type": field_type,
                    "optional": bool(field_match.group(3))
                    or "IsOptional" in decorators
                    or "ApiPropertyOptional" in decorators,
                    "decorators": decorators,
                }
            )
        dtos.append({"name": dto_name, "file": file_path, "fields": fields})
    return dtos


def _extract_pages(content: str, file_path: str) -> list[dict[str, Any]]:
    client_imports: list[dict[str, str]] = []
    for match in _PAGE_IMPORT_RE.finditer(content):
        import_source = match.group(2)
        if "api-client" not in import_source and "/client" not in import_source.replace("\\", "/"):
            continue
        for name in match.group(1).split(","):
            clean_name = name.strip()
            if clean_name:
                client_imports.append({"name": clean_name, "from": import_source})
    return [
        {
            "route": _file_path_to_route(file_path),
            "file": file_path,
            "client_imports": client_imports,
        }
    ]


def _extract_client_exports(content: str, file_path: str) -> list[str]:
    lowered = file_path.lower()
    if not lowered.endswith((".ts", ".tsx", ".js", ".jsx")):
        return []
    if not any(
        marker in lowered
        for marker in (
            "api-client",
            "generated-client",
            "/client/",
            "\\client\\",
            "/clients/",
            "\\clients\\",
        )
    ):
        return []

    exports: list[str] = []
    exports.extend(match.group(1) for match in _NAMED_EXPORT_RE.finditer(content))
    for match in _BARREL_EXPORT_RE.finditer(content):
        exports.extend(name.strip() for name in match.group(1).split(",") if name.strip())
    return exports


def _extract_async_channels(content: str) -> list[str]:
    return [match.group(1) for match in _ASYNC_CHANNEL_RE.finditer(content)]


def _format_entity_summary(artifact: dict[str, Any], label: str) -> str:
    lines = [f"## {label}", "Entities:"]
    for entity in artifact.get("entities", []):
        fields = ", ".join(
            f"{field.get('name', '')}:{field.get('type', '')}" for field in entity.get("fields", [])
        )
        lines.append(f"- {entity.get('name', '')} [{entity.get('file', '')}] {fields}".rstrip())
    return "\n".join(lines)


def _format_service_summary(artifact: dict[str, Any], label: str) -> str:
    lines = [f"## {label}"]
    if artifact.get("entities"):
        lines.append("Entities:")
        for entity in artifact["entities"]:
            lines.append(f"- {entity.get('name', '')} [{entity.get('file', '')}]")
    if artifact.get("services"):
        lines.append("Services:")
        for service in artifact["services"]:
            method_names = ", ".join(method.get("name", "") for method in service.get("methods", []))
            suffix = f" ({method_names})" if method_names else ""
            lines.append(f"- {service.get('name', '')} [{service.get('file', '')}]{suffix}")
    return "\n".join(lines)


def _format_contract_summary(artifact: dict[str, Any]) -> str:
    lines = ["## Wave C Contracts"]
    contract_source = str(artifact.get("contract_source", "") or "").strip()
    contract_fidelity = str(artifact.get("contract_fidelity", "") or "").strip()
    degradation_reason = str(artifact.get("degradation_reason", "") or "").strip()
    client_generator = str(artifact.get("client_generator", "") or "").strip()
    client_fidelity = str(artifact.get("client_fidelity", "") or "").strip()
    client_degradation_reason = str(artifact.get("client_degradation_reason", "") or "").strip()
    if contract_source:
        lines.append(f"- Contract source: {contract_source}")
    if contract_fidelity:
        lines.append(f"- Contract fidelity: {contract_fidelity}")
    if client_generator:
        lines.append(f"- Client generator: {client_generator}")
    if client_fidelity:
        lines.append(f"- Client fidelity: {client_fidelity}")
    if contract_fidelity.lower() == "degraded":
        reason = f" Reason: {degradation_reason}" if degradation_reason else ""
        lines.append(
            "BLOCKED: Wave C contract metadata is degraded and must not be "
            f"treated as authoritative for Wave D.{reason}"
        )
    if client_fidelity.lower() == "degraded":
        reason = f" Reason: {client_degradation_reason}" if client_degradation_reason else ""
        lines.append(
            "BLOCKED: Wave C client metadata is degraded and must not be "
            f"treated as authoritative for Wave D.{reason}"
        )
    openapi_path = artifact.get("openapi_spec_path")
    if openapi_path:
        lines.append(f"- OpenAPI: {openapi_path}")
    cumulative_path = artifact.get("cumulative_spec_path")
    if cumulative_path:
        lines.append(f"- Cumulative spec: {cumulative_path}")

    endpoints = artifact.get("endpoints", [])
    if endpoints:
        lines.append("Endpoints:")
        for endpoint in endpoints[:20]:
            if isinstance(endpoint, dict):
                method = endpoint.get("method", "").upper()
                path = endpoint.get("path", "")
                lines.append(f"- {method} {path}".strip())

    client_manifest = artifact.get("client_manifest", [])
    if client_manifest:
        lines.append("Client manifest:")
        for item in client_manifest[:12]:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", "") or "").strip() or "unknownSymbol"
            details = [
                detail
                for detail in (
                    f"{str(item.get('method', '') or '').upper()} {str(item.get('path', '') or '').strip()}".strip(),
                    item.get("request_type") and f"request: {item['request_type']}",
                    item.get("response_type") and f"response: {item['response_type']}",
                )
                if detail
            ]
            if details:
                lines.append(f"- {symbol} | " + " | ".join(details))
            else:
                lines.append(f"- {symbol}")
    else:
        client_exports = artifact.get("client_exports", [])
        if client_exports:
            lines.append(f"- Client exports: {', '.join(client_exports[:20])}")

    breaking_changes = artifact.get("breaking_changes", [])
    if breaking_changes:
        lines.append("Breaking changes:")
        for item in breaking_changes[:10]:
            lines.append(f"- {item}")

    return "\n".join(lines)


def _format_full_artifact(artifact: dict[str, Any], wave: str) -> str:
    lines = [f"## Wave {wave}"]
    if artifact.get("entities"):
        lines.append(f"- Entities: {', '.join(item.get('name', '') for item in artifact['entities'])}")
    if artifact.get("services"):
        lines.append(f"- Services: {', '.join(item.get('name', '') for item in artifact['services'])}")
    if artifact.get("controllers"):
        lines.append(
            f"- Controllers: {', '.join(item.get('name', '') for item in artifact['controllers'])}"
        )
    if artifact.get("dtos"):
        lines.append(f"- DTOs: {', '.join(item.get('name', '') for item in artifact['dtos'])}")
    if artifact.get("pages"):
        lines.append(f"- Pages: {', '.join(item.get('route', '') for item in artifact['pages'])}")
    if artifact.get("client_exports"):
        lines.append(f"- Client exports: {', '.join(artifact['client_exports'])}")
    if artifact.get("client_manifest"):
        lines.append(
            f"- Client manifest entries: {len(artifact['client_manifest'])}"
        )
    if artifact.get("async_channels"):
        lines.append(f"- Async channels: {', '.join(artifact['async_channels'])}")
    if artifact.get("test_files"):
        lines.append(f"- Tests: {', '.join(artifact['test_files'])}")
    return "\n".join(lines)


def _safe_read(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return ""
    return ""


def _slice_class_body(content: str, start: int) -> str:
    open_brace = content.find("{", start)
    if open_brace < 0:
        return content[start:]

    depth = 1
    index = open_brace + 1
    while index < len(content) and depth > 0:
        char = content[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    return content[open_brace + 1:index - 1]


def _file_path_to_route(file_path: str) -> str:
    parts = file_path.replace("\\", "/").split("/")
    if "app" in parts:
        parts = parts[parts.index("app") + 1:]
    if parts and parts[-1].startswith("page."):
        parts = parts[:-1]

    route_parts: list[str] = []
    for part in parts:
        if not part or (part.startswith("(") and part.endswith(")")):
            continue
        if part in {"[locale]", "[lang]"}:
            continue
        if part.startswith("[...") and part.endswith("]"):
            route_parts.append(f":{part[4:-1]}")
            continue
        if part.startswith("[") and part.endswith("]"):
            route_parts.append(f":{part[1:-1]}")
            continue
        route_parts.append(part)
    return "/" + "/".join(route_parts) if route_parts else "/"


def _artifact_to_dict(artifact: WaveArtifact) -> dict[str, Any]:
    return asdict(artifact)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _filter_generated_paths(paths: list[str]) -> list[str]:
    return [
        path for path in paths
        if not path.replace("\\", "/").lower().endswith(_GENERATED_FILE_SUFFIXES)
    ]


def _dedupe_dicts(items: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        marker = tuple(item.get(key) for key in keys)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(item)
    return deduped


__all__ = [
    "WaveArtifact",
    "extract_wave_artifacts",
    "format_artifacts_for_prompt",
    "load_dependency_artifacts",
    "load_wave_artifact",
    "save_wave_artifact",
]
