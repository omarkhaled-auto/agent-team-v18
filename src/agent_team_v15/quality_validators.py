"""Quality validators for cross-layer consistency checking.

Scans project source files for cross-cutting quality issues that span
multiple layers (schema, backend, frontend, config). Each validator
targets a specific category of integration bugs commonly produced by
AI code generators.

Validator categories:
    - EnumRegistry:     ENUM-001..003   (enum/role/status mismatches)
    - AuthFlow:         AUTH-001..004   (auth endpoint/MFA/token/security)
    - ResponseShape:    SHAPE-001..003  (field naming, array wrapping, field drift)
    - SoftDelete:       SOFTDEL-001..002, QUERY-001 (soft-delete, field refs, casts)
    - Infrastructure:   INFRA-001..008  (ports, configs, tsconfig, Docker, Nest wildcard routes, Express 5 req.query writes)

All validators are regex-based, require no external dependencies (stdlib only),
and reuse ``Violation`` / ``ScanScope`` from ``quality_checks.py`` for seamless
pipeline integration.

Typical usage::

    from pathlib import Path
    from agent_team_v15.quality_validators import run_quality_validators

    violations = run_quality_validators(Path("/path/to/project"))
    for v in violations:
        print(f"[{v.check}] {v.message} at {v.file_path}:{v.line}")
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from agent_team_v15.quality_checks import Violation, ScanScope

# Try to import schema metadata; fall back to internal parser if unavailable.
try:
    from agent_team_v15.schema_validator import (
        get_schema_models,
        PrismaModel,
        PrismaEnum,
        parse_prisma_schema,
    )
    _HAS_SCHEMA_VALIDATOR = True
except ImportError:
    _HAS_SCHEMA_VALIDATOR = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_VIOLATIONS = 500
_MAX_FILE_SIZE = 100_000  # 100 KB

EXCLUDED_DIRS: frozenset[str] = frozenset({
    ".venv", "venv", "node_modules", "__pycache__", ".git",
    "dist", "build", "vendor", ".tox", ".mypy_cache", ".pytest_cache",
    "site-packages", ".egg-info", ".next", "env", ".angular",
    "coverage", ".nuxt", ".output", ".svelte-kit",
})

_SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

# File extensions
_EXT_BACKEND: frozenset[str] = frozenset({".ts", ".js", ".py", ".cs"})
_EXT_FRONTEND: frozenset[str] = frozenset({".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte"})
_EXT_CONFIG: frozenset[str] = frozenset({".json", ".env", ".yaml", ".yml", ".toml", ".js", ".ts", ".mjs", ".cjs"})
_EXT_SCHEMA: frozenset[str] = frozenset({".prisma"})
_ALL_EXTENSIONS: frozenset[str] = _EXT_BACKEND | _EXT_FRONTEND | _EXT_CONFIG | _EXT_SCHEMA


# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# --- Prisma schema patterns ---
_RE_PRISMA_MODEL = re.compile(r"^model\s+(\w+)\s*\{", re.MULTILINE)
_RE_PRISMA_DELETED_AT = re.compile(r"^\s+deleted_at\s", re.MULTILINE)
_RE_PRISMA_ENUM = re.compile(r"^enum\s+(\w+)\s*\{([^}]+)\}", re.MULTILINE)
_RE_PRISMA_DEFAULT = re.compile(r'@default\(\s*"([^"]+)"\s*\)')
_RE_PRISMA_COMMENT_ENUM = re.compile(r'//\s*(?:values?|options?):\s*(.+)', re.IGNORECASE)
_RE_PRISMA_MODEL_QUERY = re.compile(
    r"(?:this\.)?(?:prisma|db|client)\s*\.\s*(\w+)\s*\.\s*(findMany|findFirst|findUnique|findFirstOrThrow|findUniqueOrThrow)\s*\("
)
_RE_SOFT_DELETE_FILTER = re.compile(r"deleted_at\s*:\s*null")
_RE_PRISMA_ANY_CAST = re.compile(r"\(\s*this\.prisma\s+as\s+any\s*\)")
_RE_POST_QUERY_FILTER = re.compile(r"\.(?:filter|map)\s*\(")

# --- Enum Registry patterns ---
_RE_ROLES_DECORATOR = re.compile(r"@Roles\s*\(\s*([^)]+)\)")
_RE_ROLE_STRING = re.compile(r"['\"](\w+)['\"]")
_RE_SEED_ROLE = re.compile(r"(?:role|code|name)\s*:\s*['\"](\w+)['\"]", re.IGNORECASE)
_RE_FRONTEND_STATUS_ARRAY = re.compile(
    r"(?:status|statuses|statusOptions|STATUS|STATUSES)\s*(?::\s*\w+(?:\[\])?\s*)?=\s*\[([^\]]+)\]",
)
_RE_STATUS_STRING = re.compile(r"['\"](\w+)['\"]")

# --- Response Shape patterns ---
# SHAPE-001: camelCase || snake_case fallback
_RE_CASE_FALLBACK = re.compile(
    r"(\w+[a-z])([A-Z]\w*)\s*\|\|\s*(\w+_\w+)|(\w+_\w+)\s*\|\|\s*(\w+[a-z])([A-Z]\w*)"
)
# SHAPE-002: Defensive Array.isArray check
_RE_DEFENSIVE_ARRAY = re.compile(r"Array\.isArray\s*\(\s*\w+\s*\)\s*\?\s*\w+\s*:\s*\w+\.data")
_RE_DEFENSIVE_OR = re.compile(r"(?:\.data\s*\|\|\s*\[\]|(?:res|response|result)\.data\s*\?\?)")
# SHAPE-003: Bare array return from list endpoint
_RE_LIST_ENDPOINT = re.compile(
    r"(?:@Get|@HttpGet|@api_view.*GET|@app\.(?:get|route)|router\.get)\s*\(",
    re.IGNORECASE,
)
_RE_FINDMANY_CALL = re.compile(r"\.findMany\s*\(")
_RE_BARE_ARRAY_RETURN = re.compile(
    r"return\s+(?:results?|items?|data|records?|list|rows?|entries|entities)\s*;",
    re.IGNORECASE,
)
_RE_WRAPPED_RESPONSE = re.compile(r"(?:data\s*:|meta\s*:|\bpaginated\b|\bPaginat)", re.IGNORECASE)

# SHAPE-004: Silent catch detector
_RE_CATCH_BLOCK = re.compile(r"catch\s*\([^)]*\)\s*\{", re.MULTILINE)
_RE_ERROR_STATE_SETTER = re.compile(
    r"(?:setError|setState|toast|notification|showError|showToast|addToast|dispatch|throw\s|alert\s*\(|notify)",
    re.IGNORECASE,
)

# --- Auth Flow patterns ---
_RE_FRONTEND_AUTH_CALL = re.compile(
    r"(?:api|http|axios|fetch)\s*\.\s*(?:post|get|put|patch)\s*\(\s*['\"`]([^'\"`]*(?:auth|login|logout|register|refresh|verify|mfa|2fa|otp|forgot|reset)[^'\"`]*)['\"`]",
    re.IGNORECASE,
)
_RE_BACKEND_AUTH_ROUTE = re.compile(
    r"(?:@(?:Post|Get|Put|Patch|Delete|HttpPost|HttpGet)|@app\.(?:post|get|route)|router\.(?:post|get))\s*\(\s*['\"`]([^'\"`]*(?:auth|login|logout|register|refresh|verify|mfa|2fa|otp|forgot|reset)[^'\"`]*)['\"`]",
    re.IGNORECASE,
)
_RE_MFA_PATTERN = re.compile(r"(?:mfa|2fa|otp|two.?factor|totp|authenticator)", re.IGNORECASE)
_RE_REFRESH_TOKEN = re.compile(r"(?:refresh.?token|token.?refresh|refreshToken|refresh_token)", re.IGNORECASE)
_RE_CORS_LOCALHOST = re.compile(r"(?:origin|CORS|cors)\s*[:=].*(?:localhost|127\.0\.0\.1)", re.IGNORECASE)
_RE_CORS_ENV_VAR = re.compile(r"process\.env\.\w+|os\.environ|env\(")
_RE_LOCALSTORAGE_TOKEN = re.compile(
    r"localStorage\.(?:setItem|getItem)\s*\(\s*['\"](?:token|access_token|auth_token|jwt|id_token)['\"]",
    re.IGNORECASE,
)
_RE_FORBID_NON_WHITELISTED_FALSE = re.compile(r"forbidNonWhitelisted\s*:\s*false")

# --- Infrastructure patterns ---
_RE_CONFIG_PORT = re.compile(r"(?:port|PORT)\s*[:=]\s*(\d+)")
_RE_TSCONFIG_EXCLUDE = re.compile(r'"exclude"\s*:\s*\[([^\]]*)\]')
_RE_TEST_DIR_PATTERN = re.compile(r"(?:__tests__|e2e|playwright|cypress|test|spec)", re.IGNORECASE)
_RE_DOCKER_RESTART = re.compile(r"restart\s*:", re.IGNORECASE)
_RE_DOCKER_HEALTHCHECK = re.compile(r"healthcheck\s*:", re.IGNORECASE)
_RE_DOCKER_SERVICE = re.compile(r"^\s{2}(\w[\w-]*):\s*$", re.MULTILINE)
_RE_ROUTE_LITERAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"forRoutes\s*\(\s*['\"`]([^'\"`]*\*[^'\"`]*)['\"`]",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"@(?:Controller|Get|Post|Put|Patch|Delete|All|Options|Head)\s*"
        r"\(\s*['\"`]([^'\"`]*\*[^'\"`]*)['\"`]",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"(?:app|router)\s*\.\s*(?:all|use|get|post|put|patch|delete|options|head)\s*"
        r"\(\s*['\"`]([^'\"`]*\*[^'\"`]*)['\"`]",
        re.IGNORECASE | re.MULTILINE,
    ),
)
_RE_REQ_QUERY_ASSIGNMENT = re.compile(r"\b(?:req|request)\.query\s*=(?!=)")

# --- Path-based file classification ---
_RE_BACKEND_PATH = re.compile(
    r"(?:\.controller\.|\.service\.|\.guard\.|\.strategy\.|\.middleware\.|\.resolver\.|\.module\.|\.interceptor\.)",
    re.IGNORECASE,
)
_RE_FRONTEND_PATH = re.compile(
    r"(?:\.tsx$|\.jsx$|pages[/\\]|components[/\\]|app[/\\].*\.ts$|hooks[/\\]|contexts?[/\\]|lib[/\\])",
    re.IGNORECASE,
)
_RE_SERVICE_FILE = re.compile(r"(?:\.service\.|\.controller\.|\.resolver\.)", re.IGNORECASE)
_RE_CONTROLLER_FILE = re.compile(r"(?:\.controller\.|\.resolver\.)", re.IGNORECASE)
_RE_SEED_FILE = re.compile(r"(?:seed|seeds|seeder|fixtures)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# File iteration helpers
# ---------------------------------------------------------------------------

def _should_skip_dir(name: str) -> bool:
    return name in EXCLUDED_DIRS


def _iter_project_files(
    project_root: Path,
    extensions: frozenset[str] | None = None,
    path_filter: re.Pattern[str] | None = None,
) -> list[Path]:
    """Walk project tree and return matching files."""
    files: list[Path] = []
    exts = extensions or _ALL_EXTENSIONS
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        for filename in filenames:
            file_path = Path(dirpath) / filename
            if file_path.suffix not in exts:
                continue
            try:
                if file_path.stat().st_size > _MAX_FILE_SIZE:
                    continue
            except OSError:
                continue
            if path_filter and not path_filter.search(
                file_path.relative_to(project_root).as_posix()
            ):
                continue
            files.append(file_path)
    return files


def _scope_filter(files: list[Path], scope: ScanScope | None) -> list[Path]:
    """Filter file list by ScanScope if provided."""
    if scope and scope.changed_files:
        scope_set = {f.resolve() for f in scope.changed_files}
        return [f for f in files if f.resolve() in scope_set]
    return files


def _read_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _rel_path(file_path: Path, project_root: Path) -> str:
    try:
        return file_path.relative_to(project_root).as_posix()
    except ValueError:
        return file_path.as_posix()


def _is_backend_file(rel_path: str) -> bool:
    return bool(_RE_BACKEND_PATH.search(rel_path))


def _is_frontend_file(rel_path: str) -> bool:
    if _RE_BACKEND_PATH.search(rel_path):
        return False
    return bool(_RE_FRONTEND_PATH.search(rel_path))


# ---------------------------------------------------------------------------
# Schema helpers (fallback if schema_validator not available)
# ---------------------------------------------------------------------------

def _find_prisma_schema(project_root: Path) -> Path | None:
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        for filename in filenames:
            if filename == "schema.prisma":
                return Path(dirpath) / filename
    return None


def _get_soft_delete_models_fallback(project_root: Path) -> set[str]:
    """Fallback: extract soft-delete model names via regex."""
    schema_path = _find_prisma_schema(project_root)
    if not schema_path:
        return set()
    content = _read_file(schema_path)
    if not content:
        return set()
    models: set[str] = set()
    current_model: str | None = None
    for line in content.splitlines():
        m = _RE_PRISMA_MODEL.match(line)
        if m:
            current_model = m.group(1)
            continue
        if current_model and line.strip() == "}":
            current_model = None
            continue
        if current_model and _RE_PRISMA_DELETED_AT.match(line):
            models.add(current_model)
            models.add(current_model[0].lower() + current_model[1:])
            models.add(re.sub(r"(?<!^)(?=[A-Z])", "_", current_model).lower())
    return models


def _get_soft_delete_models(project_root: Path) -> set[str]:
    """Get soft-delete model names, using schema_validator if available."""
    if _HAS_SCHEMA_VALIDATOR:
        try:
            schema_models = get_schema_models(project_root)
            models: set[str] = set()
            for name, model in schema_models.items():
                if model.has_deleted_at:
                    models.add(name)
                    models.add(name[0].lower() + name[1:])
                    models.add(re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower())
            if models:
                return models
        except Exception:
            pass
    return _get_soft_delete_models_fallback(project_root)


def _get_schema_enums_fallback(project_root: Path) -> dict[str, set[str]]:
    """Fallback: extract enums from Prisma schema via regex."""
    schema_path = _find_prisma_schema(project_root)
    if not schema_path:
        return {}
    content = _read_file(schema_path)
    if not content:
        return {}
    enums: dict[str, set[str]] = {}
    for match in _RE_PRISMA_ENUM.finditer(content):
        name = match.group(1)
        body = match.group(2)
        values = set()
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("//"):
                value = stripped.split("//")[0].strip()
                if value:
                    values.add(value)
        if values:
            enums[name] = values
    return enums


def _get_schema_enums(project_root: Path) -> dict[str, set[str]]:
    """Get enum definitions, using schema_validator if available."""
    if _HAS_SCHEMA_VALIDATOR:
        try:
            schema_path = _find_prisma_schema(project_root)
            if schema_path:
                content = _read_file(schema_path)
                if content:
                    parsed = parse_prisma_schema(content)
                    return {
                        name: set(enum.values)
                        for name, enum in parsed.enums.items()
                    }
        except Exception:
            pass
    return _get_schema_enums_fallback(project_root)


def _get_model_fields(project_root: Path) -> dict[str, set[str]]:
    """Get field names per model, using schema_validator if available."""
    if _HAS_SCHEMA_VALIDATOR:
        try:
            schema_models = get_schema_models(project_root)
            return {
                name: {f.name for f in model.fields}
                for name, model in schema_models.items()
            }
        except Exception:
            pass
    # Fallback: simple regex parse
    schema_path = _find_prisma_schema(project_root)
    if not schema_path:
        return {}
    content = _read_file(schema_path)
    if not content:
        return {}
    fields: dict[str, set[str]] = {}
    current_model: str | None = None
    for line in content.splitlines():
        m = _RE_PRISMA_MODEL.match(line)
        if m:
            current_model = m.group(1)
            fields[current_model] = set()
            continue
        if current_model and line.strip() == "}":
            current_model = None
            continue
        if current_model:
            parts = line.strip().split()
            if parts and not parts[0].startswith("@") and not parts[0].startswith("//"):
                fields[current_model].add(parts[0])
    return fields


def _has_global_soft_delete_middleware(project_root: Path) -> bool:
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        for filename in filenames:
            if filename.endswith((".ts", ".js")):
                file_path = Path(dirpath) / filename
                content = _read_file(file_path)
                if content and re.search(
                    r"\$use\s*\(.*?deleted_at|middleware.*soft.?delete|\.use\(.*softDelete",
                    content, re.IGNORECASE | re.DOTALL,
                ):
                    return True
    return False


# ---------------------------------------------------------------------------
# Validator 1: EnumRegistryValidator (ENUM-001..003)
# ---------------------------------------------------------------------------

def run_enum_registry_scan(
    project_root: Path,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Scan for enum/role/status value mismatches across layers.

    ENUM-001 (error): Role used in @Roles() but not in seed data.
    ENUM-002 (error): Frontend status values missing from Prisma enum.
    ENUM-003 (warning): Frontend dropdown role values don't match seeds.
    """
    violations: list[Violation] = []

    # Step 1: Get Prisma enums
    prisma_enums = _get_schema_enums(project_root)

    # Step 2: Extract seed roles
    seed_roles: set[str] = set()
    seed_files = _iter_project_files(
        project_root, extensions=frozenset({".ts", ".js", ".py"}),
        path_filter=_RE_SEED_FILE,
    )
    for fp in seed_files:
        content = _read_file(fp)
        if content:
            for m in _RE_SEED_ROLE.finditer(content):
                seed_roles.add(m.group(1))

    # Step 3: Extract controller @Roles() values
    controller_roles: dict[str, list[tuple[str, int]]] = {}
    controller_files = _iter_project_files(
        project_root, extensions=frozenset({".ts", ".js"}),
        path_filter=_RE_CONTROLLER_FILE,
    )
    for fp in controller_files:
        content = _read_file(fp)
        if not content:
            continue
        rel = _rel_path(fp, project_root)
        for lineno, line in enumerate(content.splitlines(), start=1):
            dec = _RE_ROLES_DECORATOR.search(line)
            if dec:
                for rm in _RE_ROLE_STRING.finditer(dec.group(1)):
                    role = rm.group(1)
                    controller_roles.setdefault(role, []).append((rel, lineno))

    # ENUM-001: Role in @Roles() but not in seed data
    if seed_roles and controller_roles:
        for role, locs in controller_roles.items():
            if role not in seed_roles:
                for fpath, ln in locs:
                    violations.append(Violation(
                        check="ENUM-001",
                        message=(
                            f"Role '{role}' in @Roles() not found in seed data. "
                            f"Seeded roles: {', '.join(sorted(seed_roles))}. "
                            f"Users with this role will be denied access."
                        ),
                        file_path=fpath,
                        line=ln,
                        severity="critical",
                    ))

    # ENUM-002: Frontend status values missing from Prisma enum
    frontend_files = _scope_filter(
        _iter_project_files(project_root, extensions=_EXT_FRONTEND), scope
    )
    if prisma_enums:
        for fp in frontend_files:
            content = _read_file(fp)
            if not content:
                continue
            rel = _rel_path(fp, project_root)
            for lineno, line in enumerate(content.splitlines(), start=1):
                match = _RE_FRONTEND_STATUS_ARRAY.search(line)
                if match:
                    fe_values = set(_RE_STATUS_STRING.findall(match.group(1)))
                    if not fe_values:
                        continue
                    for enum_name, enum_vals in prisma_enums.items():
                        fe_lower = {v.lower() for v in fe_values}
                        schema_lower = {v.lower() for v in enum_vals}
                        overlap = fe_lower & schema_lower
                        if overlap and len(overlap) < len(fe_lower):
                            missing = fe_lower - schema_lower
                            if missing:
                                violations.append(Violation(
                                    check="ENUM-002",
                                    message=(
                                        f"Frontend status values {sorted(missing)} "
                                        f"not in Prisma enum '{enum_name}'. "
                                        f"Schema has: {sorted(enum_vals)}."
                                    ),
                                    file_path=rel,
                                    line=lineno,
                                    severity="high",
                                ))

    # ENUM-003: Dropdown role values don't match seed data
    for fp in frontend_files:
        content = _read_file(fp)
        if not content:
            continue
        rel = _rel_path(fp, project_root)
        for lineno, line in enumerate(content.splitlines(), start=1):
            if re.search(r"(?:option|select|dropdown).*role", line, re.IGNORECASE):
                values = set(_RE_ROLE_STRING.findall(line))
                if seed_roles and values:
                    bad = values - seed_roles
                    if bad:
                        violations.append(Violation(
                            check="ENUM-003",
                            message=(
                                f"Dropdown role values {sorted(bad)} "
                                f"don't match seeded roles: {sorted(seed_roles)}."
                            ),
                            file_path=rel,
                            line=lineno,
                            severity="medium",
                        ))

    return violations


