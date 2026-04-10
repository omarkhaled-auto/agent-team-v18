"""Deterministic scaffolding runner for V18.1.

This module is intentionally standalone and not wired into production
execution yet. It reads a compiled Product IR and creates predictable
file skeletons that downstream agents can fill in with business logic.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional


def run_scaffolding(
    ir_path: Path,
    project_root: Path,
    milestone_id: str,
    milestone_features: list[str],
    stack_target: Optional[str] = None,
) -> list[str]:
    """Run deterministic scaffolding for a milestone.

    Returns the created file paths relative to *project_root*.
    """
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    stack = stack_target or _detect_stack_from_ir(ir)
    scaffolded_files: list[str] = []

    milestone_entities = [
        entity
        for entity in ir.get("entities", [])
        if _entity_matches_milestone(entity, milestone_id, milestone_features)
    ]

    if not milestone_entities:
        return []

    if "nestjs" in stack.lower():
        scaffolded_files.extend(
            _scaffold_nestjs(project_root, milestone_entities, ir)
        )

    if "next" in stack.lower() or "react" in stack.lower():
        scaffolded_files.extend(
            _scaffold_nextjs_pages(project_root, milestone_entities, ir)
        )

    if ir.get("i18n", {}).get("locales"):
        scaffolded_files.extend(
            _scaffold_i18n(project_root, milestone_features, ir["i18n"])
        )

    return scaffolded_files


def _detect_stack_from_ir(ir: dict) -> str:
    stack = ir.get("stack_target", {}) or {}
    backend = str(stack.get("backend", "") or "")
    frontend = str(stack.get("frontend", "") or "")
    mobile = str(stack.get("mobile", "") or "")
    parts = [backend, frontend, mobile]
    return " ".join(part for part in parts if part).strip()


def _entity_matches_milestone(
    entity: dict,
    milestone_id: str,
    milestone_features: list[str],
) -> bool:
    owner_feature = str(entity.get("owner_feature", "") or "")
    owner_hint = str(entity.get("owner_milestone_hint", "") or "")
    if owner_hint == milestone_id:
        return True
    if owner_feature and owner_feature in milestone_features:
        return True
    return False


def _scaffold_nestjs(project_root: Path, entities: list[dict], ir: dict) -> list[str]:
    """Generate NestJS module/service/controller shells."""
    scaffolded: list[str] = []
    api_dir = project_root / "apps" / "api"
    api_dir.mkdir(parents=True, exist_ok=True)

    if _check_nest_cli(api_dir):
        for entity in entities:
            name = _to_kebab_case(str(entity.get("name", "")))
            if not name:
                continue
            target_paths = [
                api_dir / "src" / name / f"{name}.module.ts",
                api_dir / "src" / name / f"{name}.service.ts",
                api_dir / "src" / name / f"{name}.controller.ts",
            ]
            if all(path.exists() for path in target_paths):
                continue
            if any(path.exists() for path in target_paths):
                scaffolded.extend(
                    _scaffold_nestjs_from_templates(project_root, [entity], ir)
                )
                continue
            try:
                subprocess.run(
                    ["npx", "nest", "generate", "module", name, "--no-spec"],
                    cwd=str(api_dir),
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                subprocess.run(
                    ["npx", "nest", "generate", "service", name, "--no-spec"],
                    cwd=str(api_dir),
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                subprocess.run(
                    ["npx", "nest", "generate", "controller", name, "--no-spec"],
                    cwd=str(api_dir),
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                scaffolded.extend(
                    [
                        _relpath(api_dir / "src" / name / f"{name}.module.ts", project_root),
                        _relpath(api_dir / "src" / name / f"{name}.service.ts", project_root),
                        _relpath(api_dir / "src" / name / f"{name}.controller.ts", project_root),
                    ]
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                scaffolded.extend(
                    _scaffold_nestjs_from_templates(project_root, [entity], ir)
                )
    else:
        scaffolded.extend(_scaffold_nestjs_from_templates(project_root, entities, ir))

    return scaffolded


def _scaffold_nestjs_from_templates(
    project_root: Path,
    entities: list[dict],
    ir: dict,
) -> list[str]:
    scaffolded: list[str] = []
    api_dir = project_root / "apps" / "api" / "src"

    for entity in entities:
        name = _to_kebab_case(str(entity.get("name", "")))
        pascal = _to_pascal_case(str(entity.get("name", "")))
        if not name or not pascal:
            continue
        entity_dir = api_dir / name
        entity_dir.mkdir(parents=True, exist_ok=True)

        for suffix, content in (
            ("module.ts", _nestjs_module_template(pascal, name)),
            ("service.ts", _nestjs_service_template(pascal, name)),
            ("controller.ts", _nestjs_controller_template(pascal, name)),
        ):
            file_path = entity_dir / f"{name}.{suffix}"
            if not file_path.exists():
                file_path.write_text(content, encoding="utf-8")
                scaffolded.append(_relpath(file_path, project_root))

    return scaffolded


def _scaffold_nextjs_pages(
    project_root: Path,
    entities: list[dict],
    ir: dict,
) -> list[str]:
    """Generate Next.js page shells with i18n-aware route structure."""
    scaffolded: list[str] = []
    web_dir = project_root / "apps" / "web" / "src" / "app"
    has_i18n = bool(ir.get("i18n", {}).get("locales", []))
    prefix = "[locale]/(protected)" if has_i18n else "(protected)"

    for entity in entities:
        route = _to_kebab_case(str(entity.get("name", "")))
        if not route:
            continue
        page_dir = web_dir / prefix / route
        page_dir.mkdir(parents=True, exist_ok=True)

        list_page = page_dir / "page.tsx"
        if not list_page.exists():
            list_page.write_text(_nextjs_page_template(route, "list", has_i18n), encoding="utf-8")
            scaffolded.append(_relpath(list_page, project_root))

        detail_dir = page_dir / "[id]"
        detail_dir.mkdir(parents=True, exist_ok=True)
        detail_page = detail_dir / "page.tsx"
        if not detail_page.exists():
            detail_page.write_text(_nextjs_page_template(route, "detail", has_i18n), encoding="utf-8")
            scaffolded.append(_relpath(detail_page, project_root))

    return scaffolded


def _scaffold_i18n(project_root: Path, features: list[str], i18n_config: dict) -> list[str]:
    """Create empty i18n namespace files for declared locales."""
    scaffolded: list[str] = []
    messages_dir = project_root / "apps" / "web" / "messages"

    for locale in i18n_config.get("locales", ["en"]):
        locale_dir = messages_dir / str(locale)
        locale_dir.mkdir(parents=True, exist_ok=True)
        for feature in features:
            ns_file = locale_dir / f"{_to_kebab_case(str(feature))}.json"
            if not ns_file.exists():
                ns_file.write_text("{}\n", encoding="utf-8")
                scaffolded.append(_relpath(ns_file, project_root))

    return scaffolded


def _check_nest_cli(project_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["npx", "nest", "--version"],
            cwd=str(project_root),
            capture_output=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _relpath(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _to_kebab_case(name: str) -> str:
    import re

    if not name:
        return ""
    s = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
    s = re.sub(r"[^a-z0-9-]", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def _to_pascal_case(s: str) -> str:
    if not s:
        return ""
    return "".join(word.capitalize() for word in s.replace("-", " ").replace("_", " ").split())


def _nestjs_module_template(pascal: str, name: str) -> str:
    return (
        "import { Module } from '@nestjs/common';\n\n"
        "@Module({\n"
        f"  providers: [],\n"
        f"  controllers: [],\n"
        f"  exports: [],\n"
        "})\n"
        f"export class {pascal}Module {{}}\n"
    )


def _nestjs_service_template(pascal: str, name: str) -> str:
    return (
        "import { Injectable } from '@nestjs/common';\n\n"
        "@Injectable()\n"
        f"export class {pascal}Service {{\n"
        f"  // TODO: implement {name} service logic\n"
        "}\n"
    )


def _nestjs_controller_template(pascal: str, name: str) -> str:
    return (
        "import { Controller } from '@nestjs/common';\n\n"
        f"@Controller('{name}')\n"
        f"export class {pascal}Controller {{\n"
        f"  // TODO: implement {name} controller routes\n"
        "}\n"
    )


def _nextjs_page_template(route: str, page_type: str, has_i18n: bool) -> str:
    i18n_import = "import { useTranslations } from 'next-intl';\n" if has_i18n else ""
    t_init = f"  const t = useTranslations('{route}');\n" if has_i18n else ""
    return (
        "'use client';\n\n"
        f"{i18n_import}"
        f"export default function {_to_pascal_case(route)}{_to_pascal_case(page_type)}Page() {{\n"
        f"{t_init}"
        "  return (\n"
        "    <div>\n"
        f"      {{/* TODO: Implement {route} {page_type} */}}\n"
        "    </div>\n"
        "  );\n"
        "}\n"
    )
