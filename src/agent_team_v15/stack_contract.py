"""Stack contract derivation and deterministic validation helpers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


_SKIP_DIRS = {
    ".agent-team",
    ".git",
    ".next",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}

_SOURCE_EXTENSIONS = {
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".mjs",
    ".prisma",
    ".py",
    ".sql",
    ".ts",
    ".tsx",
}

_EXEMPT_SHARED_PREFIXES = (
    ".agent-team/",
    "contracts/",
    "docs/",
    "packages/",
    "scripts/",
    "tests/",
)

_FRAMEWORK_PATTERNS = {
    "backend": [
        (re.compile(r"\bnest(?:\.|)js\b", re.IGNORECASE), "nestjs"),
        (re.compile(r"\bexpress(?:\.|)js\b|\bexpress\b", re.IGNORECASE), "express"),
        (re.compile(r"\bfastify\b", re.IGNORECASE), "fastify"),
        (re.compile(r"\bfastapi\b", re.IGNORECASE), "fastapi"),
        (re.compile(r"\bdjango\b", re.IGNORECASE), "django"),
        (re.compile(r"\bspring(?:\s+boot)?\b", re.IGNORECASE), "spring"),
        (re.compile(r"\basp\.?net\b|\baspnet\b", re.IGNORECASE), "aspnet"),
    ],
    "frontend": [
        (re.compile(r"\bnext(?:\.|)js\b", re.IGNORECASE), "nextjs"),
        (re.compile(r"\bremix\b", re.IGNORECASE), "remix"),
        (re.compile(r"\bvite\b.*\breact\b|\breact\b.*\bvite\b", re.IGNORECASE), "vite-react"),
        (re.compile(r"\bsveltekit\b", re.IGNORECASE), "sveltekit"),
        (re.compile(r"\bnuxt\b", re.IGNORECASE), "nuxt"),
    ],
}

_ORM_PATTERNS = [
    (re.compile(r"\bprisma\b", re.IGNORECASE), "prisma"),
    (re.compile(r"\btypeorm\b", re.IGNORECASE), "typeorm"),
    (re.compile(r"\bdrizzle(?:-orm)?\b", re.IGNORECASE), "drizzle"),
    (re.compile(r"\bkysely\b", re.IGNORECASE), "kysely"),
    (re.compile(r"\bsqlalchemy\b", re.IGNORECASE), "sqlalchemy"),
    (re.compile(r"\bsqlmodel\b", re.IGNORECASE), "sqlmodel"),
    (re.compile(r"\btortoise\b", re.IGNORECASE), "tortoise"),
    (re.compile(r"\bdjango\s+orm\b|\bdjango-orm\b", re.IGNORECASE), "django-orm"),
    (re.compile(r"\bjpa\b|\bhibernate\b", re.IGNORECASE), "jpa"),
    (re.compile(r"\bef\s*core\b|\befcore\b|\bentity framework core\b", re.IGNORECASE), "ef-core"),
]

_DATABASE_PATTERNS = [
    (re.compile(r"\bpostgres(?:ql)?\b", re.IGNORECASE), "postgresql"),
    (re.compile(r"\bmysql\b", re.IGNORECASE), "mysql"),
    (re.compile(r"\bsqlite\b", re.IGNORECASE), "sqlite"),
    (re.compile(r"\bmongo(?:db)?\b", re.IGNORECASE), "mongodb"),
]


@dataclass
class StackContract:
    """Canonical stack choices for one run or milestone."""

    backend_framework: str = ""
    frontend_framework: str = ""
    orm: str = ""
    database: str = ""
    monorepo_layout: str = ""
    backend_path_prefix: str = ""
    frontend_path_prefix: str = ""
    forbidden_file_patterns: list[str] = field(default_factory=list)
    forbidden_imports: list[str] = field(default_factory=list)
    forbidden_decorators: list[str] = field(default_factory=list)
    required_file_patterns: list[str] = field(default_factory=list)
    required_imports: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    confidence: str = "high"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "StackContract":
        payload = data if isinstance(data, dict) else {}
        return cls(
            backend_framework=str(payload.get("backend_framework", "") or ""),
            frontend_framework=str(payload.get("frontend_framework", "") or ""),
            orm=str(payload.get("orm", "") or ""),
            database=str(payload.get("database", "") or ""),
            monorepo_layout=str(payload.get("monorepo_layout", "") or ""),
            backend_path_prefix=str(payload.get("backend_path_prefix", "") or ""),
            frontend_path_prefix=str(payload.get("frontend_path_prefix", "") or ""),
            forbidden_file_patterns=[str(item) for item in payload.get("forbidden_file_patterns", []) or []],
            forbidden_imports=[str(item) for item in payload.get("forbidden_imports", []) or []],
            forbidden_decorators=[str(item) for item in payload.get("forbidden_decorators", []) or []],
            required_file_patterns=[str(item) for item in payload.get("required_file_patterns", []) or []],
            required_imports=[str(item) for item in payload.get("required_imports", []) or []],
            derived_from=[str(item) for item in payload.get("derived_from", []) or []],
            confidence=str(payload.get("confidence", "high") or "high"),
        )


@dataclass
class StackViolation:
    """Deterministic contract violation."""

    code: str
    severity: str
    file_path: str
    line: int
    message: str
    expected: str = ""
    actual: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _base_stack_contracts() -> dict[tuple[str, str], StackContract]:
    return {
        ("nestjs", "prisma"): StackContract(
            backend_framework="nestjs",
            orm="prisma",
            forbidden_file_patterns=[
                r".*\.entity\.ts$",
                r".*data-source\.ts$",
                r".*typeorm\.config\.ts$",
            ],
            forbidden_imports=["@nestjs/typeorm", "typeorm"],
            forbidden_decorators=["@Entity", "@PrimaryGeneratedColumn", "@Column"],
            required_file_patterns=[r"prisma/schema\.prisma$"],
            required_imports=["@prisma/client"],
            derived_from=["builtin:nestjs+prisma"],
        ),
        ("nestjs", "typeorm"): StackContract(
            backend_framework="nestjs",
            orm="typeorm",
            forbidden_file_patterns=[r"prisma/schema\.prisma$"],
            forbidden_imports=["@prisma/client", "prisma"],
            required_file_patterns=[r".*\.entity\.ts$"],
            required_imports=["@nestjs/typeorm", "typeorm"],
            derived_from=["builtin:nestjs+typeorm"],
        ),
        ("nestjs", "drizzle"): StackContract(
            backend_framework="nestjs",
            orm="drizzle",
            forbidden_file_patterns=[r"prisma/schema\.prisma$", r".*\.entity\.ts$", r".*typeorm\.config\.ts$"],
            forbidden_imports=["@prisma/client", "prisma", "@nestjs/typeorm", "typeorm"],
            forbidden_decorators=["@Entity", "@PrimaryGeneratedColumn", "@Column"],
            required_file_patterns=[r".*drizzle/.*", r".*src/db/schema\.(ts|js)$"],
            required_imports=["drizzle-orm"],
            derived_from=["builtin:nestjs+drizzle"],
        ),
        ("express", "prisma"): StackContract(
            backend_framework="express",
            orm="prisma",
            forbidden_file_patterns=[r".*\.entity\.ts$", r".*typeorm\.config\.ts$"],
            forbidden_imports=["typeorm", "sequelize", "mongoose"],
            forbidden_decorators=["@Entity", "@PrimaryGeneratedColumn", "@Column"],
            required_file_patterns=[r"prisma/schema\.prisma$"],
            required_imports=["@prisma/client"],
            derived_from=["builtin:express+prisma"],
        ),
        ("fastify", "prisma"): StackContract(
            backend_framework="fastify",
            orm="prisma",
            forbidden_file_patterns=[r".*\.entity\.ts$", r".*typeorm\.config\.ts$"],
            forbidden_imports=["typeorm", "sequelize", "mongoose"],
            forbidden_decorators=["@Entity", "@PrimaryGeneratedColumn", "@Column"],
            required_file_patterns=[r"prisma/schema\.prisma$"],
            required_imports=["@prisma/client"],
            derived_from=["builtin:fastify+prisma"],
        ),
        ("django", "django-orm"): StackContract(
            backend_framework="django",
            orm="django-orm",
            forbidden_file_patterns=[r".*schema\.prisma$", r".*alembic/.*"],
            forbidden_imports=["sqlalchemy", "prisma"],
            required_file_patterns=[r"manage\.py$", r".*models\.py$"],
            required_imports=["django.db"],
            derived_from=["builtin:django+django-orm"],
        ),
        ("spring", "jpa"): StackContract(
            backend_framework="spring",
            orm="jpa",
            forbidden_file_patterns=[r".*schema\.prisma$"],
            forbidden_imports=["org.jooq", "@prisma/client"],
            required_file_patterns=[r".*\.java$"],
            required_imports=["jakarta.persistence", "org.springframework.data.jpa"],
            derived_from=["builtin:spring+jpa"],
        ),
        ("aspnet", "ef-core"): StackContract(
            backend_framework="aspnet",
            orm="ef-core",
            forbidden_file_patterns=[r".*schema\.prisma$"],
            forbidden_imports=["Dapper", "@prisma/client"],
            required_file_patterns=[r".*DbContext\.cs$"],
            required_imports=["Microsoft.EntityFrameworkCore"],
            derived_from=["builtin:aspnet+ef-core"],
        ),
    }


BUILTIN_STACK_CONTRACTS: dict[tuple[str, str], StackContract] = _base_stack_contracts()


def builtin_stack_contracts() -> dict[tuple[str, str], StackContract]:
    """Return a fresh copy of the builtin contract registry."""

    return {
        key: StackContract.from_dict(contract.to_dict())
        for key, contract in BUILTIN_STACK_CONTRACTS.items()
    }


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_framework_name(value: str) -> str:
    normalized = _normalize_name(value)
    framework_aliases = {
        "nestjs": "nestjs",
        "express": "express",
        "fastify": "fastify",
        "fastapi": "fastapi",
        "django": "django",
        "spring": "spring",
        "springboot": "spring",
        "aspnet": "aspnet",
        "aspnetcore": "aspnet",
        "nextjs": "nextjs",
        "next": "nextjs",
        "remix": "remix",
        "vitereact": "vite-react",
        "sveltekit": "sveltekit",
        "nuxt": "nuxt",
    }
    return framework_aliases.get(normalized, "")


def _normalize_orm_name(value: str) -> str:
    normalized = _normalize_name(value)
    orm_aliases = {
        "prisma": "prisma",
        "typeorm": "typeorm",
        "drizzle": "drizzle",
        "drizzleorm": "drizzle",
        "kysely": "kysely",
        "sqlalchemy": "sqlalchemy",
        "sqlmodel": "sqlmodel",
        "tortoise": "tortoise",
        "djangoorm": "django-orm",
        "djangorm": "django-orm",
        "jpa": "jpa",
        "hibernate": "jpa",
        "efcore": "ef-core",
        "entityframeworkcore": "ef-core",
    }
    return orm_aliases.get(normalized, "")


def _normalize_database_name(value: str) -> str:
    normalized = _normalize_name(value)
    database_aliases = {
        "postgres": "postgresql",
        "postgresql": "postgresql",
        "mysql": "mysql",
        "sqlite": "sqlite",
        "mongodb": "mongodb",
        "mongo": "mongodb",
    }
    return database_aliases.get(normalized, "")


def _text_contains_pattern(text: str, pattern: re.Pattern[str]) -> bool:
    return bool(pattern.search(text or ""))


def _detect_frameworks_from_text(text: str) -> tuple[str, str]:
    backend = ""
    frontend = ""
    for pattern, value in _FRAMEWORK_PATTERNS["backend"]:
        if _text_contains_pattern(text, pattern):
            backend = value
            break
    for pattern, value in _FRAMEWORK_PATTERNS["frontend"]:
        if _text_contains_pattern(text, pattern):
            frontend = value
            break
    return backend, frontend


def _detect_orm_from_text(text: str) -> str:
    for pattern, value in _ORM_PATTERNS:
        if _text_contains_pattern(text, pattern):
            return value
    return ""


def _detect_database_from_text(text: str) -> str:
    for pattern, value in _DATABASE_PATTERNS:
        if _text_contains_pattern(text, pattern):
            return value
    return ""


def _detect_layout_from_text(text: str) -> tuple[str, str, str, bool]:
    lower = str(text or "").lower()
    if "apps/api" in lower or "apps/web" in lower:
        return "apps", "apps/api/", "apps/web/", True
    if "packages/" in lower and "apps/" in lower:
        return "packages-and-apps", "apps/api/", "apps/web/", True
    if "backend/" in lower or "frontend/" in lower:
        return "backend-frontend", "backend/", "frontend/", True
    if "server/" in lower or "client/" in lower:
        return "client-server", "server/", "client/", True
    if "monorepo" in lower or "workspace" in lower or "merge-surfaces" in lower:
        return "apps", "apps/api/", "apps/web/", False
    return "single", "", "", False


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _synthesized_contract(backend: str, orm: str) -> StackContract:
    contract = StackContract(backend_framework=backend, orm=orm)

    if orm == "prisma":
        contract.forbidden_file_patterns = [r".*\.entity\.ts$", r".*data-source\.ts$", r".*typeorm\.config\.ts$"]
        contract.forbidden_imports = ["@nestjs/typeorm", "typeorm", "sequelize", "mongoose"]
        contract.forbidden_decorators = ["@Entity", "@PrimaryGeneratedColumn", "@Column"]
        contract.required_file_patterns = [r"prisma/schema\.prisma$"]
        contract.required_imports = ["@prisma/client"]
    elif orm == "typeorm":
        contract.forbidden_file_patterns = [r"prisma/schema\.prisma$"]
        contract.forbidden_imports = ["@prisma/client", "prisma"]
        contract.required_file_patterns = [r".*\.entity\.ts$"]
        contract.required_imports = ["typeorm"]
        if backend == "nestjs":
            contract.required_imports.insert(0, "@nestjs/typeorm")
    elif orm == "drizzle":
        contract.forbidden_file_patterns = [r"prisma/schema\.prisma$", r".*\.entity\.ts$", r".*typeorm\.config\.ts$"]
        contract.forbidden_imports = ["@prisma/client", "prisma", "@nestjs/typeorm", "typeorm"]
        contract.forbidden_decorators = ["@Entity", "@PrimaryGeneratedColumn", "@Column"]
        contract.required_file_patterns = [r".*drizzle/.*", r".*schema\.(ts|js)$"]
        contract.required_imports = ["drizzle-orm"]
    elif orm == "sqlalchemy":
        contract.forbidden_file_patterns = [r".*schema\.prisma$"]
        contract.forbidden_imports = ["django.db", "@prisma/client"]
        contract.required_file_patterns = [r".*models?\.py$", r".*alembic/.*"]
        contract.required_imports = ["sqlalchemy"]
    elif orm == "django-orm":
        contract.forbidden_file_patterns = [r".*schema\.prisma$", r".*alembic/.*"]
        contract.forbidden_imports = ["sqlalchemy", "@prisma/client"]
        contract.required_file_patterns = [r"manage\.py$", r".*models\.py$"]
        contract.required_imports = ["django.db"]
    elif orm == "jpa":
        contract.forbidden_file_patterns = [r".*schema\.prisma$"]
        contract.forbidden_imports = ["org.jooq", "@prisma/client"]
        contract.required_file_patterns = [r".*\.java$"]
        contract.required_imports = ["jakarta.persistence", "org.springframework.data.jpa"]
    elif orm == "ef-core":
        contract.forbidden_file_patterns = [r".*schema\.prisma$"]
        contract.forbidden_imports = ["Dapper", "@prisma/client"]
        contract.required_file_patterns = [r".*DbContext\.cs$"]
        contract.required_imports = ["Microsoft.EntityFrameworkCore"]

    contract.derived_from = [f"synthesized:{backend}+{orm}".strip("+")]
    return contract


def _extract_from_tech_stack(tech_stack: list[Any]) -> tuple[str, str, str, str]:
    backend = ""
    frontend = ""
    orm = ""
    database = ""
    for entry in tech_stack or []:
        name = str(getattr(entry, "name", "") or (entry.get("name", "") if isinstance(entry, dict) else "") or "")
        category = str(getattr(entry, "category", "") or (entry.get("category", "") if isinstance(entry, dict) else "") or "")
        normalized_name = _normalize_framework_name(name)
        if category == "backend_framework" and not backend:
            backend = normalized_name
        elif category == "frontend_framework" and not frontend:
            frontend = normalized_name
        elif category == "orm" and not orm:
            orm = _normalize_orm_name(name)
        elif category == "database" and not database:
            database = _normalize_database_name(name)
    return backend, frontend, orm, database


def _collect_requirements_texts(project_root: Path) -> str:
    milestone_root = project_root / ".agent-team" / "milestones"
    if not milestone_root.is_dir():
        return ""
    chunks: list[str] = []
    for path in sorted(milestone_root.glob("*/REQUIREMENTS.md")):
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n\n".join(chunks)


def derive_stack_contract(
    prd_text: str,
    master_plan_text: str,
    tech_stack: list[Any],
    milestone_requirements: str,
) -> StackContract:
    """Resolve a stack contract from PRD, plan, research, and requirements."""

    prd_backend, prd_frontend = _detect_frameworks_from_text(prd_text)
    plan_backend, plan_frontend = _detect_frameworks_from_text(master_plan_text)
    req_backend, req_frontend = _detect_frameworks_from_text(milestone_requirements)
    tech_backend, tech_frontend, tech_orm, tech_database = _extract_from_tech_stack(tech_stack)

    backend = prd_backend or plan_backend or req_backend or tech_backend
    frontend = prd_frontend or plan_frontend or req_frontend or tech_frontend

    prd_orm = _detect_orm_from_text(prd_text)
    plan_orm = _detect_orm_from_text(master_plan_text)
    req_orm = _detect_orm_from_text(milestone_requirements)
    orm = prd_orm or plan_orm or req_orm or tech_orm

    prd_database = _detect_database_from_text(prd_text)
    plan_database = _detect_database_from_text(master_plan_text)
    req_database = _detect_database_from_text(milestone_requirements)
    database = prd_database or plan_database or req_database or tech_database

    layout, backend_prefix, frontend_prefix, _ = _detect_layout_from_text(
        "\n".join([master_plan_text or "", milestone_requirements or "", prd_text or ""])
    )
    _, _, _, prd_layout_explicit = _detect_layout_from_text(prd_text)
    _, _, _, plan_layout_explicit = _detect_layout_from_text(master_plan_text)
    _, _, _, req_layout_explicit = _detect_layout_from_text(milestone_requirements)
    layout_explicit = prd_layout_explicit or plan_layout_explicit or req_layout_explicit

    explicit_framework = bool(prd_backend or plan_backend or req_backend or prd_frontend or plan_frontend or req_frontend)
    explicit_orm = bool(prd_orm or plan_orm or req_orm)
    explicit_count = int(explicit_framework) + int(explicit_orm) + int(layout_explicit)

    confidence = "low"
    if explicit_framework and explicit_orm:
        confidence = "explicit"
    elif explicit_count >= 2:
        confidence = "high"
    elif explicit_count == 1:
        confidence = "medium"
    elif backend or frontend or orm or database:
        confidence = "low"

    registry = builtin_stack_contracts()
    base_contract = registry.get((backend, orm))
    if base_contract is None:
        base_contract = _synthesized_contract(backend, orm)
    contract = StackContract.from_dict(base_contract.to_dict())
    contract.backend_framework = backend
    contract.frontend_framework = frontend
    contract.orm = orm
    contract.database = database or contract.database
    contract.monorepo_layout = layout
    contract.backend_path_prefix = backend_prefix
    contract.frontend_path_prefix = frontend_prefix
    contract.derived_from = []
    if prd_backend or prd_frontend or prd_orm or prd_database:
        contract.derived_from.append("prd_text")
    if plan_backend or plan_frontend or plan_orm or plan_database or layout_explicit:
        contract.derived_from.append("master_plan")
    if req_backend or req_frontend or req_orm or req_database:
        contract.derived_from.append("milestone_requirements")
    if tech_backend or tech_frontend or tech_orm or tech_database:
        contract.derived_from.append("tech_research")
    if (backend, orm) in registry:
        contract.derived_from.append(f"builtin:{backend}+{orm}")
    if not contract.derived_from:
        contract.derived_from.append("default")
    contract.derived_from = _dedupe_strings(contract.derived_from)
    contract.confidence = confidence
    return contract


def write_stack_contract(project_root: Path | str, contract: StackContract) -> Path:
    """Persist the resolved contract under .agent-team/STACK_CONTRACT.json."""

    root = Path(project_root)
    agent_dir = root / ".agent-team"
    agent_dir.mkdir(parents=True, exist_ok=True)
    path = agent_dir / "STACK_CONTRACT.json"
    path.write_text(json.dumps(contract.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_stack_contract(project_root: Path | str) -> StackContract | None:
    """Load the persisted contract from STACK_CONTRACT.json or STATE.json."""

    root = Path(project_root)
    contract_path = root / ".agent-team" / "STACK_CONTRACT.json"
    if contract_path.is_file():
        try:
            return StackContract.from_dict(json.loads(contract_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return None

    state_path = root / ".agent-team" / "STATE.json"
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return None
        return StackContract.from_dict(state.get("stack_contract", {}))
    return None


def format_stack_contract_for_prompt(contract: StackContract) -> str:
    """Render the non-negotiable contract block for Wave A prompts."""

    lines = [
        "=== STACK CONTRACT (NON-NEGOTIABLE) ===",
        "",
        f"Backend framework:  {contract.backend_framework or '(unspecified)'}",
        f"Frontend framework: {contract.frontend_framework or '(unspecified)'}",
        f"ORM:                {contract.orm or '(unspecified)'}",
        f"Database:           {contract.database or '(unspecified)'}",
        f"Monorepo layout:    {contract.monorepo_layout or '(unspecified)'}",
        f"Backend path:       {contract.backend_path_prefix or '(root)'}",
        f"Frontend path:      {contract.frontend_path_prefix or '(root)'}",
        "",
        "You MUST NOT do any of these:",
        f"- Create files matching: {contract.forbidden_file_patterns or ['(none)']}",
        f"- Import from: {contract.forbidden_imports or ['(none)']}",
        f"- Use decorators: {contract.forbidden_decorators or ['(none)']}",
        "",
        "You MUST do all of these:",
        f"- Create at least one file matching: {contract.required_file_patterns or ['(none)']}",
        f"- Use at least one import from: {contract.required_imports or ['(none)']}",
        "",
        "If the milestone requirements or other context contradict this contract,",
        "write `WAVE_A_CONTRACT_CONFLICT.md` explaining the contradiction and stop.",
        "A deterministic validator will reject forbidden stack drift and retry once.",
    ]
    return "\n".join(lines)


def format_stack_violations(violations: list[StackViolation]) -> str:
    """Render violations for prompt injection or reports."""

    if not violations:
        return "- none"
    return "\n".join(
        (
            f"- [{violation.code}] {violation.file_path}:{violation.line} "
            f"{violation.message} (expected: {violation.expected or 'n/a'}; actual: {violation.actual or 'n/a'})"
        )
        for violation in violations
    )


def _iter_project_files(project_root: Path) -> list[Path]:
    # Safe walker — prunes node_modules / .pnpm at descent so Windows
    # MAX_PATH inside pnpm's symlink tree can't raise WinError 3
    # (project_walker.py post smoke #9/#10).
    from .project_walker import DEFAULT_SKIP_DIRS, iter_project_files as _walk

    merged_skips = set(DEFAULT_SKIP_DIRS) | set(_SKIP_DIRS)
    return _walk(project_root, skip_dirs=merged_skips)


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _is_layout_exempt(rel_path: str) -> bool:
    if rel_path in {
        "package.json",
        "pnpm-workspace.yaml",
        "yarn.lock",
        "package-lock.json",
        "tsconfig.json",
        "README.md",
        "WAVE_A_CONTRACT_CONFLICT.md",
    }:
        return True
    return rel_path.startswith(_EXEMPT_SHARED_PREFIXES)


def _is_backend_or_frontend_candidate(rel_path: str) -> bool:
    suffix = Path(rel_path).suffix.lower()
    return suffix in _SOURCE_EXTENSIONS or rel_path.endswith("schema.prisma")


def validate_wave_against_stack_contract(
    wave_output: Any,
    contract: StackContract,
    project_root: Path,
) -> list[StackViolation]:
    """Run deterministic stack validation against wave outputs and current tree."""

    violations: list[StackViolation] = []
    changed_files = {
        str(path).replace("\\", "/")
        for path in list(getattr(wave_output, "files_created", []) or []) + list(getattr(wave_output, "files_modified", []) or [])
        if str(path).strip()
    }
    all_files = _iter_project_files(project_root)
    rel_to_path = {}
    for path in all_files:
        try:
            rel = path.relative_to(project_root).as_posix()
        except ValueError:
            rel = str(path).replace("\\", "/")
        rel_to_path[rel] = path
    changed_paths = [rel_to_path[rel_path] for rel_path in sorted(changed_files) if rel_path in rel_to_path]

    forbidden_file_regexes = [re.compile(pattern) for pattern in contract.forbidden_file_patterns]
    required_file_regexes = [re.compile(pattern) for pattern in contract.required_file_patterns]

    for rel_path in sorted(changed_files):
        path = rel_to_path.get(rel_path)
        if not path:
            continue
        for pattern in forbidden_file_regexes:
            if pattern.search(rel_path):
                violations.append(
                    StackViolation(
                        code="STACK-FILE-001",
                        severity="CRITICAL",
                        file_path=rel_path,
                        line=1,
                        message="Created or modified a file that is forbidden by the resolved stack contract.",
                        expected=f"not matching /{pattern.pattern}/",
                        actual=rel_path,
                    )
                )

        content = _read_file(path)
        for forbidden_import in contract.forbidden_imports:
            import_pattern = re.compile(re.escape(forbidden_import))
            for match in import_pattern.finditer(content):
                violations.append(
                    StackViolation(
                        code="STACK-IMPORT-001",
                        severity="CRITICAL",
                        file_path=rel_path,
                        line=content[:match.start()].count("\n") + 1,
                        message="Imported a module that is forbidden by the resolved stack contract.",
                        expected="avoid forbidden imports",
                        actual=forbidden_import,
                    )
                )
        for decorator in contract.forbidden_decorators:
            decorator_pattern = re.compile(re.escape(decorator))
            for match in decorator_pattern.finditer(content):
                violations.append(
                    StackViolation(
                        code="STACK-DECORATOR-001",
                        severity="CRITICAL",
                        file_path=rel_path,
                        line=content[:match.start()].count("\n") + 1,
                        message="Used a decorator that is forbidden by the resolved stack contract.",
                        expected="avoid forbidden decorators",
                        actual=decorator,
                    )
                )
        if contract.monorepo_layout and contract.monorepo_layout != "single":
            if (
                _is_backend_or_frontend_candidate(rel_path)
                and not rel_path.startswith(contract.backend_path_prefix)
                and not rel_path.startswith(contract.frontend_path_prefix)
                and not _is_layout_exempt(rel_path)
            ):
                violations.append(
                    StackViolation(
                        code="STACK-PATH-001",
                        severity="CRITICAL",
                        file_path=rel_path,
                        line=1,
                        message="Created or modified a code file outside the declared stack layout paths.",
                        expected=f"{contract.backend_path_prefix}* or {contract.frontend_path_prefix}*",
                        actual=rel_path,
                    )
                )

    for pattern in required_file_regexes:
        if not any(pattern.search(rel_path) for rel_path in changed_files):
            violations.append(
                StackViolation(
                    code="STACK-FILE-002",
                    severity="HIGH",
                    file_path="",
                    line=0,
                    message="No file in the wave output matches a required stack-contract file pattern.",
                    expected=pattern.pattern,
                    actual="missing",
                )
            )

    for required_import in contract.required_imports:
        import_pattern = re.compile(re.escape(required_import))
        if not any(import_pattern.search(_read_file(path)) for path in changed_paths):
            violations.append(
                StackViolation(
                    code="STACK-IMPORT-002",
                    severity="HIGH",
                    file_path="",
                    line=0,
                    message="No file in the wave output contains a required stack-contract import.",
                    expected=required_import,
                    actual="missing",
                )
            )

    deduped: dict[tuple[str, str, int, str], StackViolation] = {}
    for violation in violations:
        key = (violation.code, violation.file_path, violation.line, violation.actual)
        deduped.setdefault(key, violation)
    return list(deduped.values())


def collect_stack_contract_inputs(
    *,
    project_root: Path,
    prd_text: str,
    master_plan_text: str,
    tech_stack: list[Any],
) -> StackContract:
    """Derive and persist a contract from the available run inputs."""

    milestone_requirements = _collect_requirements_texts(project_root)
    return derive_stack_contract(prd_text, master_plan_text, tech_stack, milestone_requirements)


__all__ = [
    "BUILTIN_STACK_CONTRACTS",
    "StackContract",
    "StackViolation",
    "builtin_stack_contracts",
    "collect_stack_contract_inputs",
    "derive_stack_contract",
    "format_stack_contract_for_prompt",
    "format_stack_violations",
    "load_stack_contract",
    "validate_wave_against_stack_contract",
    "write_stack_contract",
]