# ---------------------------------------------------------------------------
# Validator 2: AuthFlowValidator (AUTH-001..004)
# ---------------------------------------------------------------------------

def _normalize_auth_path(path: str) -> str:
    """Normalize auth endpoint path for comparison."""
    path = path.strip("/").lower()
    path = re.sub(r":[^/]+|\{[^}]+\}", ":id", path)
    return path


def run_auth_flow_scan(project_root: Path) -> list[Violation]:
    """Scan for frontend-backend auth flow incompatibilities.

    AUTH-001 (error): Frontend calls auth endpoint not found in backend.
    AUTH-002 (error): MFA flow mismatch (one side implements, other doesn't).
    AUTH-003 (error): Token refresh mismatch.
    AUTH-004 (warning): Security config issues (CORS, localStorage, validation).
    """
    violations: list[Violation] = []

    fe_endpoints: list[tuple[str, str, int]] = []
    fe_has_mfa = False
    fe_has_refresh = False
    fe_mfa_files: list[tuple[str, int]] = []
    fe_refresh_files: list[tuple[str, int]] = []

    be_endpoints: list[tuple[str, str, int]] = []
    be_has_mfa = False
    be_has_refresh = False
    be_mfa_files: list[tuple[str, int]] = []
    be_refresh_files: list[tuple[str, int]] = []

    all_files = _iter_project_files(project_root, extensions=_EXT_BACKEND | _EXT_FRONTEND)

    for fp in all_files:
        content = _read_file(fp)
        if not content:
            continue
        rel = _rel_path(fp, project_root)
        is_fe = _is_frontend_file(rel)
        is_be = _is_backend_file(rel)

        for lineno, line in enumerate(content.splitlines(), start=1):
            if is_fe:
                em = _RE_FRONTEND_AUTH_CALL.search(line)
                if em:
                    fe_endpoints.append((em.group(1), rel, lineno))
                if _RE_MFA_PATTERN.search(line):
                    fe_has_mfa = True
                    fe_mfa_files.append((rel, lineno))
                if _RE_REFRESH_TOKEN.search(line):
                    fe_has_refresh = True
                    fe_refresh_files.append((rel, lineno))

            if is_be:
                rm = _RE_BACKEND_AUTH_ROUTE.search(line)
                if rm:
                    be_endpoints.append((rm.group(1), rel, lineno))
                if _RE_MFA_PATTERN.search(line):
                    be_has_mfa = True
                    be_mfa_files.append((rel, lineno))
                if _RE_REFRESH_TOKEN.search(line):
                    be_has_refresh = True
                    be_refresh_files.append((rel, lineno))

    # AUTH-001: Frontend calls auth endpoint missing from backend
    if fe_endpoints and be_endpoints:
        be_paths = {_normalize_auth_path(ep[0]) for ep in be_endpoints}
        for fe_path, fe_file, fe_line in fe_endpoints:
            if _normalize_auth_path(fe_path) not in be_paths:
                violations.append(Violation(
                    check="AUTH-001",
                    message=(
                        f"Frontend calls auth endpoint '{fe_path}' but no matching "
                        f"backend route found. Backend routes: {sorted(be_paths)}."
                    ),
                    file_path=fe_file,
                    line=fe_line,
                    severity="critical",
                ))

    # AUTH-002: MFA flow mismatch
    if fe_has_mfa and not be_has_mfa:
        for f, ln in fe_mfa_files[:3]:
            violations.append(Violation(
                check="AUTH-002",
                message="Frontend implements MFA but no backend MFA handling found.",
                file_path=f, line=ln, severity="critical",
            ))
    elif be_has_mfa and not fe_has_mfa:
        for f, ln in be_mfa_files[:3]:
            violations.append(Violation(
                check="AUTH-002",
                message="Backend implements MFA but no frontend MFA UI found.",
                file_path=f, line=ln, severity="critical",
            ))

    # AUTH-003: Token refresh mismatch
    if fe_has_refresh and not be_has_refresh:
        for f, ln in fe_refresh_files[:3]:
            violations.append(Violation(
                check="AUTH-003",
                message="Frontend implements token refresh but no backend refresh endpoint found.",
                file_path=f, line=ln, severity="high",
            ))
    elif be_has_refresh and not fe_has_refresh:
        for f, ln in be_refresh_files[:3]:
            violations.append(Violation(
                check="AUTH-003",
                message="Backend supports token refresh but frontend doesn't implement refresh logic.",
                file_path=f, line=ln, severity="medium",
            ))

    # AUTH-004: Security config issues
    for fp in all_files:
        content = _read_file(fp)
        if not content:
            continue
        rel = _rel_path(fp, project_root)

        for lineno, line in enumerate(content.splitlines(), start=1):
            # CORS hardcoded to localhost (backend only)
            if _is_backend_file(rel):
                if _RE_CORS_LOCALHOST.search(line) and not _RE_CORS_ENV_VAR.search(line):
                    violations.append(Violation(
                        check="AUTH-004",
                        message="CORS origin hardcoded to localhost. Use env variable.",
                        file_path=rel, line=lineno, severity="medium",
                    ))
                if _RE_FORBID_NON_WHITELISTED_FALSE.search(line):
                    violations.append(Violation(
                        check="AUTH-004",
                        message="forbidNonWhitelisted: false — unknown request body properties pass through.",
                        file_path=rel, line=lineno, severity="medium",
                    ))

            # localStorage token storage (frontend only)
            if _is_frontend_file(rel):
                if _RE_LOCALSTORAGE_TOKEN.search(line):
                    violations.append(Violation(
                        check="AUTH-004",
                        message="Auth token in localStorage (XSS-vulnerable). Use httpOnly cookies.",
                        file_path=rel, line=lineno, severity="medium",
                    ))

    return violations


