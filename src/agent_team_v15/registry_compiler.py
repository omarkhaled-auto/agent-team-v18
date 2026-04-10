"""Deterministic registry compilers for shared V18.1 surfaces."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REGISTRY_TYPES: dict[str, dict[str, str]] = {
    "deps": {"source": "deps.registry.json", "output": "package.json"},
    "modules": {"source": "modules.registry.json", "output": "apps/api/src/app.module.ts"},
    "nav": {"source": "nav.registry.json", "output": "apps/web/src/components/nav-registry.ts"},
    "i18n": {"source": "i18n.registry.json", "output": "apps/web/messages/index.ts"},
    "routes": {"source": "routes.registry.json", "output": "apps/api/src/routes.ts"},
}

COMPILED_SHARED_SURFACES = frozenset(
    cfg["output"].replace("\\", "/") for cfg in REGISTRY_TYPES.values()
)


def compile_registries(cwd: str, milestone_ids: list[str]) -> dict[str, bool]:
    """Compile all known registries for the provided milestone ids."""

    root = Path(cwd)
    registries_dir = root / ".agent-team" / "registries"
    results: dict[str, bool] = {}
    ordered_ids = _ordered_unique_milestone_ids(milestone_ids)

    for registry_type, config in REGISTRY_TYPES.items():
        try:
            declarations = _collect_declarations(registries_dir, ordered_ids, config["source"])
            if not declarations:
                results[registry_type] = True
                continue

            if registry_type == "deps":
                _compile_deps_registry(declarations, root, config)
            elif registry_type == "modules":
                _compile_modules_registry(declarations, root, config)
            elif registry_type == "nav":
                _compile_nav_registry(declarations, root, config)
            elif registry_type == "i18n":
                _compile_i18n_registry(declarations, root, config)
            elif registry_type == "routes":
                _compile_routes_registry(declarations, root, config)
            else:  # pragma: no cover - defensive guard
                logger.warning("Unknown registry type: %s", registry_type)
            results[registry_type] = True
        except Exception as exc:  # pragma: no cover - best-effort compiler
            logger.error("Registry compilation failed for %s: %s", registry_type, exc)
            results[registry_type] = False

    return results


def _ordered_unique_milestone_ids(milestone_ids: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for milestone_id in milestone_ids:
        normalized = str(milestone_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _collect_declarations(
    registries_dir: Path,
    milestone_ids: list[str],
    source_name: str,
) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    for milestone_id in milestone_ids:
        path = registries_dir / milestone_id / source_name
        payload = _read_json_dict(path)
        if payload:
            declarations.append(payload)
    return declarations


def _read_json_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _merge_sorted_mapping(
    declarations: list[dict[str, Any]],
    key: str,
) -> dict[str, str]:
    merged: dict[str, str] = {}
    for declaration in declarations:
        values = declaration.get(key, {})
        if not isinstance(values, dict):
            continue
        for dep_name, dep_version in values.items():
            if isinstance(dep_name, str) and isinstance(dep_version, str):
                merged[dep_name] = dep_version
    return dict(sorted(merged.items()))


def _compile_deps_registry(
    declarations: list[dict[str, Any]],
    root: Path,
    config: dict[str, str],
) -> None:
    path = root / config["output"]
    package_json = _read_json_dict(path)
    if not package_json:
        return

    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        merged = _merge_sorted_mapping(declarations, section)
        if merged:
            package_json[section] = merged

    _write_text(path, json.dumps(package_json, indent=2) + "\n")


def _dedupe_entries(
    declarations: list[dict[str, Any]],
    key: str,
    dedupe_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, ...], dict[str, Any]] = {}
    for declaration in declarations:
        values = declaration.get(key, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            dedupe_key = tuple(str(value.get(field, "") or "") for field in dedupe_fields)
            if any(dedupe_key):
                merged[dedupe_key] = value
    return [merged[key] for key in sorted(merged)]


def _compile_modules_registry(
    declarations: list[dict[str, Any]],
    root: Path,
    config: dict[str, str],
) -> None:
    modules = _dedupe_entries(declarations, "modules", ("path", "class_name"))
    if not modules:
        return

    imports = []
    module_names = []
    for module in modules:
        class_name = str(module.get("class_name", "") or "").strip()
        import_path = str(module.get("path", "") or "").strip()
        if not class_name or not import_path:
            continue
        imports.append(f"import {{ {class_name} }} from '{import_path}';")
        module_names.append(class_name)

    content = "\n".join(
        [
            "// Auto-generated by registry_compiler.py",
            *sorted(imports),
            "",
            "export const REGISTERED_MODULES = [",
            *[f"  {name}," for name in sorted(module_names)],
            "];",
            "",
        ]
    )
    _write_text(root / config["output"], content)


def _compile_nav_registry(
    declarations: list[dict[str, Any]],
    root: Path,
    config: dict[str, str],
) -> None:
    nav_items = _dedupe_entries(declarations, "items", ("id", "href", "label"))
    if not nav_items:
        return

    nav_items.sort(
        key=lambda item: (
            int(item.get("order", 0) or 0),
            str(item.get("label", "") or ""),
            str(item.get("href", "") or ""),
        )
    )
    content = (
        "// Auto-generated by registry_compiler.py\n"
        "export const NAV_REGISTRY = "
        f"{json.dumps(nav_items, indent=2, ensure_ascii=False)} as const;\n"
    )
    _write_text(root / config["output"], content)


def _compile_i18n_registry(
    declarations: list[dict[str, Any]],
    root: Path,
    config: dict[str, str],
) -> None:
    locales: dict[str, list[str]] = {}
    for declaration in declarations:
        values = declaration.get("locales", {})
        if not isinstance(values, dict):
            continue
        for locale, namespaces in values.items():
            if not isinstance(locale, str) or not isinstance(namespaces, list):
                continue
            bucket = locales.setdefault(locale, [])
            for namespace in namespaces:
                if isinstance(namespace, str) and namespace not in bucket:
                    bucket.append(namespace)

    if not locales:
        return

    normalized = {
        locale: sorted(namespaces)
        for locale, namespaces in sorted(locales.items())
    }
    content = (
        "// Auto-generated by registry_compiler.py\n"
        "export const LOCALE_NAMESPACE_REGISTRY = "
        f"{json.dumps(normalized, indent=2, ensure_ascii=False)} as const;\n"
    )
    _write_text(root / config["output"], content)


def _compile_routes_registry(
    declarations: list[dict[str, Any]],
    root: Path,
    config: dict[str, str],
) -> None:
    routes = _dedupe_entries(
        declarations,
        "routes",
        ("method", "path", "symbol", "import_path"),
    )
    if not routes:
        return

    imports: list[str] = []
    route_entries: list[str] = []
    for route in sorted(
        routes,
        key=lambda item: (
            str(item.get("path", "") or ""),
            str(item.get("method", "") or ""),
            str(item.get("symbol", "") or ""),
        ),
    ):
        symbol = str(route.get("symbol", "") or "").strip()
        import_path = str(route.get("import_path", "") or "").strip()
        method = str(route.get("method", "") or "").upper()
        path_value = str(route.get("path", "") or "")
        if symbol and import_path:
            imports.append(f"import {{ {symbol} }} from '{import_path}';")
            route_entries.append(
                f"  {{ method: '{method}', path: '{path_value}', handler: {symbol} }},"
            )
        else:
            route_entries.append(
                "  "
                + json.dumps(
                    {
                        "method": method,
                        "path": path_value,
                        "handler": symbol or route.get("handler", ""),
                    },
                    ensure_ascii=False,
                )
                + ","
            )

    content = "\n".join(
        [
            "// Auto-generated by registry_compiler.py",
            *sorted(set(imports)),
            "",
            "export const REGISTERED_ROUTES = [",
            *route_entries,
            "];",
            "",
        ]
    )
    _write_text(root / config["output"], content)


__all__ = [
    "COMPILED_SHARED_SURFACES",
    "REGISTRY_TYPES",
    "compile_registries",
]
