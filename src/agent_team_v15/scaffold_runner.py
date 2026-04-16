"""Deterministic scaffolding runner for V18.1.

Reads the compiled Product IR and creates predictable file skeletons
that downstream waves can fill in with business logic.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NEW-2: Scaffold template version stamping (Phase B)
# ---------------------------------------------------------------------------
SCAFFOLD_TEMPLATE_VERSION = "1.0.0"

# Module-level flag toggled by ``run_scaffolding`` for the duration of its
# emission. Default False means ``_write_if_missing`` emits byte-identical
# pre-NEW-2 content; flag-ON prepends a single-line version header through
# :func:`_stamp_version`. We intentionally avoid threading the flag through
# every emission helper signature — scaffold_runner is a single-threaded
# entry point and the flag's lifetime is exactly one ``run_scaffolding``
# call. The helper is reset to ``False`` via a ``try/finally`` in the entry
# point so a crashed run cannot leak the flag into subsequent tests.
_TEMPLATE_VERSION_STAMPING_ACTIVE: bool = False

# Extensions that receive a ``#``-style stamp.
_STAMP_HASH_EXTS: frozenset[str] = frozenset(
    {".py", ".yaml", ".yml", ".toml", ".env"}
)
# Extensions that receive a ``//``-style stamp.
_STAMP_SLASH_EXTS: frozenset[str] = frozenset(
    {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
)
# Extensions intentionally SKIPPED: strict-JSON has no comment syntax, and
# human-readable markdown/text should not carry our internal marker.
_STAMP_SKIP_EXTS: frozenset[str] = frozenset(
    {".json", ".md", ".txt", ".prisma"}
)


def _stamp_version(content: str, file_ext: str) -> str:
    """Prepend a single-line scaffold-template-version header.

    Comment syntax is selected by file extension:
      * ``.py`` / ``.yaml`` / ``.toml`` / ``.env`` → ``# scaffold-template-version: X.Y.Z``
      * ``.ts`` / ``.tsx`` / ``.js`` / ``.jsx`` / ``.mjs`` / ``.cjs`` → ``// scaffold-template-version: X.Y.Z``
      * ``.json`` / ``.md`` / ``.txt`` / ``.prisma`` → unchanged (no
        comment syntax OR human-readable content).

    Unknown extensions fall through unchanged. Never inserts a stamp when
    one is already present (idempotent).
    """
    ext = (file_ext or "").lower()
    if ext in _STAMP_SKIP_EXTS:
        return content
    if ext in _STAMP_HASH_EXTS:
        comment = f"# scaffold-template-version: {SCAFFOLD_TEMPLATE_VERSION}"
    elif ext in _STAMP_SLASH_EXTS:
        comment = f"// scaffold-template-version: {SCAFFOLD_TEMPLATE_VERSION}"
    else:
        return content
    if content.lstrip().startswith(comment):
        return content
    return comment + "\n" + content


def _check_template_version(content: str, file_ext: str) -> Optional[str]:
    """Return the stamped version for ``content``, or ``None`` if absent.

    Helper consumed by version-compatibility checks at pipeline startup
    (flag-ON only). Reads the first non-empty line; when it matches the
    expected comment prefix, returns the extracted version string.
    """
    ext = (file_ext or "").lower()
    if ext in _STAMP_HASH_EXTS:
        prefix = "# scaffold-template-version:"
    elif ext in _STAMP_SLASH_EXTS:
        prefix = "// scaffold-template-version:"
    else:
        return None
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip() or None
        return None
    return None


# ---------------------------------------------------------------------------
# N-02: Ownership contract parser (Phase B)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileOwnership:
    """One row of the scaffold ownership contract (docs/SCAFFOLD_OWNERSHIP.md)."""

    path: str
    owner: str  # "scaffold" | "wave-b" | "wave-d" | "wave-c-generator"
    optional: bool
    emits_stub: bool = False
    audit_expected: bool = True


@dataclass(frozen=True)
class OwnershipContract:
    """Immutable ownership contract parsed from docs/SCAFFOLD_OWNERSHIP.md."""

    files: tuple[FileOwnership, ...]

    def files_for_owner(self, owner: str) -> list[FileOwnership]:
        return [f for f in self.files if f.owner == owner]

    def is_optional(self, path: str) -> bool:
        for f in self.files:
            if f.path == path:
                return f.optional
        return False

    def owner_for(self, path: str) -> str | None:
        for f in self.files:
            if f.path == path:
                return f.owner
        return None


_OWNERSHIP_YAML_BLOCK_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)
_VALID_OWNERS = {"scaffold", "wave-b", "wave-d", "wave-c-generator"}


def _strip_notes_lines(block: str) -> str:
    """Strip `notes:` lines (prose — often contains unquoted colons like
    ``composite: true`` that trip yaml.safe_load). Runtime does not consume
    ``notes``; dropping them before parse avoids requiring the contract
    author to quote every note body.
    """
    out_lines: list[str] = []
    in_notes = False
    for line in block.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if in_notes:
            if not line.strip():
                in_notes = False
                out_lines.append(line)
                continue
            if indent <= 2:
                in_notes = False
            else:
                continue
        if stripped.startswith("notes:"):
            in_notes = True
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def load_ownership_contract(
    path: Path = Path("docs/SCAFFOLD_OWNERSHIP.md"),
) -> OwnershipContract:
    """Parse SCAFFOLD_OWNERSHIP.md yaml code blocks into an OwnershipContract.

    Raises FileNotFoundError when the file is missing, ValueError when the
    contract is malformed (invalid YAML, missing required fields, unknown
    owner).
    """
    if yaml is None:
        raise ValueError("PyYAML not available; install pyyaml to parse ownership contract")

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"Ownership contract not found: {path}")

    blocks = _OWNERSHIP_YAML_BLOCK_RE.findall(text)
    if not blocks:
        raise ValueError(f"No ```yaml blocks found in {path}")

    rows: list[FileOwnership] = []
    for idx, block in enumerate(blocks):
        scrubbed = _strip_notes_lines(block)
        try:
            parsed = yaml.safe_load(scrubbed)
        except yaml.YAMLError as exc:  # pragma: no cover — defensive
            raise ValueError(f"YAML parse error in block {idx} of {path}: {exc}")
        if parsed is None:
            continue
        if not isinstance(parsed, list):
            raise ValueError(f"Block {idx} of {path} is not a YAML list")
        for entry in parsed:
            if not isinstance(entry, dict):
                raise ValueError(f"Entry in block {idx} of {path} is not a mapping: {entry!r}")
            for required in ("path", "owner", "optional"):
                if required not in entry:
                    raise ValueError(
                        f"Entry in {path} missing required field '{required}': {entry!r}"
                    )
            owner = entry["owner"]
            if owner not in _VALID_OWNERS:
                raise ValueError(
                    f"Entry in {path} has unknown owner '{owner}': valid owners are {_VALID_OWNERS}"
                )
            rows.append(
                FileOwnership(
                    path=str(entry["path"]),
                    owner=str(owner),
                    optional=bool(entry["optional"]),
                    emits_stub=bool(entry.get("emits_stub", False)),
                    audit_expected=bool(entry.get("audit_expected", True)),
                )
            )

    return OwnershipContract(files=tuple(rows))


# ---------------------------------------------------------------------------
# N-12: Parameterized scaffold config (Phase B, §5.4 of architecture report)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScaffoldConfig:
    """Canonical scaffold values — single source of truth for drift-prone literals.

    Flag-OFF behavior (``v18.spec_reconciliation_enabled=False``): the scaffold
    uses :data:`DEFAULT_SCAFFOLD_CONFIG`, which reflects the canonical M1
    REQUIREMENTS.md shape. Flag-ON behavior: the milestone spec reconciler
    (``milestone_spec_reconciler.py``) derives a per-run ``ScaffoldConfig`` from
    REQUIREMENTS.md + PRD and passes it through in place of the default.
    """

    port: int = 4000
    prisma_path: str = "src/database"
    modules_path: str = "src/modules"
    api_prefix: str = "api"
    db_name: str = "taskflow"
    db_user: str = "taskflow"


DEFAULT_SCAFFOLD_CONFIG = ScaffoldConfig()


def run_scaffolding(
    ir_path: Path,
    project_root: Path,
    milestone_id: str,
    milestone_features: list[str],
    stack_target: Optional[str] = None,
    config: Optional[object] = None,
    scaffold_cfg: Optional[ScaffoldConfig] = None,
) -> list[str]:
    """Run deterministic scaffolding for a milestone.

    Returns the created file paths relative to *project_root*.

    When *config* is provided and ``config.v18.ownership_contract_enabled``
    is True, the emitted set is validated against the scaffold-owned rows
    of ``docs/SCAFFOLD_OWNERSHIP.md``. Missing or unexpected paths are
    logged as warnings (soft invariant — hard enforcement is N-13).

    N-12: *scaffold_cfg* lets the spec reconciler inject a per-run
    :class:`ScaffoldConfig`. When omitted, :data:`DEFAULT_SCAFFOLD_CONFIG` is
    used (canonical M1 REQUIREMENTS values).
    """
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    stack = stack_target or _detect_stack_from_ir(ir)
    scaffolded_files: list[str] = []
    cfg = scaffold_cfg if scaffold_cfg is not None else DEFAULT_SCAFFOLD_CONFIG

    milestone_entities = [
        entity
        for entity in ir.get("entities", [])
        if _entity_matches_milestone(entity, milestone_id, milestone_features)
    ]

    has_nestjs = "nestjs" in stack.lower()
    has_nextjs = "next" in stack.lower() or "react" in stack.lower()

    # NEW-2: activate version-stamping for the duration of this run when the
    # flag is on. ``finally`` ensures the module flag is restored even when
    # emission raises, so subsequent runs / tests see the canonical default.
    global _TEMPLATE_VERSION_STAMPING_ACTIVE
    previous_stamping = _TEMPLATE_VERSION_STAMPING_ACTIVE
    v18 = getattr(config, "v18", None) if config is not None else None
    _TEMPLATE_VERSION_STAMPING_ACTIVE = bool(
        getattr(v18, "template_version_stamping_enabled", False)
    )

    try:
        # M1 foundation — deterministic across all milestones (idempotent)
        scaffolded_files.extend(
            _scaffold_m1_foundation(
                project_root,
                has_nestjs=has_nestjs,
                has_nextjs=has_nextjs,
                cfg=cfg,
            )
        )

        if has_nestjs:
            scaffolded_files.extend(
                _scaffold_nestjs(project_root, milestone_entities, ir)
            )

        if milestone_entities and has_nextjs:
            scaffolded_files.extend(
                _scaffold_nextjs_pages(project_root, milestone_entities, ir)
            )

        if milestone_features and ir.get("i18n", {}).get("locales"):
            scaffolded_files.extend(
                _scaffold_i18n(project_root, milestone_features, ir["i18n"])
            )
    finally:
        _TEMPLATE_VERSION_STAMPING_ACTIVE = previous_stamping

    _maybe_validate_ownership(config, scaffolded_files, milestone_id)

    return scaffolded_files


def _maybe_validate_ownership(
    config: Optional[object],
    scaffolded_files: list[str],
    milestone_id: str,
) -> None:
    """N-02 soft invariant: warn when scaffold emission drifts from the
    ``docs/SCAFFOLD_OWNERSHIP.md`` scaffold-owned rows.
    """
    if config is None:
        return
    v18 = getattr(config, "v18", None)
    if v18 is None or not getattr(v18, "ownership_contract_enabled", False):
        return
    try:
        contract = load_ownership_contract()
    except (FileNotFoundError, ValueError) as exc:
        _logger.warning(
            "N-02 ownership validation skipped for %s: %s", milestone_id, exc
        )
        return

    emitted = set(scaffolded_files)
    expected = {
        row.path
        for row in contract.files_for_owner("scaffold")
        if not row.optional
    }
    missing = sorted(expected - emitted)
    unexpected = sorted(
        path for path in emitted
        if contract.owner_for(path) not in (None, "scaffold")
    )
    for path in missing:
        _logger.warning(
            "N-02 ownership drift (%s): scaffold-owned path not emitted: %s",
            milestone_id, path,
        )
    for path in unexpected:
        owner = contract.owner_for(path)
        _logger.warning(
            "N-02 ownership drift (%s): emitted path owned by %s, not scaffold: %s",
            milestone_id, owner, path,
        )


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
    scaffolded: list[str] = _scaffold_nestjs_support_files(project_root)
    api_dir = project_root / "apps" / "api"
    api_dir.mkdir(parents=True, exist_ok=True)

    if not entities:
        return scaffolded

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


def _scaffold_nestjs_support_files(project_root: Path) -> list[str]:
    scaffolded: list[str] = []
    scripts_dir = project_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_path = scripts_dir / "generate-openapi.ts"
    if not script_path.exists():
        script_path.write_text(_openapi_generation_script_template(), encoding="utf-8")
        scaffolded.append(_relpath(script_path, project_root))
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


#: A-04 — M1 REQUIREMENTS.md pins locales to en + ar. Filter upstream IR drift
#: (e.g., stray `id` locale leaking in from templates) so scaffold output stays
#: deterministic. Widening requires an explicit tracker decision, not IR drift.
_M1_ALLOWED_LOCALES: frozenset[str] = frozenset({"en", "ar"})


def _scaffold_i18n(project_root: Path, features: list[str], i18n_config: dict) -> list[str]:
    """Create empty i18n namespace files for declared locales.

    Locales are intersected with :data:`_M1_ALLOWED_LOCALES` — the scaffold
    layer is defensive against upstream IR drift that injects locales outside
    the M1 spec (see tracker A-04).
    """
    scaffolded: list[str] = []
    messages_dir = project_root / "apps" / "web" / "messages"

    raw_locales = [str(locale) for locale in i18n_config.get("locales", ["en"])]
    filtered_locales = [
        locale for locale in raw_locales if locale in _M1_ALLOWED_LOCALES
    ]
    if not filtered_locales:
        filtered_locales = ["en"]

    for locale in filtered_locales:
        locale_dir = messages_dir / locale
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


def _openapi_generation_script_template() -> str:
    return (
        "import 'reflect-metadata';\n"
        "import { mkdirSync, writeFileSync } from 'node:fs';\n"
        "import { join, resolve } from 'node:path';\n"
        "import { NestFactory } from '@nestjs/core';\n"
        "import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';\n\n"
        "async function loadAppModule(): Promise<any> {\n"
        "  const candidates = ['../apps/api/src/app.module', '../src/app.module'];\n"
        "  for (const candidate of candidates) {\n"
        "    try {\n"
        "      const moduleRef = await import(candidate);\n"
        "      if (moduleRef?.AppModule) {\n"
        "        return moduleRef.AppModule;\n"
        "      }\n"
        "    } catch {\n"
        "      // Try the next app root.\n"
        "    }\n"
        "  }\n"
        "  throw new Error('Unable to resolve AppModule from apps/api/src/app.module or src/app.module');\n"
        "}\n\n"
        "async function main(): Promise<void> {\n"
        "  const milestoneId = process.env.MILESTONE_ID || 'milestone-unknown';\n"
        "  const outputDir = resolve(process.cwd(), process.env.OUTPUT_DIR || 'contracts/openapi');\n"
        "  mkdirSync(outputDir, { recursive: true });\n"
        "  const AppModule = await loadAppModule();\n"
        "  const app = await NestFactory.create(AppModule, { logger: false });\n"
        "  await app.init();\n"
        "  const document = SwaggerModule.createDocument(\n"
        "    app,\n"
        "    new DocumentBuilder().setTitle('Generated API').setVersion('1.0.0').build(),\n"
        "  );\n"
        "  await app.close();\n"
        "  const serialized = JSON.stringify(document, null, 2);\n"
        "  writeFileSync(join(outputDir, 'current.json'), serialized);\n"
        "  writeFileSync(join(outputDir, `${milestoneId}.json`), serialized);\n"
        "}\n\n"
        "main().catch((error) => {\n"
        "  console.error(error instanceof Error ? error.stack || error.message : String(error));\n"
        "  process.exit(1);\n"
        "});\n"
    )


# ---------------------------------------------------------------------------
# M1 foundation scaffold — tracker IDs A-01 / A-02 / A-03 / A-07 / A-08 / D-18
# ---------------------------------------------------------------------------

def _scaffold_m1_foundation(
    project_root: Path,
    *,
    has_nestjs: bool,
    has_nextjs: bool,
    cfg: ScaffoldConfig = DEFAULT_SCAFFOLD_CONFIG,
) -> list[str]:
    """Emit the deterministic M1 foundation: root files + backend + frontend bases.

    Idempotent — each helper writes only when the file does not exist, so
    later milestones and wave agents may extend or override. Templates reflect
    `milestones/milestone-1/REQUIREMENTS.md` directly: PORT 4000 baseline (N-12),
    Prisma 5 shutdown pattern, vitest + testing-library ready out of the box,
    `.gitignore` covering the expected tooling, docker-compose Postgres.
    """
    scaffolded: list[str] = []
    scaffolded.extend(_scaffold_root_files(project_root, cfg=cfg))  # A-08
    scaffolded.extend(_scaffold_docker_compose(project_root))  # A-01
    if has_nestjs:
        scaffolded.extend(_scaffold_api_foundation(project_root, cfg=cfg))  # A-02, A-03, D-18
    if has_nextjs:
        scaffolded.extend(_scaffold_web_foundation(project_root))  # A-07, D-18
    scaffolded.extend(_scaffold_packages_shared(project_root))  # N-03, DRIFT-7
    return scaffolded


def _write_if_missing(path: Path, content: str, *, project_root: Path) -> Optional[str]:
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    # NEW-2: stamp the content via _stamp_version when the module-level flag
    # is active (run_scaffolding toggles it on entry when
    # v18.template_version_stamping_enabled=True). Skip-extension files
    # (.json, .md) pass through unchanged.
    payload = content
    if _TEMPLATE_VERSION_STAMPING_ACTIVE:
        payload = _stamp_version(content, path.suffix)
    path.write_text(payload, encoding="utf-8")
    return _relpath(path, project_root)


def _scaffold_root_files(
    project_root: Path,
    *,
    cfg: ScaffoldConfig = DEFAULT_SCAFFOLD_CONFIG,
) -> list[str]:
    """A-08: `.gitignore` + `.env.example`; plus root `package.json` workspaces manifest.

    N-03 / DRIFT-4: also emits `pnpm-workspace.yaml` + `tsconfig.base.json` so
    `@taskflow/shared` path alias + `packages/*` workspace glob are in place for
    the shared package to resolve.
    """
    scaffolded: list[str] = []
    for rel, content in (
        (".gitignore", _gitignore_template()),
        (".env.example", _env_example_template(cfg)),
        ("package.json", _root_package_json_template()),
        ("pnpm-workspace.yaml", _root_pnpm_workspace_template()),
        ("tsconfig.base.json", _root_tsconfig_base_template()),
    ):
        result = _write_if_missing(project_root / rel, content, project_root=project_root)
        if result is not None:
            scaffolded.append(result)
    return scaffolded


def _scaffold_docker_compose(project_root: Path) -> list[str]:
    """A-01: root `docker-compose.yml` with Postgres + healthcheck + named volume."""
    path = project_root / "docker-compose.yml"
    result = _write_if_missing(path, _docker_compose_template(), project_root=project_root)
    return [result] if result is not None else []


def _scaffold_api_foundation(
    project_root: Path,
    *,
    cfg: ScaffoldConfig = DEFAULT_SCAFFOLD_CONFIG,
) -> list[str]:
    """A-02 (PORT default from cfg), A-03 (Prisma 5 shutdown hook), A-05 (clean
    validation pipe), D-18 (clean pins). N-12 threads ``cfg`` into drift-prone
    templates (main.ts / env.validation.ts)."""
    scaffolded: list[str] = []
    api_src = project_root / "apps" / "api" / "src"
    templates: tuple[tuple[Path, str], ...] = (
        (project_root / "apps" / "api" / "package.json", _api_package_json_template()),
        (api_src / "main.ts", _api_main_ts_template(cfg)),
        (api_src / "config" / "env.validation.ts", _api_env_validation_template(cfg)),
        (api_src / "database" / "prisma.service.ts", _api_prisma_service_template()),
        (api_src / "database" / "prisma.module.ts", _api_prisma_module_template()),
        (api_src / "common" / "pipes" / "validation.pipe.ts", _api_validation_pipe_template()),
    )
    for path, content in templates:
        result = _write_if_missing(path, content, project_root=project_root)
        if result is not None:
            scaffolded.append(result)
    scaffolded.extend(_scaffold_prisma_schema_and_migrations(project_root))
    return scaffolded


def _scaffold_web_foundation(project_root: Path) -> list[str]:
    """A-06 (RTL baseline + ESLint rule), A-07 (vitest + jsdom), D-18 (pins).

    N-06 / DRIFT-6: extends apps/web emission from the A-06/A-07 baseline to
    the full 15-file scaffold contract (next.config.mjs, tsconfig.json,
    postcss.config.mjs, openapi-ts.config.ts, .env.example, Dockerfile, and
    app-router stubs for layout/page/middleware + vitest setup). Stubs are
    minimum-viable Next.js 15 app-router shapes — Wave D finalizes with
    business content. AUD-022: vitest.config.ts wires setupFiles to
    src/test/setup.ts so the import is actually sourced.
    """
    scaffolded: list[str] = []
    web_dir = project_root / "apps" / "web"
    templates: tuple[tuple[Path, str], ...] = (
        (web_dir / "package.json", _web_package_json_template()),
        (web_dir / "vitest.config.ts", _web_vitest_config_template()),
        (web_dir / "tailwind.config.ts", _web_tailwind_config_template()),
        (web_dir / "src" / "styles" / "globals.css", _web_globals_css_template()),
        (web_dir / "eslint.config.js", _web_eslint_config_template()),
        # N-06: 10 new canonical emissions closing DRIFT-6.
        (web_dir / "next.config.mjs", _web_next_config_template()),
        (web_dir / "tsconfig.json", _web_tsconfig_template()),
        (web_dir / "postcss.config.mjs", _web_postcss_config_template()),
        (web_dir / "openapi-ts.config.ts", _web_openapi_ts_config_template()),
        (web_dir / ".env.example", _web_env_example_template()),
        (web_dir / "Dockerfile", _web_dockerfile_template()),
        (web_dir / "src" / "app" / "layout.tsx", _web_layout_stub_template()),
        (web_dir / "src" / "app" / "page.tsx", _web_page_stub_template()),
        (web_dir / "src" / "middleware.ts", _web_middleware_stub_template()),
        (web_dir / "src" / "test" / "setup.ts", _web_test_setup_template()),
    )
    for path, content in templates:
        result = _write_if_missing(path, content, project_root=project_root)
        if result is not None:
            scaffolded.append(result)
    return scaffolded


def _scaffold_packages_shared(project_root: Path) -> list[str]:
    """N-03: emit `packages/shared/*` baseline (6 files) per M1 REQUIREMENTS.

    Constants (enums, error codes, pagination types) are copied VERBATIM from
    `milestones/milestone-1/REQUIREMENTS.md` lines 340-368. Scaffold owns these
    because they are spec-defined baseline — not derived from wave-B domain
    modelling. All downstream consumers (AllExceptionsFilter, frontend error
    mapping, TransformResponseInterceptor) import from `@taskflow/shared`.
    """
    scaffolded: list[str] = []
    shared_dir = project_root / "packages" / "shared"
    src_dir = shared_dir / "src"
    templates: tuple[tuple[Path, str], ...] = (
        (shared_dir / "package.json", _packages_shared_package_json_template()),
        (shared_dir / "tsconfig.json", _packages_shared_tsconfig_template()),
        (src_dir / "enums.ts", _packages_shared_enums_template()),
        (src_dir / "error-codes.ts", _packages_shared_error_codes_template()),
        (src_dir / "pagination.ts", _packages_shared_pagination_template()),
        (src_dir / "index.ts", _packages_shared_index_template()),
    )
    for path, content in templates:
        result = _write_if_missing(path, content, project_root=project_root)
        if result is not None:
            scaffolded.append(result)
    return scaffolded


# --- templates --------------------------------------------------------------

def _gitignore_template() -> str:
    return (
        "# Dependencies\n"
        "node_modules/\n"
        "apps/*/node_modules/\n"
        "packages/*/node_modules/\n"
        "\n"
        "# Build output\n"
        "dist/\n"
        "apps/*/dist/\n"
        "packages/*/dist/\n"
        ".next/\n"
        "apps/*/.next/\n"
        ".turbo/\n"
        "\n"
        "# Test / coverage\n"
        "coverage/\n"
        "apps/*/coverage/\n"
        "\n"
        "# Env — never commit real secrets. Use .env.example as the template.\n"
        ".env\n"
        ".env.local\n"
        ".env.*.local\n"
        "apps/*/.env\n"
        "apps/*/.env.local\n"
        "\n"
        "# Editors\n"
        ".vscode/\n"
        ".idea/\n"
        "*.log\n"
    )


def _env_example_template(cfg: ScaffoldConfig = DEFAULT_SCAFFOLD_CONFIG) -> str:
    # N-12: PORT is sourced from ScaffoldConfig (default 4000 per canonical M1
    # REQUIREMENTS). Flag-ON path passes a reconciler-derived ScaffoldConfig.
    return (
        "# M1 baseline env — copy to .env and fill per environment.\n"
        "NODE_ENV=development\n"
        f"PORT={cfg.port}\n"
        "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/app?schema=public\n"
        "POSTGRES_USER=postgres\n"
        "POSTGRES_PASSWORD=postgres\n"
        "POSTGRES_DB=app\n"
        "JWT_SECRET=change-me\n"
        "JWT_EXPIRES_IN=3600s\n"
        "FRONTEND_ORIGIN=http://localhost:3000\n"
    )


def _root_package_json_template() -> str:
    return json.dumps(
        {
            "name": "app",
            "version": "1.0.0",
            "private": True,
            "workspaces": ["apps/*", "packages/*"],
            "scripts": {
                "build:api": "npm --workspace apps/api run build",
                "build:web": "npm --workspace apps/web run build",
                "dev:api": "npm --workspace apps/api run start:dev",
                "dev:web": "npm --workspace apps/web run dev",
                "test:api": "npm --workspace apps/api run test",
                "test:web": "npm --workspace apps/web run test",
                "test": "npm run test:api && npm run test:web",
            },
        },
        indent=2,
    ) + "\n"


def _docker_compose_template() -> str:
    # N-07 (Phase B, DRIFT-5): postgres + api + web topology with healthcheck
    # and long-form `depends_on.condition: service_healthy` wiring. PORT=4000
    # is canonical per DRIFT-3. Compose v2+ omits the obsolete top-level
    # `version:` key per context7 /docker/compose canonical examples.
    return (
        "services:\n"
        "  postgres:\n"
        "    image: postgres:16-alpine\n"
        "    ports:\n"
        '      - "5432:5432"\n'
        "    environment:\n"
        "      POSTGRES_USER: ${POSTGRES_USER:-postgres}\n"
        "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}\n"
        "      POSTGRES_DB: ${POSTGRES_DB:-app}\n"
        "    volumes:\n"
        "      - postgres_data:/var/lib/postgresql/data\n"
        "    healthcheck:\n"
        '      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-app}"]\n'
        "      interval: 10s\n"
        "      timeout: 5s\n"
        "      retries: 5\n"
        "\n"
        "  api:\n"
        "    build:\n"
        "      context: ./apps/api\n"
        "    ports:\n"
        '      - "4000:4000"\n'
        "    environment:\n"
        "      DATABASE_URL: postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-postgres}@postgres:5432/${POSTGRES_DB:-app}?schema=public\n"
        '      PORT: "4000"\n'
        "      JWT_SECRET: ${JWT_SECRET:-dev-secret-change-me}\n"
        "    depends_on:\n"
        "      postgres:\n"
        "        condition: service_healthy\n"
        "    healthcheck:\n"
        '      test: ["CMD-SHELL", "curl -f http://localhost:4000/api/health || exit 1"]\n'
        "      interval: 10s\n"
        "      timeout: 5s\n"
        "      retries: 5\n"
        "    volumes:\n"
        "      - ./apps/api/src:/app/src\n"
        "      - ./apps/api/prisma:/app/prisma\n"
        "\n"
        "  web:\n"
        "    build:\n"
        "      context: ./apps/web\n"
        "    ports:\n"
        '      - "3000:3000"\n'
        "    environment:\n"
        "      NEXT_PUBLIC_API_URL: http://localhost:4000/api\n"
        "      INTERNAL_API_URL: http://api:4000/api\n"
        "    depends_on:\n"
        "      api:\n"
        "        condition: service_healthy\n"
        "\n"
        "volumes:\n"
        "  postgres_data:\n"
    )


def _api_package_json_template() -> str:
    # D-18: dependency pins tracked against npm audit as of 2026-04. Minimum
    # floors (Next 15.1+, NestJS 11+, Prisma 6+) are enforced in
    # tests/test_scaffold_m1_correctness.py::TestD18NonVulnerablePins.
    return json.dumps(
        {
            "name": "api",
            "version": "1.0.0",
            "private": True,
            "scripts": {
                "build": "nest build",
                "start": "node dist/main.js",
                "start:dev": "nest start --watch",
                "test": "jest --runInBand --passWithNoTests",
                "test:watch": "jest --watch",
                "openapi": "ts-node -r tsconfig-paths/register ../../scripts/generate-openapi.ts",
            },
            "prisma": {"seed": "ts-node prisma/seed.ts"},
            "dependencies": {
                "@nestjs/common": "^11.0.0",
                "@nestjs/config": "^4.0.0",
                "@nestjs/core": "^11.0.0",
                "@nestjs/jwt": "^11.0.0",
                "@nestjs/passport": "^11.0.0",
                "@nestjs/platform-express": "^11.0.0",
                "@nestjs/swagger": "^11.0.0",
                "@prisma/client": "^6.0.0",
                "class-transformer": "^0.5.1",
                "class-validator": "^0.14.1",
                "helmet": "^8.0.0",
                "joi": "^17.13.3",
                "passport": "^0.7.0",
                "passport-jwt": "^4.0.1",
                "prisma": "^6.0.0",
                "reflect-metadata": "^0.2.2",
                "rxjs": "^7.8.1",
            },
            "devDependencies": {
                "@nestjs/cli": "^11.0.0",
                "@nestjs/schematics": "^11.0.0",
                "@nestjs/testing": "^11.0.0",
                "@types/jest": "^29.5.14",
                "@types/node": "^22.10.2",
                "@types/passport-jwt": "^4.0.1",
                "jest": "^29.7.0",
                "ts-jest": "^29.2.5",
                "ts-node": "^10.9.2",
                "tsconfig-paths": "^4.2.0",
                "typescript": "^5.7.2",
            },
        },
        indent=2,
    ) + "\n"


def _api_main_ts_template(cfg: ScaffoldConfig = DEFAULT_SCAFFOLD_CONFIG) -> str:
    # N-12: PORT default is sourced from ScaffoldConfig (default 4000 per
    # canonical M1 REQUIREMENTS). env.validation.ts is the canonical
    # source; the fallback here matches it for the case where the env var is
    # unset at boot.
    return (
        "import { Logger, ValidationPipe } from '@nestjs/common';\n"
        "import { NestFactory } from '@nestjs/core';\n"
        "import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';\n"
        "import { AppModule } from './app.module';\n"
        "\n"
        "async function bootstrap(): Promise<void> {\n"
        "  const app = await NestFactory.create(AppModule);\n"
        "  const logger = new Logger('Bootstrap');\n"
        "\n"
        "  app.setGlobalPrefix('api', { exclude: ['health'] });\n"
        "  app.enableCors({\n"
        "    origin: process.env.FRONTEND_ORIGIN,\n"
        "    credentials: true,\n"
        "  });\n"
        "  app.useGlobalPipes(\n"
        "    new ValidationPipe({\n"
        "      whitelist: true,\n"
        "      forbidNonWhitelisted: true,\n"
        "      transform: true,\n"
        "    }),\n"
        "  );\n"
        "\n"
        "  const config = new DocumentBuilder()\n"
        "    .setTitle('API')\n"
        "    .setVersion('1.0.0')\n"
        "    .addBearerAuth()\n"
        "    .build();\n"
        "  const document = SwaggerModule.createDocument(app, config);\n"
        "  SwaggerModule.setup('api/docs', app, document);\n"
        "\n"
        f"  // N-12: M1 dev-api port baseline is {cfg.port}.\n"
        f"  const port = Number(process.env.PORT ?? {cfg.port});\n"
        "  await app.listen(port);\n"
        "  logger.log(`API listening on port ${port}`);\n"
        "}\n"
        "\n"
        "void bootstrap();\n"
    )


def _api_env_validation_template(cfg: ScaffoldConfig = DEFAULT_SCAFFOLD_CONFIG) -> str:
    # N-12: Joi schema with PORT default sourced from ScaffoldConfig.
    return (
        "import * as Joi from 'joi';\n"
        "\n"
        f"// N-12: PORT default is {cfg.port} (M1 dev-api port baseline). Do not\n"
        "// change without updating .env.example and apps/api/src/main.ts in\n"
        "// lock step.\n"
        "export const envValidationSchema = Joi.object({\n"
        "  NODE_ENV: Joi.string()\n"
        "    .valid('development', 'test', 'production')\n"
        "    .default('development'),\n"
        f"  PORT: Joi.number().integer().positive().default({cfg.port}),\n"
        "  DATABASE_URL: Joi.string().uri({ scheme: ['postgres', 'postgresql'] }).required(),\n"
        "  JWT_SECRET: Joi.string().min(16).required(),\n"
        "  JWT_EXPIRES_IN: Joi.string().default('3600s'),\n"
        "  FRONTEND_ORIGIN: Joi.string().uri().default('http://localhost:3000'),\n"
        "});\n"
    )


def _api_prisma_service_template() -> str:
    # A-03: Prisma 5+ removed `$on('beforeExit')` from the library engine. Use
    # the Node process hook instead so `app.close()` triggers on SIGTERM.
    # Verified against Prisma migration guidance (context7 /prisma/prisma).
    return (
        "import { INestApplication, Injectable, OnModuleInit } from '@nestjs/common';\n"
        "import { PrismaClient } from '@prisma/client';\n"
        "\n"
        "@Injectable()\n"
        "export class PrismaService extends PrismaClient implements OnModuleInit {\n"
        "  async onModuleInit(): Promise<void> {\n"
        "    await this.$connect();\n"
        "  }\n"
        "\n"
        "  // A-03: Prisma 5+ no longer emits `beforeExit` via `$on`. Register\n"
        "  // the Node-level hook instead so Nest cleans up on SIGTERM.\n"
        "  async enableShutdownHooks(app: INestApplication): Promise<void> {\n"
        "    process.on('beforeExit', async () => {\n"
        "      await app.close();\n"
        "    });\n"
        "  }\n"
        "}\n"
    )


def _api_prisma_module_template() -> str:
    return (
        "import { Global, Module } from '@nestjs/common';\n"
        "import { PrismaService } from './prisma.service';\n"
        "\n"
        "@Global()\n"
        "@Module({\n"
        "  providers: [PrismaService],\n"
        "  exports: [PrismaService],\n"
        "})\n"
        "export class PrismaModule {}\n"
    )


def _api_prisma_schema_template() -> str:
    # N-05 / DRIFT-1: emits the bootstrap schema.prisma stub at
    # apps/api/prisma/schema.prisma (canonical location per /prisma/prisma
    # docs). Wave B extends with domain models in later milestones; M1 needs
    # only datasource + generator so `prisma generate` and `prisma migrate
    # deploy` can run against the paired initial migration stub.
    return (
        "// This is your Prisma schema file,\n"
        "// learn more about it in the docs: https://pris.ly/d/prisma-schema\n"
        "\n"
        "generator client {\n"
        '  provider = "prisma-client-js"\n'
        "}\n"
        "\n"
        "datasource db {\n"
        '  provider = "postgresql"\n'
        '  url      = env("DATABASE_URL")\n'
        "}\n"
    )


def _prisma_initial_migration_sql_template() -> str:
    # N-05: empty-but-valid SQL stub. M1 has no domain models; Wave B adds
    # them in later milestones. The directory must exist with a non-empty
    # migration.sql + migration_lock.toml so `prisma migrate deploy` does not
    # error on an empty migrations folder during M1 boot.
    return (
        "-- Phase B scaffold - empty initial migration for M1 foundation.\n"
        "-- Domain models are added in subsequent milestones; this stub exists\n"
        "-- so `prisma migrate deploy` has a non-empty migrations directory on\n"
        "-- M1 boot.\n"
    )


def _prisma_migration_lock_template() -> str:
    # N-05: canonical Prisma `migrate dev` output format. Verified against
    # /prisma/prisma context7 docs - provider must match datasource block in
    # schema.prisma (postgresql, not postgres).
    return (
        "# Please do not edit this file manually\n"
        "# It should be added in your version-control system (i.e. Git)\n"
        'provider = "postgresql"\n'
    )


def _scaffold_prisma_schema_and_migrations(project_root: Path) -> list[str]:
    """N-05 / DRIFT-1: emit schema.prisma bootstrap + initial migration stub.

    Order-sensitive: schema.prisma first (declares datasource), then the
    paired migration folder + migration_lock.toml. Scaffold-verifier (N-13)
    checks both exist with the canonical provider value.
    """
    scaffolded: list[str] = []
    prisma_dir = project_root / "apps" / "api" / "prisma"
    mig_dir = prisma_dir / "migrations" / "20260101000000_init"
    emissions: tuple[tuple[Path, str], ...] = (
        (prisma_dir / "schema.prisma", _api_prisma_schema_template()),
        (mig_dir / "migration.sql", _prisma_initial_migration_sql_template()),
        (prisma_dir / "migrations" / "migration_lock.toml", _prisma_migration_lock_template()),
    )
    for path, content in emissions:
        result = _write_if_missing(path, content, project_root=project_root)
        if result is not None:
            scaffolded.append(result)
    return scaffolded


def _web_package_json_template() -> str:
    # A-07: vitest + testing-library + jsdom pinned deterministically. D-18:
    # floors verified clean against npm advisory data as of 2026-04. Bumping
    # these requires updating the corresponding test assertions in
    # tests/test_scaffold_m1_correctness.py.
    return json.dumps(
        {
            "name": "web",
            "version": "1.0.0",
            "private": True,
            "scripts": {
                "dev": "next dev",
                "build": "next build",
                "start": "next start",
                "test": "vitest run --passWithNoTests",
            },
            "dependencies": {
                "@hey-api/client-fetch": "^0.8.0",
                "next": "^15.1.0",
                "next-intl": "^3.26.5",
                "react": "^19.0.0",
                "react-dom": "^19.0.0",
            },
            "devDependencies": {
                "@hey-api/openapi-ts": "^0.64.0",
                "@testing-library/jest-dom": "^6.6.0",
                "@testing-library/react": "^16.1.0",
                "@types/node": "^22.10.2",
                "@types/react": "^19.0.2",
                "@types/react-dom": "^19.0.2",
                "@vitejs/plugin-react": "^4.3.4",
                "autoprefixer": "^10.4.20",
                "jsdom": "^25.0.0",
                "postcss": "^8.4.49",
                "tailwindcss": "^3.4.17",
                "typescript": "^5.7.2",
                "vitest": "^2.1.0",
            },
        },
        indent=2,
    ) + "\n"


def _web_vitest_config_template() -> str:
    # AUD-022: setupFiles must point at the scaffold-emitted src/test/setup.ts
    # (see `_web_test_setup_template`) so @testing-library/jest-dom matchers
    # actually load. Prior config referenced the path without the file being
    # emitted — vitest would silently skip setup and DOM assertions drifted.
    return (
        "import { defineConfig } from 'vitest/config';\n"
        "import react from '@vitejs/plugin-react';\n"
        "\n"
        "export default defineConfig({\n"
        "  plugins: [react()],\n"
        "  test: {\n"
        "    environment: 'jsdom',\n"
        "    globals: true,\n"
        "    css: false,\n"
        "    setupFiles: ['./src/test/setup.ts'],\n"
        "    passWithNoTests: true,\n"
        "  },\n"
        "});\n"
    )


def _api_validation_pipe_template() -> str:
    # A-05: standard NestJS ValidationPipe with whitelist + forbidNonWhitelisted
    # + transform. Explicitly NO custom key rewriting — build-j's `normalizeInput`
    # was masking a DTO/contract misalignment (snake_case DTO fields vs
    # camelCase contract). See v18 test runs/session-02-validation/
    # a05-investigation.md for the Session 3+ follow-up (DTO rename + drop
    # serializeOutput on the response path).
    return (
        "import { Injectable, ValidationPipe, ValidationPipeOptions } from '@nestjs/common';\n"
        "\n"
        "const validationOptions: ValidationPipeOptions = {\n"
        "  whitelist: true,\n"
        "  forbidNonWhitelisted: true,\n"
        "  transform: true,\n"
        "  transformOptions: {\n"
        "    enableImplicitConversion: true,\n"
        "  },\n"
        "};\n"
        "\n"
        "@Injectable()\n"
        "export class AppValidationPipe extends ValidationPipe {\n"
        "  constructor() {\n"
        "    super(validationOptions);\n"
        "  }\n"
        "}\n"
    )


def _web_tailwind_config_template() -> str:
    # A-06: Tailwind 3.4 ships logical-property utilities (ps-*/pe-*/ms-*/me-*)
    # via the default `corePlugins` — no opt-in required. This config only
    # keeps preflight on and sets the M1 design tokens. Physical-spacing
    # utilities are rejected by the scaffolded eslint.config.js — see
    # v18 test runs/session-02-validation/a06-investigation.md.
    return (
        "import type { Config } from 'tailwindcss';\n"
        "\n"
        "// A-06 RTL baseline: rely on Tailwind 3.4 default core plugins for\n"
        "// logical-property utilities (ps-*/pe-*/ms-*/me-*). Physical spacing\n"
        "// utilities (px-*/py-*/mx-*/my-*/etc) are blocked in eslint.config.js.\n"
        "const config: Config = {\n"
        "  content: [\n"
        "    './src/**/*.{ts,tsx}',\n"
        "    './messages/*.json',\n"
        "  ],\n"
        "  corePlugins: {\n"
        "    preflight: true,\n"
        "  },\n"
        "  theme: {\n"
        "    extend: {\n"
        "      colors: {\n"
        "        primary: '#0F172A',\n"
        "        secondary: '#475569',\n"
        "        accent: '#f59e0b',\n"
        "        surface: '#ffffff',\n"
        "        border: '#cbd5e1',\n"
        "        error: '#dc2626',\n"
        "        warning: '#f59e0b',\n"
        "        success: '#16a34a',\n"
        "        info: '#0ea5e9',\n"
        "      },\n"
        "      fontFamily: {\n"
        "        sans: ['var(--font-inter)', 'Inter', 'system-ui', 'sans-serif'],\n"
        "        mono: ['var(--font-jetbrains-mono)', 'JetBrains Mono', 'monospace'],\n"
        "      },\n"
        "      borderRadius: {\n"
        "        md: '0.75rem',\n"
        "      },\n"
        "    },\n"
        "  },\n"
        "  plugins: [],\n"
        "};\n"
        "\n"
        "export default config;\n"
    )


def _web_globals_css_template() -> str:
    # A-06: RTL baseline — all spacing/layout declarations use CSS logical
    # properties (min-block-size, inline-size, text-align: start) so rtl/ltr
    # flows correctly. Authors must use Tailwind's ps-*/pe-*/ms-*/me-*
    # utilities; physical spacing is blocked by eslint.config.js.
    return (
        "@tailwind base;\n"
        "@tailwind components;\n"
        "@tailwind utilities;\n"
        "\n"
        "/* A-06 RTL baseline: use CSS logical properties only. Tailwind's\n"
        "   ps-*/pe-*/ms-*/me-* utilities replace px-*/py-*/mx-*/my-*. */\n"
        ":root {\n"
        "  color-scheme: light;\n"
        "  --background: #f8fbff;\n"
        "  --foreground: #0f172a;\n"
        "  --surface: #ffffff;\n"
        "  --border: #cbd5e1;\n"
        "  --accent: #f59e0b;\n"
        "  --primary: #0f172a;\n"
        "  --secondary: #475569;\n"
        "}\n"
        "\n"
        "*,\n"
        "*::before,\n"
        "*::after {\n"
        "  box-sizing: border-box;\n"
        "}\n"
        "\n"
        "html {\n"
        "  min-block-size: 100%;\n"
        "  scroll-behavior: smooth;\n"
        "}\n"
        "\n"
        "html[dir=\"rtl\"] {\n"
        "  text-align: start;\n"
        "}\n"
        "\n"
        "body {\n"
        "  min-block-size: 100vh;\n"
        "  margin: 0;\n"
        "  background: var(--background);\n"
        "  color: var(--foreground);\n"
        "  font-family: var(--font-inter), Inter, system-ui, sans-serif;\n"
        "}\n"
        "\n"
        "input,\n"
        "select,\n"
        "textarea {\n"
        "  inline-size: 100%;\n"
        "  font: inherit;\n"
        "}\n"
    )


def _web_eslint_config_template() -> str:
    # A-06: flat-config ESLint rule rejecting physical Tailwind spacing
    # utilities in JSX className strings and template literals. Authors get
    # an actionable error pointing at the logical-property replacement.
    physical_families = "px-|py-|mx-|my-|pl-|pr-|pt-|pb-|ml-|mr-|mt-|mb-"
    return (
        "// A-06: enforce CSS logical properties — reject physical Tailwind\n"
        "// spacing utilities. Use ps-*/pe-* (inline) and mt-*/mb-* block\n"
        "// equivalents via logical-property classes as Tailwind 3.4 supports\n"
        "// them natively.\n"
        "const PHYSICAL_SPACING_REGEX = String.raw`\\b("
        + physical_families
        + ")\\d`;\n"
        "\n"
        "module.exports = [\n"
        "  {\n"
        "    files: ['src/**/*.{ts,tsx,js,jsx}'],\n"
        "    rules: {\n"
        "      'no-restricted-syntax': [\n"
        "        'error',\n"
        "        {\n"
        "          selector:\n"
        "            `Literal[value=/${PHYSICAL_SPACING_REGEX}/]`,\n"
        "          message:\n"
        "            'Use CSS logical properties: ps-*/pe-*/ms-*/me-* instead of px-*/py-*/mx-*/my-* (A-06 RTL baseline).',\n"
        "        },\n"
        "        {\n"
        "          selector:\n"
        "            `TemplateElement[value.raw=/${PHYSICAL_SPACING_REGEX}/]`,\n"
        "          message:\n"
        "            'Use CSS logical properties: ps-*/pe-*/ms-*/me-* instead of px-*/py-*/mx-*/my-* (A-06 RTL baseline).',\n"
        "        },\n"
        "      ],\n"
        "    },\n"
        "  },\n"
        "];\n"
    )


def _web_next_config_template() -> str:
    """apps/web/next.config.mjs — Next.js 15 app-router minimum shape.

    context7 /vercel/next.js: `next.config.mjs` only needs to export the
    NextConfig object. Kept minimal here; Wave D / later milestones may layer
    on image domains, i18n routing, redirects, etc.
    """
    return (
        "/** @type {import('next').NextConfig} */\n"
        "const nextConfig = {};\n"
        "\n"
        "export default nextConfig;\n"
    )


def _web_tsconfig_template() -> str:
    """apps/web/tsconfig.json — extends root base, jsx: preserve, path aliases.

    Path aliases mirror the root `tsconfig.base.json` mapping: `@/*` for
    in-package imports and `@taskflow/shared` for the workspace package.
    jsx='preserve' is the Next.js 15 app-router default (Next compiles JSX).
    """
    return (
        "{\n"
        '  "extends": "../../tsconfig.base.json",\n'
        '  "compilerOptions": {\n'
        '    "target": "ES2022",\n'
        '    "module": "esnext",\n'
        '    "moduleResolution": "bundler",\n'
        '    "jsx": "preserve",\n'
        '    "lib": ["DOM", "DOM.Iterable", "ES2022"],\n'
        '    "allowJs": true,\n'
        '    "noEmit": true,\n'
        '    "incremental": true,\n'
        '    "resolveJsonModule": true,\n'
        '    "isolatedModules": true,\n'
        '    "baseUrl": ".",\n'
        '    "paths": {\n'
        '      "@/*": ["src/*"],\n'
        '      "@taskflow/shared": ["../../packages/shared/src"],\n'
        '      "@taskflow/shared/*": ["../../packages/shared/src/*"]\n'
        "    },\n"
        '    "plugins": [{ "name": "next" }]\n'
        "  },\n"
        '  "include": ["next-env.d.ts", "src/**/*.ts", "src/**/*.tsx", ".next/types/**/*.ts"],\n'
        '  "exclude": ["node_modules"]\n'
        "}\n"
    )


def _web_postcss_config_template() -> str:
    """apps/web/postcss.config.mjs — Tailwind 3 + autoprefixer under Next.js 15.

    context7 /vercel/next.js (postcss + Tailwind integration): Next.js 15
    expects an ES-module `postcss.config.mjs` exporting `{ plugins: { ... } }`
    when using Tailwind v3. The object form (not array) is required for
    zero-config Next auto-detection.
    """
    return (
        "const config = {\n"
        "  plugins: {\n"
        "    tailwindcss: {},\n"
        "    autoprefixer: {},\n"
        "  },\n"
        "};\n"
        "\n"
        "export default config;\n"
    )


def _web_openapi_ts_config_template() -> str:
    """apps/web/openapi-ts.config.ts — Wave C generator source-of-truth.

    context7 /hey-api/openapi-ts: `defineConfig({input, output, plugins})` is
    the canonical TS config form. Plugin names are the 3 default
    `@hey-api/*` names (typescript, sdk, client-fetch). Input points at the
    openapi.json emitted by apps/api `generate-openapi.ts`.
    """
    return (
        "import { defineConfig } from '@hey-api/openapi-ts';\n"
        "\n"
        "export default defineConfig({\n"
        "  input: '../api/openapi.json',\n"
        "  output: 'src/lib/api/generated',\n"
        "  plugins: [\n"
        "    '@hey-api/typescript',\n"
        "    '@hey-api/sdk',\n"
        "    '@hey-api/client-fetch',\n"
        "  ],\n"
        "});\n"
    )


def _web_env_example_template() -> str:
    """apps/web/.env.example — canonical API URL pair per M1 REQUIREMENTS.

    DRIFT-3: PORT=4000 is the canonical backend port. `NEXT_PUBLIC_API_URL` is
    the browser-visible base (localhost), `INTERNAL_API_URL` is the service
    hostname inside the docker-compose network (`api`) for server-side calls.
    """
    return (
        "# Public base URL — exposed to the browser bundle.\n"
        "NEXT_PUBLIC_API_URL=http://localhost:4000/api\n"
        "\n"
        "# Internal docker-compose service URL — used by Next.js server runtime.\n"
        "INTERNAL_API_URL=http://api:4000/api\n"
    )


def _web_dockerfile_template() -> str:
    """apps/web/Dockerfile — multi-stage node:20-alpine build producing a
    `next start` runtime image on port 3000.

    Standard pnpm workflow: deps stage installs from lockfile, build stage
    compiles, runner stage copies the built `.next` + minimal deps. `next
    build` requires the full app to be present; no standalone output mode.
    """
    return (
        "# syntax=docker/dockerfile:1.6\n"
        "FROM node:20-alpine AS base\n"
        "RUN corepack enable && corepack prepare pnpm@latest --activate\n"
        "WORKDIR /app\n"
        "\n"
        "FROM base AS deps\n"
        "COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml ./\n"
        "COPY apps/web/package.json apps/web/\n"
        "COPY packages/shared/package.json packages/shared/\n"
        "RUN pnpm install --frozen-lockfile\n"
        "\n"
        "FROM base AS build\n"
        "COPY --from=deps /app/node_modules ./node_modules\n"
        "COPY --from=deps /app/apps/web/node_modules ./apps/web/node_modules\n"
        "COPY . .\n"
        "WORKDIR /app/apps/web\n"
        "RUN pnpm next build\n"
        "\n"
        "FROM base AS runner\n"
        "ENV NODE_ENV=production\n"
        "WORKDIR /app/apps/web\n"
        "COPY --from=build /app/apps/web/.next ./.next\n"
        "COPY --from=build /app/apps/web/public ./public\n"
        "COPY --from=build /app/apps/web/package.json ./package.json\n"
        "COPY --from=build /app/node_modules /app/node_modules\n"
        "EXPOSE 3000\n"
        "CMD [\"pnpm\", \"next\", \"start\"]\n"
    )


def _web_layout_stub_template() -> str:
    """apps/web/src/app/layout.tsx — minimum-viable Next.js 15 root layout.

    context7 /vercel/next.js: the root layout must render `<html>` and
    `<body>` elements; anything less fails `next build`. Wave D replaces this
    stub with app-specific chrome (fonts, providers, metadata).
    """
    return (
        "// SCAFFOLD STUB — Wave D finalizes with app-specific chrome.\n"
        "export default function RootLayout({\n"
        "  children,\n"
        "}: {\n"
        "  children: React.ReactNode;\n"
        "}) {\n"
        "  return (\n"
        "    <html lang=\"en\">\n"
        "      <body>{children}</body>\n"
        "    </html>\n"
        "  );\n"
        "}\n"
    )


def _web_page_stub_template() -> str:
    """apps/web/src/app/page.tsx — minimum-viable root route.

    Next.js 15 app-router requires a default-exported React component per
    route segment. Wave D replaces with the M1 landing content.
    """
    return (
        "// SCAFFOLD STUB — Wave D finalizes with M1 landing content.\n"
        "export default function HomePage() {\n"
        "  return <main>TaskFlow</main>;\n"
        "}\n"
    )


def _web_middleware_stub_template() -> str:
    """apps/web/src/middleware.ts — passthrough stub with empty matcher.

    context7 /vercel/next.js: middleware signature is `(request: NextRequest)`
    returning a `NextResponse`. Empty matcher array means the middleware runs
    for no routes until Wave D enables JWT cookie forwarding.
    """
    return (
        "// SCAFFOLD STUB — Wave D finalizes with JWT cookie forwarding.\n"
        "import type { NextRequest } from 'next/server';\n"
        "import { NextResponse } from 'next/server';\n"
        "\n"
        "export function middleware(_request: NextRequest): NextResponse {\n"
        "  return NextResponse.next();\n"
        "}\n"
        "\n"
        "export const config = {\n"
        "  matcher: [],\n"
        "};\n"
    )


def _web_test_setup_template() -> str:
    """apps/web/src/test/setup.ts — vitest global setup (AUD-022).

    Imports `@testing-library/jest-dom` so DOM matchers (toBeInTheDocument,
    etc.) are registered before any spec runs. Sourced via the setupFiles
    entry in `_web_vitest_config_template`.
    """
    return (
        "// Vitest global setup — registers @testing-library/jest-dom matchers.\n"
        "// Sourced by vitest.config.ts `setupFiles`. (AUD-022)\n"
        "import '@testing-library/jest-dom';\n"
    )


def _root_pnpm_workspace_template() -> str:
    """Root `pnpm-workspace.yaml` per REQUIREMENTS lines 39-44."""
    return (
        "packages:\n"
        "  - 'apps/*'\n"
        "  - 'packages/*'\n"
    )


def _root_tsconfig_base_template() -> str:
    """Root `tsconfig.base.json` with path aliases for workspace packages.

    REQUIREMENTS lines 48-50 declare `@taskflow/api-client` and `@taskflow/shared`
    path mappings. `composite`-friendly base — individual packages set their own
    `composite: true` and extend this file.
    """
    return (
        "{\n"
        '  "compilerOptions": {\n'
        '    "target": "ES2022",\n'
        '    "module": "commonjs",\n'
        '    "lib": ["ES2022"],\n'
        '    "strict": true,\n'
        '    "esModuleInterop": true,\n'
        '    "skipLibCheck": true,\n'
        '    "forceConsistentCasingInFileNames": true,\n'
        '    "declaration": true,\n'
        '    "resolveJsonModule": true,\n'
        '    "baseUrl": ".",\n'
        '    "paths": {\n'
        '      "@taskflow/shared": ["packages/shared/src"],\n'
        '      "@taskflow/shared/*": ["packages/shared/src/*"],\n'
        '      "@taskflow/api-client": ["packages/api-client/src"],\n'
        '      "@taskflow/api-client/*": ["packages/api-client/src/*"]\n'
        "    }\n"
        "  }\n"
        "}\n"
    )


def _packages_shared_package_json_template() -> str:
    """packages/shared minimal pnpm workspace manifest (@taskflow/shared)."""
    return (
        "{\n"
        '  "name": "@taskflow/shared",\n'
        '  "version": "0.1.0",\n'
        '  "private": true,\n'
        '  "main": "./src/index.ts",\n'
        '  "types": "./src/index.ts"\n'
        "}\n"
    )


def _packages_shared_tsconfig_template() -> str:
    """packages/shared tsconfig — composite project extending root base."""
    return (
        "{\n"
        '  "extends": "../../tsconfig.base.json",\n'
        '  "compilerOptions": {\n'
        '    "composite": true,\n'
        '    "declaration": true,\n'
        '    "outDir": "./dist",\n'
        '    "rootDir": "./src"\n'
        "  },\n"
        '  "include": ["src/**/*"]\n'
        "}\n"
    )


def _packages_shared_enums_template() -> str:
    """packages/shared/src/enums.ts — VERBATIM from REQUIREMENTS lines 339-343."""
    return (
        "// src/enums.ts — re-export Prisma enums so frontend can import without @prisma/client\n"
        "export enum UserRole { ADMIN = 'ADMIN', MEMBER = 'MEMBER' }\n"
        "export enum ProjectStatus { ACTIVE = 'ACTIVE', ARCHIVED = 'ARCHIVED' }\n"
        "export enum TaskStatus { TODO = 'TODO', IN_PROGRESS = 'IN_PROGRESS', IN_REVIEW = 'IN_REVIEW', DONE = 'DONE' }\n"
        "export enum TaskPriority { LOW = 'LOW', MEDIUM = 'MEDIUM', HIGH = 'HIGH', URGENT = 'URGENT' }\n"
    )


def _packages_shared_error_codes_template() -> str:
    """packages/shared/src/error-codes.ts — VERBATIM from REQUIREMENTS lines 345-364."""
    return (
        "// src/error-codes.ts — stable codes used by AllExceptionsFilter AND frontend error mapping\n"
        "export const ErrorCodes = {\n"
        "  VALIDATION_ERROR: 'VALIDATION_ERROR',\n"
        "  UNAUTHORIZED: 'UNAUTHORIZED',\n"
        "  FORBIDDEN: 'FORBIDDEN',\n"
        "  NOT_FOUND: 'NOT_FOUND',\n"
        "  CONFLICT: 'CONFLICT',\n"
        "  INTERNAL_ERROR: 'INTERNAL_ERROR',\n"
        "  PROJECT_NOT_FOUND: 'PROJECT_NOT_FOUND',\n"
        "  PROJECT_FORBIDDEN: 'PROJECT_FORBIDDEN',\n"
        "  TASK_NOT_FOUND: 'TASK_NOT_FOUND',\n"
        "  TASK_INVALID_TRANSITION: 'TASK_INVALID_TRANSITION',\n"
        "  TASK_TRANSITION_FORBIDDEN: 'TASK_TRANSITION_FORBIDDEN',\n"
        "  COMMENT_CONTENT_REQUIRED: 'COMMENT_CONTENT_REQUIRED',\n"
        "  USER_NOT_FOUND: 'USER_NOT_FOUND',\n"
        "  EMAIL_IN_USE: 'EMAIL_IN_USE',\n"
        "  INVALID_CREDENTIALS: 'INVALID_CREDENTIALS',\n"
        "  UNAUTHENTICATED: 'UNAUTHENTICATED',\n"
        "  CANNOT_DELETE_SELF: 'CANNOT_DELETE_SELF',\n"
        "} as const;\n"
    )


def _packages_shared_pagination_template() -> str:
    """packages/shared/src/pagination.ts — VERBATIM from REQUIREMENTS lines 366-368."""
    return (
        "// src/pagination.ts\n"
        "export interface PaginationMeta { total: number; page: number; limit: number; }\n"
        "export class PaginatedResult<T> { constructor(public items: T[], public meta: PaginationMeta) {} }\n"
    )


def _packages_shared_index_template() -> str:
    """packages/shared/src/index.ts — barrel re-export."""
    return (
        "export * from './enums';\n"
        "export * from './error-codes';\n"
        "export * from './pagination';\n"
    )