# ---------------------------------------------------------------------------
# Validator 3: ResponseShapeValidator (SHAPE-001..003)
# ---------------------------------------------------------------------------

def run_response_shape_scan(
    project_root: Path,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Scan for response shape inconsistencies.

    SHAPE-001 (warning): camelCase || snake_case field name fallback pattern.
    SHAPE-002 (warning): Defensive Array.isArray / .data fallback handling.
    SHAPE-003 (warning): List endpoint returns bare array instead of {data, meta}.
    SHAPE-004 (warning): Silent catch — only console.log/error, no error state setter.
    """
    violations: list[Violation] = []

    # SHAPE-001 & SHAPE-002: Frontend patterns
    frontend_files = _scope_filter(
        _iter_project_files(project_root, extensions=_EXT_FRONTEND), scope
    )
    for fp in frontend_files:
        content = _read_file(fp)
        if not content:
            continue
        rel = _rel_path(fp, project_root)
        for lineno, line in enumerate(content.splitlines(), start=1):
            # SHAPE-001: camelCase || snake_case fallback
            if _RE_CASE_FALLBACK.search(line):
                violations.append(Violation(
                    check="SHAPE-001",
                    message=(
                        "camelCase || snake_case field fallback detected. "
                        "Fix the backend serialization interceptor instead."
                    ),
                    file_path=rel, line=lineno, severity="medium",
                ))

            # SHAPE-002: Defensive array/data handling
            if _RE_DEFENSIVE_ARRAY.search(line) or _RE_DEFENSIVE_OR.search(line):
                violations.append(Violation(
                    check="SHAPE-002",
                    message=(
                        "Defensive response handling (Array.isArray or .data fallback). "
                        "Indicates inconsistent API response shapes."
                    ),
                    file_path=rel, line=lineno, severity="medium",
                ))

            # SHAPE-004: Silent catch — only console.log/error, no user-facing error state
            if _RE_CATCH_BLOCK.search(line):
                all_lines = content.splitlines()
                # Start depth=1 for the catch opening brace, scan body lines
                depth = 1
                block_lines: list[str] = [line]
                for idx in range(lineno, min(lineno + 20, len(all_lines))):
                    bline = all_lines[idx]
                    depth += bline.count("{") - bline.count("}")
                    block_lines.append(bline)
                    if depth <= 0:
                        break
                block_text = "\n".join(block_lines)
                has_console = bool(re.search(r"console\.(error|log|warn)\s*\(", block_text))
                has_state_setter = bool(_RE_ERROR_STATE_SETTER.search(block_text))
                if has_console and not has_state_setter:
                    violations.append(Violation(
                        check="SHAPE-004",
                        message=(
                            "Silent catch block: only console.log/error with no "
                            "user-facing error state (setError, toast, etc.)."
                        ),
                        file_path=rel, line=lineno, severity="medium",
                    ))

    # SHAPE-003: Backend bare array returns from list endpoints
    backend_files = _scope_filter(
        _iter_project_files(
            project_root, extensions=frozenset({".ts", ".js", ".py", ".cs"}),
            path_filter=re.compile(r"(?:controller|resolver|route|handler)", re.IGNORECASE),
        ), scope
    )
    for fp in backend_files:
        content = _read_file(fp)
        if not content:
            continue
        rel = _rel_path(fp, project_root)
        lines = content.splitlines()
        in_list = False

        for lineno, line in enumerate(lines, start=1):
            if _RE_LIST_ENDPOINT.search(line):
                in_list = True
                continue
            if in_list:
                if _RE_FINDMANY_CALL.search(line) or _RE_BARE_ARRAY_RETURN.search(line):
                    ctx_start = max(0, lineno - 5)
                    ctx_end = min(len(lines), lineno + 5)
                    ctx = "\n".join(lines[ctx_start:ctx_end])
                    if not _RE_WRAPPED_RESPONSE.search(ctx):
                        violations.append(Violation(
                            check="SHAPE-003",
                            message="List endpoint may return bare array. Wrap in {data, meta}.",
                            file_path=rel, line=lineno, severity="high",
                        ))
                if re.search(r"(?:@\w+|^\s*(?:async\s+)?(?:def|function|class)\s)", line):
                    if not _RE_LIST_ENDPOINT.search(line):
                        in_list = False

    return violations


# ---------------------------------------------------------------------------
# Validator 4: SoftDeleteValidator (SOFTDEL-001..002, QUERY-001)
# ---------------------------------------------------------------------------

def run_soft_delete_scan(
    project_root: Path,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Scan for soft-delete and query correctness issues.

    SOFTDEL-001 (error): Prisma query on soft-deletable model missing deleted_at filter.
    SOFTDEL-002 (error): Query references non-existent field on model.
    QUERY-001 (warning): ``(this.prisma as any)`` cast bypasses type safety.
    """
    violations: list[Violation] = []

    soft_delete_models = _get_soft_delete_models(project_root)
    model_fields = _get_model_fields(project_root)
    has_middleware = _has_global_soft_delete_middleware(project_root)

    if not soft_delete_models and not model_fields:
        return violations  # No Prisma schema

    # Check for missing global middleware
    if soft_delete_models and not has_middleware:
        schema_path = _find_prisma_schema(project_root)
        violations.append(Violation(
            check="SOFTDEL-001",
            message=(
                f"No global soft-delete middleware. Models with deleted_at: "
                f"{', '.join(sorted(soft_delete_models))}."
            ),
            file_path=_rel_path(schema_path, project_root) if schema_path else "schema.prisma",
            line=1,
            severity="low",
        ))

    service_files = _scope_filter(
        _iter_project_files(
            project_root, extensions=frozenset({".ts", ".js"}),
            path_filter=_RE_SERVICE_FILE,
        ), scope
    )

    for fp in service_files:
        content = _read_file(fp)
        if not content:
            continue
        rel = _rel_path(fp, project_root)
        lines = content.splitlines()

        for lineno, line in enumerate(lines, start=1):
            match = _RE_PRISMA_MODEL_QUERY.search(line)
            if match:
                model_name = match.group(1)
                query_method = match.group(2)

                # SOFTDEL-001: Missing deleted_at filter
                if model_name in soft_delete_models and not has_middleware:
                    ctx_end = min(lineno + 10, len(lines))
                    ctx = "\n".join(lines[lineno - 1:ctx_end])
                    if not _RE_SOFT_DELETE_FILTER.search(ctx):
                        violations.append(Violation(
                            check="SOFTDEL-001",
                            message=(
                                f"`{model_name}.{query_method}()` missing "
                                f"deleted_at: null filter."
                            ),
                            file_path=rel, line=lineno, severity="critical",
                        ))

                # SOFTDEL-002: Field reference on non-existent field
                # Look at where clause for field names
                pascal_model = model_name[0].upper() + model_name[1:]
                known_fields = model_fields.get(pascal_model, set()) | model_fields.get(model_name, set())
                if known_fields:
                    ctx_end = min(lineno + 15, len(lines))
                    ctx = "\n".join(lines[lineno - 1:ctx_end])
                    # Extract field references from where/include blocks
                    for field_ref in re.findall(r"(\w+)\s*:", ctx):
                        if (
                            field_ref in known_fields
                            or field_ref in {
                                "where", "include", "select", "orderBy",
                                "skip", "take", "data", "create", "update",
                                "connect", "disconnect", "set", "AND", "OR",
                                "NOT", "some", "every", "none", "is", "isNot",
                            }
                        ):
                            continue
                        # Don't flag common Prisma query operators
                        if field_ref.startswith("_") or field_ref in {"gt", "gte", "lt", "lte", "in", "notIn", "contains", "startsWith", "endsWith", "not", "equals", "has", "hasEvery", "hasSome", "isEmpty", "mode"}:
                            continue

            # QUERY-001: (this.prisma as any) cast
            if _RE_PRISMA_ANY_CAST.search(line):
                violations.append(Violation(
                    check="QUERY-001",
                    message="`(this.prisma as any)` bypasses Prisma type safety.",
                    file_path=rel, line=lineno, severity="medium",
                ))

        # Post-pagination filtering detection
        for lineno, line in enumerate(lines, start=1):
            if re.search(r"\.findMany\s*\(", line):
                ctx_end = min(lineno + 10, len(lines))
                ctx = "\n".join(lines[lineno - 1:ctx_end])
                if re.search(r"(?:skip|take)\s*:", ctx):
                    scan_end = min(lineno + 15, len(lines))
                    for offset in range(lineno, scan_end):
                        if _RE_POST_QUERY_FILTER.search(lines[offset]):
                            violations.append(Violation(
                                check="SOFTDEL-002",
                                message=(
                                    "Post-pagination filtering: .filter()/.map() "
                                    "after paginated findMany(). Move to where clause."
                                ),
                                file_path=rel, line=offset + 1, severity="high",
                            ))
                            break

    return violations


# ---------------------------------------------------------------------------
# Validator 5: InfrastructureValidator (INFRA-001..008)
# ---------------------------------------------------------------------------

def run_infrastructure_scan(project_root: Path) -> list[Violation]:
    """Scan for infrastructure / build configuration issues.

    INFRA-001 (error): Port mismatch between .env and config files.
    INFRA-002 (error): Conflicting config files (e.g., next.config.js AND .ts).
    INFRA-003 (warning): tsconfig.json missing test directory exclusions.
    INFRA-004 (warning): Docker service missing restart policy.
    INFRA-005 (warning): Docker service missing healthcheck.
    INFRA-006 (critical): next.config enables experimental.workerThreads,
        which has caused Docker build DataCloneError failures.
    INFRA-007 (critical): NestJS 11 / Express 5 route strings use unnamed
        wildcard syntax such as ``forRoutes('*')`` or ``@Get('users/*')``.
    INFRA-008 (critical): Express 5 middleware reassigns ``req.query``,
        which is getter-backed and not writable.
    """
    violations: list[Violation] = []

    # INFRA-001: Port mismatches
    env_ports = _extract_env_ports(project_root)
    config_ports = _extract_config_ports(project_root)
    if env_ports and config_ports:
        for name, (ep, ef, el) in env_ports.items():
            for cname, (cp, cf, cl) in config_ports.items():
                if _port_names_related(name, cname) and ep != cp:
                    violations.append(Violation(
                        check="INFRA-001",
                        message=f"Port mismatch: {name}={ep} in {ef} but {cname}={cp} in {cf}.",
                        file_path=ef, line=el, severity="critical",
                    ))

    # INFRA-002: Conflicting config files
    config_groups = [
        ["next.config.js", "next.config.ts", "next.config.mjs", "next.config.cjs"],
        ["vite.config.js", "vite.config.ts", "vite.config.mjs"],
        ["tailwind.config.js", "tailwind.config.ts", "tailwind.config.cjs"],
        ["postcss.config.js", "postcss.config.ts", "postcss.config.mjs", "postcss.config.cjs"],
        ["jest.config.js", "jest.config.ts"],
    ]
    for group in config_groups:
        existing = [n for n in group if (project_root / n).is_file()]
        if len(existing) > 1:
            violations.append(Violation(
                check="INFRA-002",
                message=f"Conflicting config files: {', '.join(existing)}. Only one should exist.",
                file_path=existing[0], line=1, severity="critical",
            ))

    # INFRA-006: Next workerThreads clone failures in Docker builds.
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for name in files:
            if name not in {"next.config.js", "next.config.ts", "next.config.mjs", "next.config.cjs"}:
                continue
            fp = Path(root) / name
            content = _read_file(fp)
            if "workerThreads" not in content:
                continue
            rel_path = str(fp.relative_to(project_root)).replace("\\", "/")
            line = 1
            for idx, text in enumerate(content.splitlines(), start=1):
                if "workerThreads" in text:
                    line = idx
                    break
            violations.append(Violation(
                check="INFRA-006",
                message=(
                    "Next experimental.workerThreads is blocked for generated "
                    "Docker builds; it has caused DataCloneError failures."
                ),
                file_path=rel_path,
                line=line,
                severity="critical",
            ))

    # INFRA-007: NestJS 11 / Express 5 unnamed wildcard route strings.
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for name in files:
            suffix = Path(name).suffix.lower()
            if suffix not in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
                continue
            fp = Path(root) / name
            content = _read_file(fp)
            if not content or "*" not in content:
                continue
            rel_path = str(fp.relative_to(project_root)).replace("\\", "/")
            for line, route in _iter_invalid_wildcard_routes(content):
                violations.append(Violation(
                    check="INFRA-007",
                    message=(
                        "NestJS 11 / Express 5 wildcard paths must be named; "
                        f"replace {route!r} with `forRoutes('{{*splat}}')` for "
                        "all-route middleware or a named route like "
                        "`/*splat` / `/{*splat}`."
                    ),
                    file_path=rel_path,
                    line=line,
                    severity="critical",
                ))

    # INFRA-008: Express 5 req.query reassignment.
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for name in files:
            suffix = Path(name).suffix.lower()
            if suffix not in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
                continue
            fp = Path(root) / name
            content = _read_file(fp)
            if not content or "query" not in content or "=" not in content:
                continue
            rel_path = str(fp.relative_to(project_root)).replace("\\", "/")
            for match in _RE_REQ_QUERY_ASSIGNMENT.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                violations.append(Violation(
                    check="INFRA-008",
                    message=(
                        "Express 5 `req.query` is getter-backed and must not "
                        "be reassigned; normalize the existing object in place "
                        "or use a local derived copy."
                    ),
                    file_path=rel_path,
                    line=line,
                    severity="critical",
                ))

    # INFRA-003: tsconfig test exclusions
    tsconfig_path = project_root / "tsconfig.json"
    if tsconfig_path.is_file():
        content = _read_file(tsconfig_path)
        if content:
            exc = _RE_TSCONFIG_EXCLUDE.search(content)
            test_dirs_exist = any(
                (project_root / d).is_dir()
                for d in ["__tests__", "e2e", "test", "tests", "playwright", "cypress"]
            )
            if exc:
                if not _RE_TEST_DIR_PATTERN.search(exc.group(1)):
                    violations.append(Violation(
                        check="INFRA-003",
                        message="tsconfig exclude array missing test directories.",
                        file_path="tsconfig.json", line=1, severity="medium",
                    ))
            elif test_dirs_exist:
                violations.append(Violation(
                    check="INFRA-003",
                    message="tsconfig.json has no exclude but test directories exist.",
                    file_path="tsconfig.json", line=1, severity="medium",
                ))

    # INFRA-004 & INFRA-005: Docker compose checks
    for dc_name in ["docker-compose.yml", "docker-compose.yaml"]:
        dc_path = project_root / dc_name
        if not dc_path.is_file():
            continue
        content = _read_file(dc_path)
        if not content:
            continue

        # Find service blocks
        services_section = False
        service_blocks: list[tuple[str, int, int]] = []  # (name, start, end)
        current_service: str | None = None
        current_start = 0
        lines = content.splitlines()

        for lineno, line in enumerate(lines, start=1):
            if re.match(r"^services\s*:", line):
                services_section = True
                continue
            if services_section:
                svc_match = re.match(r"^  (\w[\w-]*):\s*$", line)
                if svc_match:
                    if current_service:
                        service_blocks.append((current_service, current_start, lineno - 1))
                    current_service = svc_match.group(1)
                    current_start = lineno
                elif line and not line.startswith(" ") and not line.startswith("#"):
                    if current_service:
                        service_blocks.append((current_service, current_start, lineno - 1))
                    services_section = False
                    current_service = None

        if current_service:
            service_blocks.append((current_service, current_start, len(lines)))

        for svc_name, start, end in service_blocks:
            block = "\n".join(lines[start - 1:end])
            if not _RE_DOCKER_RESTART.search(block):
                violations.append(Violation(
                    check="INFRA-004",
                    message=f"Docker service '{svc_name}' missing restart policy.",
                    file_path=dc_name, line=start, severity="medium",
                ))
            if not _RE_DOCKER_HEALTHCHECK.search(block):
                violations.append(Violation(
                    check="INFRA-005",
                    message=f"Docker service '{svc_name}' missing healthcheck.",
                    file_path=dc_name, line=start, severity="medium",
                ))

    return violations


def _extract_env_ports(project_root: Path) -> dict[str, tuple[str, str, int]]:
    ports: dict[str, tuple[str, str, int]] = {}
    for name in os.listdir(project_root):
        if name.startswith(".env") and not name.endswith(".example"):
            fp = project_root / name
            if fp.is_file():
                content = _read_file(fp)
                if content:
                    for lineno, line in enumerate(content.splitlines(), start=1):
                        m = re.match(r"(\w*PORT\w*)\s*=\s*(\d+)", line)
                        if m:
                            ports[m.group(1)] = (m.group(2), name, lineno)
    return ports


def _extract_config_ports(project_root: Path) -> dict[str, tuple[str, str, int]]:
    ports: dict[str, tuple[str, str, int]] = {}
    for cfg in [
        "package.json", "docker-compose.yml", "docker-compose.yaml",
        "Dockerfile", "angular.json", "vite.config.ts", "vite.config.js",
        "next.config.js", "next.config.ts", "next.config.mjs",
    ]:
        fp = project_root / cfg
        if not fp.is_file():
            continue
        content = _read_file(fp)
        if content:
            for lineno, line in enumerate(content.splitlines(), start=1):
                m = _RE_CONFIG_PORT.search(line)
                if m:
                    ports[f"{cfg}:PORT"] = (m.group(1), cfg, lineno)
    return ports


def _port_names_related(env_name: str, config_name: str) -> bool:
    env_lower = env_name.lower().replace("_", "")
    cfg_lower = config_name.lower().replace("_", "").replace(":", "")
    if "port" in env_lower and "port" in cfg_lower:
        if env_lower == "port" or cfg_lower.endswith("port"):
            return True
        env_pfx = env_lower.replace("port", "")
        cfg_pfx = cfg_lower.replace("port", "").split(".")[0]
        if env_pfx and cfg_pfx and (env_pfx in cfg_pfx or cfg_pfx in env_pfx):
            return True
    return False


def _route_has_unnamed_wildcard(route: str) -> bool:
    route_text = str(route or "")
    for index, char in enumerate(route_text):
        if char != "*":
            continue
        next_char = route_text[index + 1] if index + 1 < len(route_text) else ""
        if not (next_char.isalpha() or next_char == "_"):
            return True
    return False


def _iter_invalid_wildcard_routes(content: str) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for pattern in _RE_ROUTE_LITERAL_PATTERNS:
        for match in pattern.finditer(content):
            route = str(match.group(1) or "")
            if not _route_has_unnamed_wildcard(route):
                continue
            line = content.count("\n", 0, match.start()) + 1
            key = (line, route)
            if key in seen:
                continue
            seen.add(key)
            matches.append((line, route))
    return matches


# ---------------------------------------------------------------------------
# Validator registry and main entry point
# ---------------------------------------------------------------------------

_VALIDATOR_MAP: dict[str, callable] = {
    "enum": run_enum_registry_scan,
    "auth": run_auth_flow_scan,
    "response-shape": run_response_shape_scan,
    "soft-delete": run_soft_delete_scan,
    "infrastructure": run_infrastructure_scan,
}

_CHECK_TO_CATEGORY: dict[str, str] = {
    "ENUM-001": "enum", "ENUM-002": "enum", "ENUM-003": "enum",
    "AUTH-001": "auth", "AUTH-002": "auth", "AUTH-003": "auth", "AUTH-004": "auth",
    "SHAPE-001": "response-shape", "SHAPE-002": "response-shape", "SHAPE-003": "response-shape", "SHAPE-004": "response-shape",
    "SOFTDEL-001": "soft-delete", "SOFTDEL-002": "soft-delete", "QUERY-001": "soft-delete",
    "INFRA-001": "infrastructure", "INFRA-002": "infrastructure",
    "INFRA-003": "infrastructure", "INFRA-004": "infrastructure", "INFRA-005": "infrastructure",
    "INFRA-006": "infrastructure", "INFRA-007": "infrastructure", "INFRA-008": "infrastructure",
}


def run_quality_validators(
    project_root: Path,
    checks: list[str] | None = None,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Run all or selected quality validators.

    Args:
        project_root: Root directory of the project to scan.
        checks: Optional list of check IDs or category names to run.
        scope: Optional ScanScope to limit which files are scanned.

    Returns:
        List of violations sorted by severity, capped at _MAX_VIOLATIONS.
    """
    violations: list[Violation] = []

    if checks is None:
        cats = set(_VALIDATOR_MAP.keys())
    else:
        cats: set[str] = set()
        for c in checks:
            if c in _VALIDATOR_MAP:
                cats.add(c)
            elif c in _CHECK_TO_CATEGORY:
                cats.add(_CHECK_TO_CATEGORY[c])

    for cat, fn in _VALIDATOR_MAP.items():
        if cat not in cats:
            continue
        # Call with scope where supported
        import inspect
        sig = inspect.signature(fn)
        if "scope" in sig.parameters:
            cat_violations = fn(project_root, scope=scope)
        else:
            cat_violations = fn(project_root)
        violations.extend(cat_violations)
        if len(violations) >= _MAX_VIOLATIONS:
            break

    if checks:
        check_ids = [c for c in checks if c in _CHECK_TO_CATEGORY]
        if check_ids:
            violations = [v for v in violations if v.check in check_ids]

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line))
    return violations
