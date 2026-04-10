"""Extract ACTUAL API contracts from implemented backend code.

Parses NestJS controllers, DTOs, Prisma schema, Express routes, Django views,
and FastAPI routes to produce a machine-readable contract that frontend agents
can reference.  This eliminates the 90%+ wiring-mismatch bugs caused by
frontend agents receiving only brief prose summaries of backend milestones
instead of concrete endpoint paths, field names, and response shapes.

The module is **standalone** — it imports only from the Python standard library
and can be used independently of the rest of agent-team-v15.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any
import fnmatch

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skip-directory defaults (can be overridden via _active_skip_dirs)
# ---------------------------------------------------------------------------
_DEFAULT_TS_SKIP = ("node_modules", "/dist/", "/build/", "/.next/")
_DEFAULT_PY_SKIP = ("venv", "site-packages", "__pycache__", ".tox")
# Module-level override set by extract_api_contracts when config provides custom dirs
_active_skip_dirs: tuple[str, ...] | None = None
_active_paths_filter: tuple[str, ...] | None = None


def _should_skip(posix_path: str, default_skip: tuple[str, ...]) -> bool:
    """Check if a file path should be skipped during scanning."""
    skip = _active_skip_dirs if _active_skip_dirs is not None else default_skip
    return any(s in posix_path for s in skip)


# ---------------------------------------------------------------------------
# Compiled regex patterns (module-level for performance)
# ---------------------------------------------------------------------------

# --- NestJS ---

# @Controller('prefix') or @Controller()  (handles multi-line, optional quotes)
_NESTJS_CONTROLLER_RE = re.compile(
    r"@Controller\(\s*['\"]([^'\"]*?)['\"]\s*\)",
    re.MULTILINE,
)

# HTTP-method decorators: @Get(), @Post('/path'), @Delete('/:id'), etc.
# Captures the HTTP method decorator and its sub-path.  The handler name
# is resolved separately (see _find_handler_name) because a simple lazy
# quantifier like [\s\S]*? would incorrectly stop at stacked decorators
# such as @Roles() or @ApiOperation() whose arguments contain '('.
_NESTJS_HTTP_DECORATOR_RE = re.compile(
    r"@(Get|Post|Put|Patch|Delete)\(\s*(?:['\"]([^'\"]*?)['\"])?\s*\)",
    re.MULTILINE,
)

# Matches the actual handler method signature after all stacked decorators.
# Looks for `async handlerName(` or `handlerName(` that is NOT preceded by '@'.
_NESTJS_HANDLER_SIG_RE = re.compile(
    r"^\s*(?:async\s+)?(\w+)\s*\(",
    re.MULTILINE,
)

# --- Express ---

# router.get('/path', ...) or app.post('/path', ...)
_EXPRESS_ROUTE_RE = re.compile(
    r"(?:router|app)\s*\.\s*(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE | re.MULTILINE,
)

# --- FastAPI ---

# @app.get("/path") or @router.post("/path")
_FASTAPI_ROUTE_RE = re.compile(
    r"@\w+\.\s*(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE | re.MULTILINE,
)

# FastAPI handler:  async def handler_name(...)
_FASTAPI_HANDLER_RE = re.compile(
    r"(?:async\s+)?def\s+(\w+)\s*\(",
    re.MULTILINE,
)

# --- Django ---

# path('url/', view_func, name='name')
_DJANGO_PATH_RE = re.compile(
    r"path\s*\(\s*['\"]([^'\"]*)['\"]"
    r"\s*,\s*"
    r"([\w.]+)",
    re.MULTILINE,
)

# --- DTO fields (NestJS / class-validator) ---

# Decorator line(s) followed by property declaration.
# e.g.  @IsString()  @IsOptional()  name?: string;
_DTO_FIELD_RE = re.compile(
    r"((?:@\w+\([^)]*\)\s*)+)"  # one or more decorators
    r"\s*(?:readonly\s+)?"
    r"(\w+)\s*[?!]?\s*:\s*"  # field name + colon
    r"([^;=\n]+)",  # type (up to semicolon or newline)
    re.MULTILINE,
)

# Individual decorator extractor (within a decorator block)
_DECORATOR_NAME_RE = re.compile(r"@(\w+)\(")

# --- Prisma ---

# model ModelName { ... }
_PRISMA_MODEL_RE = re.compile(
    r"model\s+(\w+)\s*\{([^}]+)\}",
    re.MULTILINE | re.DOTALL,
)

# Prisma field line:  name  Type  optional?  @modifiers
_PRISMA_FIELD_RE = re.compile(
    r"^\s+(\w+)\s+([\w\[\]]+)(\?)?\s*(.*?)$",
    re.MULTILINE,
)

# enum EnumName { ... }
_PRISMA_ENUM_RE = re.compile(
    r"enum\s+(\w+)\s*\{([^}]+)\}",
    re.MULTILINE | re.DOTALL,
)

# --- NestJS response / parameter extraction ---

# @ApiResponse({ ... type: SomeDto ... })   — extract the DTO class name
_NESTJS_API_RESPONSE_TYPE_RE = re.compile(
    r"@ApiResponse\(\s*\{[^}]*\btype:\s*(\w+)",
    re.MULTILINE,
)

# Return type annotation on handler:  ): Promise<SomeType> {  or  ): SomeType {
_NESTJS_RETURN_TYPE_RE = re.compile(
    r"\)\s*(?::\s*(Promise\s*<\s*[\w<>,\s\[\]]+>|[\w<>\[\]]+))?\s*\{",
    re.MULTILINE,
)

# @Body() paramName: DtoClass   (with optional pipe)
_NESTJS_BODY_PARAM_RE = re.compile(
    r"@Body\([^)]*\)\s*\w+\s*:\s*(\w+)",
    re.MULTILINE,
)

# @Query() paramName: DtoClass   (with optional pipe)
_NESTJS_QUERY_PARAM_RE = re.compile(
    r"@Query\([^)]*\)\s*\w+\s*:\s*(\w+)",
    re.MULTILINE,
)

# --- @IsIn() validator extraction (functional enums in DTOs) ---

# @IsIn(['corrective', 'preventive', 'emergency', 'inspection'])
# Captures the array contents inside @IsIn([...])
_ISIN_VALIDATOR_RE = re.compile(
    r"@IsIn\(\s*\[([^\]]+)\]\s*\)",
    re.MULTILINE,
)

# The field name that follows the @IsIn decorator (same as DTO field pattern)
# e.g.  @IsIn([...])  type!: string;
_ISIN_FIELD_RE = re.compile(
    r"@IsIn\(\s*\[[^\]]+\]\s*\)"
    r"\s*(?:@\w+\([^)]*\)\s*)*"  # optional additional decorators
    r"(?:readonly\s+)?"
    r"(\w+)\s*[?!]?\s*:",
    re.MULTILINE,
)

# --- TypeScript enum extraction ---

# export enum Foo { ... }  or  enum Foo { ... }
_TS_ENUM_RE = re.compile(
    r"(?:export\s+)?enum\s+(\w+)\s*\{([^}]+)\}",
    re.MULTILINE | re.DOTALL,
)

# --- Import statement parsing ---

# import { Foo, Bar } from './path';
_TS_IMPORT_RE = re.compile(
    r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)

# --- Naming convention detection ---

_SNAKE_CASE_RE = re.compile(r"[a-z]+_[a-z]")
_CAMEL_CASE_RE = re.compile(r"[a-z]+[A-Z]")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EndpointContract:
    """A single API endpoint extracted from implemented backend code."""

    path: str
    method: str  # GET, POST, PUT, PATCH, DELETE
    handler_name: str
    controller_file: str
    request_params: list[str] = field(default_factory=list)
    request_body_fields: list[dict[str, str]] = field(default_factory=list)
    response_fields: list[dict[str, str]] = field(default_factory=list)
    response_type: str = ""


@dataclass
class ModelContract:
    """A data model (e.g. Prisma model) extracted from schema files."""

    name: str
    fields: list[dict[str, Any]] = field(default_factory=list)
    # Each field dict: {"name": str, "type": str, "nullable": bool}


@dataclass
class EnumContract:
    """An enum extracted from schema files."""

    name: str
    values: list[str] = field(default_factory=list)


@dataclass
class APIContractBundle:
    """Complete API contract extracted from a project's backend code."""

    version: str = "1.0"
    extracted_from_milestone: str = ""
    endpoints: list[EndpointContract] = field(default_factory=list)
    models: list[ModelContract] = field(default_factory=list)
    enums: list[EnumContract] = field(default_factory=list)
    field_naming_convention: str = "camelCase"  # "snake_case" or "camelCase"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_read(path: Path) -> str:
    """Read a file returning its text, or empty string on failure.

    Tries UTF-8 first (with BOM handling via ``utf-8-sig``), then falls back
    to ``latin-1`` for files with non-UTF-8 encoding.
    """
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            logger.warning("Could not read %s: %s", path, exc)
            return ""
    logger.warning("Could not decode %s with any supported encoding", path)
    return ""


def _find_files(root: Path, glob_pattern: str) -> list[Path]:
    """Recursively find files matching *glob_pattern* under *root*.

    Silently returns an empty list when *root* does not exist.
    """
    if not root.is_dir():
        logger.warning("Project root does not exist or is not a directory: %s", root)
        return []
    if _active_paths_filter is not None:
        matches: list[Path] = []
        for rel_path in _active_paths_filter:
            candidate = root / rel_path
            if not candidate.is_file():
                continue
            if _path_matches_filter(rel_path, glob_pattern):
                matches.append(candidate)
        return sorted(set(matches))
    try:
        return sorted(root.rglob(glob_pattern))
    except OSError as exc:
        logger.warning("Error scanning %s for %s: %s", root, glob_pattern, exc)
        return []


def _path_matches_filter(path: str, glob_pattern: str) -> bool:
    posix_path = path.replace("\\", "/")
    file_name = PurePosixPath(posix_path).name
    return fnmatch.fnmatch(file_name, glob_pattern) or fnmatch.fnmatch(posix_path, glob_pattern)


def _normalize_paths_filter(project_root: Path, paths_filter: list[str] | None) -> tuple[str, ...] | None:
    if not paths_filter:
        return None

    normalized: list[str] = []
    root_resolved = project_root.resolve()
    for raw_path in paths_filter:
        if not raw_path:
            continue
        try:
            path = Path(raw_path)
            if path.is_absolute():
                rel_path = path.resolve().relative_to(root_resolved).as_posix()
            else:
                rel_path = path.as_posix()
        except (OSError, ValueError):
            continue
        rel_path = rel_path.lstrip("./")
        if rel_path:
            normalized.append(rel_path)

    if not normalized:
        return None
    return tuple(dict.fromkeys(normalized))


def _normalize_path(path: Path, root: Path) -> str:
    """Return a POSIX-style path relative to *root*."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _extract_route_params(path: str) -> list[str]:
    """Extract path parameters like :id or {id} from a route string."""
    params: list[str] = []
    # NestJS / Express style  :paramName
    for match in re.finditer(r":(\w+)", path):
        params.append(match.group(1))
    # FastAPI / Django style  {param_name}
    for match in re.finditer(r"\{(\w+)\}", path):
        params.append(match.group(1))
    # Django style <type:param>
    for match in re.finditer(r"<(?:\w+:)?(\w+)>", path):
        params.append(match.group(1))
    return params


# ---------------------------------------------------------------------------
# NestJS parser
# ---------------------------------------------------------------------------


def _find_handler_name(content: str, search_start: int) -> str:
    """Find the actual handler method name after stacked NestJS decorators.

    Starting from *search_start* (just after the HTTP-method decorator),
    skip any number of ``@DecoratorName(...)`` lines until we reach a line
    that looks like a method signature: ``async handlerName(`` or
    ``handlerName(``.

    Returns the handler name, or ``"unknown"`` if none is found within a
    reasonable distance.
    """
    # Limit search to ~2000 chars to avoid runaway scanning
    region = content[search_start:search_start + 2000]
    for sig_match in _NESTJS_HANDLER_SIG_RE.finditer(region):
        candidate = sig_match.group(1)
        # The line must NOT be a decorator argument — decorators are preceded
        # by '@' on the same or previous line.  We check if the matched
        # position in the region is preceded by '@' on the same line.
        line_start = region.rfind("\n", 0, sig_match.start()) + 1
        line_prefix = region[line_start:sig_match.start()].strip()
        if line_prefix.startswith("@"):
            # This is a decorator, keep scanning
            continue
        return candidate
    return "unknown"


def extract_nestjs_endpoints(project_root: Path) -> list[EndpointContract]:
    """Scan for ``*.controller.ts`` files and extract NestJS endpoint contracts.

    Parses ``@Controller('prefix')`` and ``@Get()``/``@Post()``/... decorators
    to build a list of endpoint contracts with route paths, HTTP methods, and
    handler names.  Also extracts:

    - **Response type hints** from ``@ApiResponse({ type: Dto })`` decorators
      and return-type annotations (``Promise<Foo>``).
    - **Body DTO** from ``@Body() param: DtoClass`` parameter annotations.
    - **Query DTO** from ``@Query() param: DtoClass`` parameter annotations.
    """
    endpoints: list[EndpointContract] = []
    controller_files = _find_files(project_root, "*.controller.ts")

    for cfile in controller_files:
        content = _safe_read(cfile)
        if not content:
            continue

        rel_path = _normalize_path(cfile, project_root)

        # Collect imported DTO names for this controller file
        imported_dtos: set[str] = set()
        for imp_match in _TS_IMPORT_RE.finditer(content):
            names_block = imp_match.group(1)
            for name in names_block.split(","):
                name = name.strip()
                if name:
                    imported_dtos.add(name)

        # Determine controller-level route prefix
        prefix = ""
        ctrl_match = _NESTJS_CONTROLLER_RE.search(content)
        if ctrl_match:
            prefix = ctrl_match.group(1).strip("/")

        # Collect all HTTP-method decorator positions first (two-pass approach)
        http_matches = list(_NESTJS_HTTP_DECORATOR_RE.finditer(content))

        # Find all HTTP-method decorators and their handler methods
        for idx, method_match in enumerate(http_matches):
            http_method = method_match.group(1).upper()  # Get -> GET
            sub_path = method_match.group(2) or ""

            # --- Resolve actual handler name (two-pass) ---
            # Scan forward from the HTTP decorator to find the method
            # signature, skipping any stacked decorators in between.
            handler_name = _find_handler_name(content, method_match.end())

            # Build full path
            parts = [p for p in [prefix, sub_path.strip("/")] if p]
            full_path = "/" + "/".join(parts) if parts else "/"

            route_params = _extract_route_params(full_path)

            # --- Extract the decorator+handler block for this endpoint ---
            # The block spans from the start of the HTTP-method decorator
            # to the next HTTP-method decorator (or end of file).
            block_start = method_match.start()
            next_method = http_matches[idx + 1] if idx + 1 < len(http_matches) else None
            block_end = next_method.start() if next_method else len(content)
            handler_block = content[block_start:block_end]

            # --- Response type detection (Gap 2) ---
            response_type = ""

            # 1. @ApiResponse({ type: DtoClass })
            api_resp_match = _NESTJS_API_RESPONSE_TYPE_RE.search(handler_block)
            if api_resp_match:
                response_type = api_resp_match.group(1)

            # 2. Return type annotation: ): Promise<SomeType> {
            if not response_type:
                ret_match = _NESTJS_RETURN_TYPE_RE.search(handler_block)
                if ret_match and ret_match.group(1):
                    raw_return = ret_match.group(1).strip()
                    # Normalise whitespace inside generics
                    raw_return = re.sub(r"\s+", "", raw_return)
                    # Unwrap Promise<T> → T
                    promise_inner = re.match(r"^Promise<(.+)>$", raw_return)
                    if promise_inner:
                        raw_return = promise_inner.group(1)
                    if raw_return and raw_return not in ("void",):
                        response_type = raw_return

            # --- Body / Query DTO detection (Gap 3) ---
            body_dto_name = ""
            query_dto_name = ""

            body_match = _NESTJS_BODY_PARAM_RE.search(handler_block)
            if body_match:
                body_dto_name = body_match.group(1)

            query_match = _NESTJS_QUERY_PARAM_RE.search(handler_block)
            if query_match:
                query_dto_name = query_match.group(1)

            ep = EndpointContract(
                path=full_path,
                method=http_method,
                handler_name=handler_name,
                controller_file=rel_path,
                request_params=route_params,
                response_type=response_type,
            )

            # Stash DTO names for later enrichment (stored as lightweight
            # annotations so _enrich_endpoints_with_dtos can use them).
            if body_dto_name:
                ep.request_body_fields = [{"__dto_class__": body_dto_name}]
            if query_dto_name:
                # Store as first entry in request_params metadata
                ep.request_params = route_params + [f"__query_dto__:{query_dto_name}"]

            endpoints.append(ep)

    logger.info("Extracted %d NestJS endpoints from %d controller files",
                len(endpoints), len(controller_files))
    return endpoints


# ---------------------------------------------------------------------------
# Express parser
# ---------------------------------------------------------------------------

def extract_express_endpoints(project_root: Path) -> list[EndpointContract]:
    """Scan for Express-style ``router.get``/``app.post``/... route definitions.

    Looks in ``*.ts``, ``*.js``, ``*.mjs`` files for patterns like
    ``router.get('/users', ...)`` or ``app.post('/auth/login', ...)``.
    """
    endpoints: list[EndpointContract] = []
    extensions = ("*.ts", "*.js", "*.mjs")
    route_files: list[Path] = []
    for ext in extensions:
        route_files.extend(_find_files(project_root, ext))

    seen_files: set[str] = set()
    for rfile in route_files:
        # Skip NestJS controller files (handled by the NestJS parser)
        if rfile.name.endswith(".controller.ts"):
            continue
        # Skip node_modules, dist, build
        posix = rfile.as_posix()
        if _should_skip(posix, _DEFAULT_TS_SKIP):
            continue

        content = _safe_read(rfile)
        if not content:
            continue

        rel_path = _normalize_path(rfile, project_root)
        file_had_match = False

        for m in _EXPRESS_ROUTE_RE.finditer(content):
            http_method = m.group(1).upper()
            route_path = m.group(2)

            route_params = _extract_route_params(route_path)

            endpoints.append(EndpointContract(
                path=route_path if route_path.startswith("/") else "/" + route_path,
                method=http_method,
                handler_name="",  # Express inline handlers don't always have names
                controller_file=rel_path,
                request_params=route_params,
            ))
            file_had_match = True

        if file_had_match and rel_path not in seen_files:
            seen_files.add(rel_path)

    logger.info("Extracted %d Express endpoints from %d route files",
                len(endpoints), len(seen_files))
    return endpoints


# ---------------------------------------------------------------------------
# FastAPI parser
# ---------------------------------------------------------------------------

def _extract_fastapi_endpoints(project_root: Path) -> list[EndpointContract]:
    """Scan Python files for FastAPI-style route decorators.

    Parses ``@app.get("/path")`` and ``@router.post("/path")`` patterns.
    """
    endpoints: list[EndpointContract] = []
    py_files = _find_files(project_root, "*.py")

    for pyfile in py_files:
        posix = pyfile.as_posix()
        if _should_skip(posix, _DEFAULT_PY_SKIP):
            continue

        content = _safe_read(pyfile)
        if not content:
            continue

        rel_path = _normalize_path(pyfile, project_root)

        # Collect all route decorators with their positions
        route_matches = list(_FASTAPI_ROUTE_RE.finditer(content))
        if not route_matches:
            continue

        # Also collect all function definitions with positions
        handler_matches = list(_FASTAPI_HANDLER_RE.finditer(content))

        for rm in route_matches:
            http_method = rm.group(1).upper()
            route_path = rm.group(2)
            decorator_end = rm.end()

            # Find the next function definition after this decorator
            handler_name = ""
            for hm in handler_matches:
                if hm.start() >= decorator_end:
                    handler_name = hm.group(1)
                    break

            route_params = _extract_route_params(route_path)

            endpoints.append(EndpointContract(
                path=route_path if route_path.startswith("/") else "/" + route_path,
                method=http_method,
                handler_name=handler_name,
                controller_file=rel_path,
                request_params=route_params,
            ))

    logger.info("Extracted %d FastAPI endpoints", len(endpoints))
    return endpoints


# ---------------------------------------------------------------------------
# Django parser
# ---------------------------------------------------------------------------

def _extract_django_endpoints(project_root: Path) -> list[EndpointContract]:
    """Scan Django ``urls.py`` files for ``path()`` definitions."""
    endpoints: list[EndpointContract] = []
    url_files = [
        p for p in _find_files(project_root, "urls.py")
        if "venv" not in p.as_posix() and "site-packages" not in p.as_posix()
    ]

    for ufile in url_files:
        content = _safe_read(ufile)
        if not content:
            continue

        rel_path = _normalize_path(ufile, project_root)

        for m in _DJANGO_PATH_RE.finditer(content):
            url_pattern = m.group(1)
            view_ref = m.group(2)

            # Django path() doesn't carry HTTP method info; default to ALL
            route_params = _extract_route_params(url_pattern)
            full_path = "/" + url_pattern.strip("/") if url_pattern else "/"

            endpoints.append(EndpointContract(
                path=full_path,
                method="ALL",
                handler_name=view_ref,
                controller_file=rel_path,
                request_params=route_params,
            ))

    logger.info("Extracted %d Django URL patterns", len(endpoints))
    return endpoints


# ---------------------------------------------------------------------------
# DTO parser (NestJS / class-validator style)
# ---------------------------------------------------------------------------

def extract_dto_fields(project_root: Path) -> dict[str, list[dict[str, str]]]:
    """Scan DTO files **and controller files** for class properties with validator decorators.

    Many NestJS projects define DTO classes inline inside ``*.controller.ts``
    rather than in dedicated ``*.dto.ts`` files.  This parser scans both.

    Returns a mapping of ``{DtoClassName: [{name, type, decorators}, ...]}``.
    """
    dto_map: dict[str, list[dict[str, str]]] = {}
    dto_files = _find_files(project_root, "*.dto.ts")

    # Also check for inline DTOs in controller files and request/response files
    for alt_pattern in ("*request*.ts", "*response*.ts", "*.controller.ts"):
        dto_files.extend(_find_files(project_root, alt_pattern))

    # Deduplicate
    dto_files = sorted(set(dto_files))

    # Pattern to extract class name:  export class CreateUserDto { ... }
    class_re = re.compile(
        r"(?:export\s+)?class\s+(\w+(?:Dto|DTO|Request|Response)\w*)\s*"
        r"(?:extends\s+\w+\s*)?"
        r"(?:implements\s+[\w,\s]+\s*)?"
        r"\{",
        re.MULTILINE,
    )

    for dfile in dto_files:
        posix = dfile.as_posix()
        if "node_modules" in posix or "/dist/" in posix:
            continue

        content = _safe_read(dfile)
        if not content:
            continue

        # Find all DTO classes in the file
        class_matches = list(class_re.finditer(content))
        if not class_matches:
            continue

        for idx, cm in enumerate(class_matches):
            class_name = cm.group(1)

            # Filter false positives: class names ending with Controller,
            # Service, Module, Guard, etc. are NOT DTOs even if they
            # contain "Request" or "Response" in their name.
            if any(class_name.endswith(suffix) for suffix in (
                "Controller", "Service", "Module", "Guard", "Interceptor",
                "Filter", "Middleware", "Gateway", "Resolver",
            )):
                continue
            class_start = cm.end()

            # Determine class body end: either next class or end of file
            if idx + 1 < len(class_matches):
                class_end = class_matches[idx + 1].start()
            else:
                # Find matching closing brace (simple heuristic: track nesting)
                class_end = _find_closing_brace(content, class_start)

            class_body = content[class_start:class_end]
            fields: list[dict[str, str]] = []

            for fm in _DTO_FIELD_RE.finditer(class_body):
                decorator_block = fm.group(1)
                field_name = fm.group(2)
                field_type = fm.group(3).strip().rstrip(";").strip()

                # Extract decorator names
                decorators = _DECORATOR_NAME_RE.findall(decorator_block)
                decorator_str = ", ".join(decorators)

                fields.append({
                    "name": field_name,
                    "type": field_type,
                    "decorators": decorator_str,
                })

            if fields:
                dto_map[class_name] = fields

    logger.info("Extracted DTO definitions for %d classes", len(dto_map))
    return dto_map


def _find_closing_brace(text: str, start: int) -> int:
    """Find the position of the closing ``}`` that matches the opening at *start*.

    *start* should point just after the opening ``{``.
    """
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return i


# ---------------------------------------------------------------------------
# Prisma parsers
# ---------------------------------------------------------------------------

def extract_prisma_models(project_root: Path) -> list[ModelContract]:
    """Parse ``schema.prisma`` for model definitions and field types.

    Handles Prisma's ``model Foo { ... }`` blocks, extracting field name, type,
    and nullability (indicated by ``?`` suffix on the type).
    """
    models: list[ModelContract] = []
    schema_files = _find_files(project_root, "schema.prisma")
    # Also check nested prisma directories
    schema_files.extend(_find_files(project_root, "*.prisma"))
    schema_files = sorted(set(schema_files))
    # Filter out node_modules to avoid duplicates from generated .prisma client
    schema_files = [f for f in schema_files if "node_modules" not in f.as_posix()]

    for sfile in schema_files:
        content = _safe_read(sfile)
        if not content:
            continue

        for mm in _PRISMA_MODEL_RE.finditer(content):
            model_name = mm.group(1)
            body = mm.group(2)
            fields: list[dict[str, Any]] = []

            for fm in _PRISMA_FIELD_RE.finditer(body):
                fname = fm.group(1)
                ftype = fm.group(2)
                nullable = fm.group(3) is not None
                modifiers = fm.group(4).strip()

                # Skip Prisma directives that look like fields but aren't
                if fname.startswith("@@") or fname.startswith("//"):
                    continue

                fields.append({
                    "name": fname,
                    "type": ftype,
                    "nullable": nullable,
                })

            if fields:
                models.append(ModelContract(name=model_name, fields=fields))

    logger.info("Extracted %d Prisma models", len(models))
    return models


def extract_prisma_enums(project_root: Path) -> list[EnumContract]:
    """Parse ``schema.prisma`` for enum definitions.

    Handles Prisma's ``enum Foo { ... }`` blocks, extracting each enum value.
    """
    enums: list[EnumContract] = []
    schema_files = _find_files(project_root, "schema.prisma")
    schema_files.extend(_find_files(project_root, "*.prisma"))
    schema_files = sorted(set(schema_files))
    # Filter out node_modules to avoid duplicates from generated .prisma client
    schema_files = [f for f in schema_files if "node_modules" not in f.as_posix()]

    for sfile in schema_files:
        content = _safe_read(sfile)
        if not content:
            continue

        for em in _PRISMA_ENUM_RE.finditer(content):
            enum_name = em.group(1)
            body = em.group(2)

            values: list[str] = []
            for line in body.splitlines():
                stripped = line.strip()
                # Skip empty lines and comments
                if not stripped or stripped.startswith("//"):
                    continue
                # The enum value is the first word on the line
                val = stripped.split()[0]
                if val and not val.startswith("@@"):
                    values.append(val)

            if values:
                enums.append(EnumContract(name=enum_name, values=values))

    logger.info("Extracted %d Prisma enums", len(enums))
    return enums


def extract_ts_enums(project_root: Path) -> list[EnumContract]:
    """Scan TypeScript files for ``enum Foo { ... }`` declarations.

    Many NestJS projects define enums in ``.ts`` files rather than (or in
    addition to) ``schema.prisma``.  This parser catches both ``export enum``
    and plain ``enum`` declarations.
    """
    enums: list[EnumContract] = []
    ts_files = _find_files(project_root, "*.ts")

    for tsfile in ts_files:
        posix = tsfile.as_posix()
        if _should_skip(posix, _DEFAULT_TS_SKIP):
            continue

        content = _safe_read(tsfile)
        if not content:
            continue

        for em in _TS_ENUM_RE.finditer(content):
            enum_name = em.group(1)
            body = em.group(2)

            values: list[str] = []
            for line in body.splitlines():
                stripped = line.strip().rstrip(",")
                # Skip empty lines and comments
                if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
                    continue
                # Handle both plain values and assignments:
                #   VALUE,            -> VALUE
                #   VALUE = 'string', -> VALUE
                #   VALUE = 0,        -> VALUE
                val = stripped.split("=")[0].strip().split()[0]
                if val and val.isidentifier():
                    values.append(val)

            if values:
                enums.append(EnumContract(name=enum_name, values=values))

    logger.info("Extracted %d TypeScript enums", len(enums))
    return enums


def extract_isin_enums(project_root: Path) -> list[EnumContract]:
    """Extract functional enums from ``@IsIn([...])`` validators in DTO files.

    Many NestJS projects avoid Prisma enums and instead use
    ``@IsIn(['corrective', 'preventive', 'emergency'])`` decorators in DTOs
    to constrain field values.  These are functionally enums.

    The enum name is derived from the field name that the ``@IsIn`` decorator
    is applied to (e.g. ``type`` -> ``type``, ``trigger_type`` -> ``trigger_type``).
    """
    enums: list[EnumContract] = []
    seen: set[str] = set()  # avoid duplicates by (name, values_tuple)

    # Scan DTO files + controller files (same set as extract_dto_fields)
    dto_files = _find_files(project_root, "*.dto.ts")
    for alt_pattern in ("*request*.ts", "*response*.ts", "*.controller.ts"):
        dto_files.extend(_find_files(project_root, alt_pattern))
    # Also scan entity files — @IsIn can appear anywhere with class-validator
    dto_files.extend(_find_files(project_root, "*.entity.ts"))
    dto_files = sorted(set(dto_files))

    for dfile in dto_files:
        posix = dfile.as_posix()
        if _should_skip(posix, _DEFAULT_TS_SKIP):
            continue

        content = _safe_read(dfile)
        if not content:
            continue

        # Find all @IsIn([...]) occurrences and extract values + field name
        for m in _ISIN_VALIDATOR_RE.finditer(content):
            array_content = m.group(1)
            # Extract string values from the array: 'val' or "val"
            values = re.findall(r"""['"]([^'"]+)['"]""", array_content)
            if not values:
                continue

            # Find the field name this @IsIn is applied to
            # Look at the text starting from the @IsIn match
            remaining = content[m.start():]
            field_match = _ISIN_FIELD_RE.match(remaining)
            field_name = field_match.group(1) if field_match else None

            if not field_name:
                # Fallback: scan forward for the next field-like pattern
                after = content[m.end():]
                fallback = re.match(
                    r"\s*(?:@\w+\([^)]*\)\s*)*(?:readonly\s+)?(\w+)\s*[?!]?\s*:",
                    after,
                )
                field_name = fallback.group(1) if fallback else None

            if not field_name:
                continue

            # Deduplicate by field name + values
            dedup_key = f"{field_name}:{','.join(sorted(values))}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            enums.append(EnumContract(name=field_name, values=values))

    logger.info("Extracted %d @IsIn validator enums", len(enums))
    return enums


# ---------------------------------------------------------------------------
# Naming convention detection
# ---------------------------------------------------------------------------

def detect_naming_convention(
    endpoints: list[EndpointContract],
    models: list[ModelContract],
) -> str:
    """Detect whether the backend uses ``snake_case`` or ``camelCase`` field naming.

    Samples field names from endpoints and models.  Returns ``"snake_case"`` if
    the majority contain underscores, ``"camelCase"`` otherwise.
    """
    snake_count = 0
    camel_count = 0

    # Gather all field name samples
    samples: list[str] = []
    for ep in endpoints:
        for bf in ep.request_body_fields:
            samples.append(bf.get("name", ""))
        for rf in ep.response_fields:
            samples.append(rf.get("name", ""))
        samples.extend(ep.request_params)
    for model in models:
        for f in model.fields:
            samples.append(f.get("name", ""))

    for name in samples:
        if not name:
            continue
        if _SNAKE_CASE_RE.search(name):
            snake_count += 1
        if _CAMEL_CASE_RE.search(name):
            camel_count += 1

    if snake_count > camel_count:
        return "snake_case"
    return "camelCase"


# ---------------------------------------------------------------------------
# Main extraction orchestrator
# ---------------------------------------------------------------------------

def extract_api_contracts(
    project_root: Path,
    milestone_id: str = "",
    skip_dirs: list[str] | None = None,
    paths_filter: list[str] | None = None,
) -> APIContractBundle:
    """Orchestrate all parsers and return a complete :class:`APIContractBundle`.

    This is the primary entry point.  It runs every available parser, merges
    results, detects the naming convention, and returns a single bundle.

    Parameters
    ----------
    project_root:
        Path to the project's root directory.
    milestone_id:
        Optional identifier of the milestone whose code produced this contract.
    skip_dirs:
        Optional list of directory name substrings to skip during scanning.
        When provided, overrides the default skip lists for all parsers.
    paths_filter:
        Optional list of relative or absolute file paths to scope scanning to.
        When provided, only matching files are considered by the parsers.
    """
    global _active_paths_filter, _active_skip_dirs
    # Set module-level override so all parsers use config-provided skip dirs
    if skip_dirs is not None:
        _active_skip_dirs = tuple(skip_dirs)
    else:
        _active_skip_dirs = None

    root = Path(project_root)
    _active_paths_filter = _normalize_paths_filter(root, paths_filter)
    logger.info("Extracting API contracts from %s", root)

    try:
        # --- Endpoints ---
        all_endpoints: list[EndpointContract] = []

        # NestJS
        nestjs_eps = extract_nestjs_endpoints(root)
        all_endpoints.extend(nestjs_eps)

        # Express
        express_eps = extract_express_endpoints(root)
        all_endpoints.extend(express_eps)

        # FastAPI
        fastapi_eps = _extract_fastapi_endpoints(root)
        all_endpoints.extend(fastapi_eps)

        # Django
        django_eps = _extract_django_endpoints(root)
        all_endpoints.extend(django_eps)

        # --- DTO enrichment ---
        dto_map = extract_dto_fields(root)
        _enrich_endpoints_with_dtos(all_endpoints, dto_map)

        # --- Prisma ---
        models = extract_prisma_models(root)
        enums = extract_prisma_enums(root)

        # --- TypeScript enums (supplement Prisma enums) ---
        ts_enums = extract_ts_enums(root)
        # Merge, avoiding duplicates by name
        existing_enum_names = {e.name for e in enums}
        for te in ts_enums:
            if te.name not in existing_enum_names:
                enums.append(te)
                existing_enum_names.add(te.name)

        # --- @IsIn() validator enums (functional enums in DTOs) ---
        isin_enums = extract_isin_enums(root)
        for ie in isin_enums:
            if ie.name not in existing_enum_names:
                enums.append(ie)
                existing_enum_names.add(ie.name)

        # --- Naming convention ---
        convention = detect_naming_convention(all_endpoints, models)

        bundle = APIContractBundle(
            version="1.0",
            extracted_from_milestone=milestone_id,
            endpoints=all_endpoints,
            models=models,
            enums=enums,
            field_naming_convention=convention,
        )

        logger.info(
            "API contract extraction complete: %d endpoints, %d models, %d enums, convention=%s",
            len(bundle.endpoints),
            len(bundle.models),
            len(bundle.enums),
            bundle.field_naming_convention,
        )
        return bundle
    finally:
        # Always reset the module-level override to avoid leaking state
        _active_paths_filter = None
        _active_skip_dirs = None


def _enrich_endpoints_with_dtos(
    endpoints: list[EndpointContract],
    dto_map: dict[str, list[dict[str, str]]],
) -> None:
    """Attempt to match DTO classes to endpoints and populate body/response fields.

    Matching strategies (applied in order of specificity):

    1. **Explicit annotation** — ``@Body() dto: CreateUserDto`` was captured
       during NestJS parsing and stored as a ``__dto_class__`` marker.
       Similarly, ``@Query() query: ListUsersQueryDto`` is stored as a
       ``__query_dto__:ClassName`` entry in ``request_params``.
    2. **Name heuristic** — A DTO named ``CreateFooDto`` is likely the request
       body for a POST on ``/foo``.
    """
    if not dto_map:
        # Even without DTO definitions, clean up annotation markers
        for ep in endpoints:
            _clean_dto_markers(ep)
        return

    for ep in endpoints:
        # --- Strategy 1: explicit @Body() / @Query() annotations ---
        body_dto_name = _pop_body_dto_marker(ep)
        query_dto_name = _pop_query_dto_marker(ep)

        if body_dto_name and body_dto_name in dto_map:
            ep.request_body_fields = [
                {"name": f["name"], "type": f["type"]}
                for f in dto_map[body_dto_name]
            ]

        if query_dto_name and query_dto_name in dto_map:
            # Merge query DTO fields into request_params
            for f in dto_map[query_dto_name]:
                param_name = f["name"]
                if param_name not in ep.request_params:
                    ep.request_params.append(param_name)

        # --- Strategy 2: name-based heuristic (fallback) ---
        handler = ep.handler_name.lower()
        path_segment = ep.path.rstrip("/").rsplit("/", 1)[-1].lower().replace(":", "")

        for dto_name, dto_fields in dto_map.items():
            dto_lower = dto_name.lower()

            # Skip if already matched via explicit annotation
            if dto_name == body_dto_name or dto_name == query_dto_name:
                continue

            # Heuristic: request body DTOs
            is_request_dto = any(
                kw in dto_lower
                for kw in ("create", "update", "input", "request", "payload", "body")
            )
            # Heuristic: response DTOs
            is_response_dto = any(
                kw in dto_lower
                for kw in ("response", "output", "result", "view")
            )

            # Check if DTO name relates to the handler or path segment
            relates_to_endpoint = (
                path_segment and path_segment in dto_lower
            ) or (
                handler and handler in dto_lower
            )

            if not relates_to_endpoint:
                continue

            field_list = [{"name": f["name"], "type": f["type"]} for f in dto_fields]

            if is_request_dto and not ep.request_body_fields:
                ep.request_body_fields = field_list
            elif is_response_dto and not ep.response_fields:
                ep.response_fields = field_list
                if not ep.response_type:
                    ep.response_type = dto_name


def _pop_body_dto_marker(ep: EndpointContract) -> str:
    """Extract and remove the ``__dto_class__`` marker from request_body_fields.

    Returns the DTO class name if found, otherwise empty string.
    """
    if (
        ep.request_body_fields
        and len(ep.request_body_fields) == 1
        and "__dto_class__" in ep.request_body_fields[0]
    ):
        dto_name = ep.request_body_fields[0]["__dto_class__"]
        ep.request_body_fields = []
        return dto_name
    return ""


def _pop_query_dto_marker(ep: EndpointContract) -> str:
    """Extract and remove the ``__query_dto__:ClassName`` marker from request_params.

    Returns the DTO class name if found, otherwise empty string.
    """
    query_dto_name = ""
    cleaned_params: list[str] = []
    for param in ep.request_params:
        if param.startswith("__query_dto__:"):
            query_dto_name = param.split(":", 1)[1]
        else:
            cleaned_params.append(param)
    ep.request_params = cleaned_params
    return query_dto_name


def _clean_dto_markers(ep: EndpointContract) -> None:
    """Remove internal annotation markers without matching against DTOs."""
    _pop_body_dto_marker(ep)
    _pop_query_dto_marker(ep)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def save_api_contracts(bundle: APIContractBundle, output_path: Path) -> None:
    """Save an :class:`APIContractBundle` as JSON.

    Creates parent directories if they do not exist.
    """
    data = _bundle_to_dict(bundle)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved API contracts to %s", output_path)
    except OSError as exc:
        logger.error("Failed to save API contracts to %s: %s", output_path, exc)


def load_api_contracts(path: Path) -> APIContractBundle | None:
    """Load an :class:`APIContractBundle` from a JSON file.

    Returns ``None`` if the file does not exist or cannot be parsed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("API contract file not found: %s", path)
        return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid JSON in API contract file %s: %s", path, exc)
        return None

    return _dict_to_bundle(data)


def _bundle_to_dict(bundle: APIContractBundle) -> dict[str, Any]:
    """Serialize a bundle to a plain dict (for JSON)."""
    return {
        "version": bundle.version,
        "extracted_from_milestone": bundle.extracted_from_milestone,
        "field_naming_convention": bundle.field_naming_convention,
        "endpoints": [asdict(ep) for ep in bundle.endpoints],
        "models": [asdict(m) for m in bundle.models],
        "enums": [asdict(e) for e in bundle.enums],
    }


def _dict_to_bundle(data: dict[str, Any]) -> APIContractBundle:
    """Deserialize a plain dict into an :class:`APIContractBundle`."""
    endpoints = [
        EndpointContract(**ep) for ep in data.get("endpoints", [])
    ]
    models = [
        ModelContract(**m) for m in data.get("models", [])
    ]
    enums = [
        EnumContract(**e) for e in data.get("enums", [])
    ]
    return APIContractBundle(
        version=data.get("version", "1.0"),
        extracted_from_milestone=data.get("extracted_from_milestone", ""),
        endpoints=endpoints,
        models=models,
        enums=enums,
        field_naming_convention=data.get("field_naming_convention", "camelCase"),
    )


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------

def render_api_contracts_for_prompt(
    bundle: APIContractBundle,
    max_chars: int = 15000,
) -> str:
    """Render an :class:`APIContractBundle` as markdown for LLM prompt injection.

    Format:
    - Endpoints grouped by controller file.
    - Each endpoint: ``METHOD /path -> response_type (field1, field2, ...)``.
    - Models listed with their fields.
    - Enums listed with their values.

    Output is truncated at *max_chars* to stay within token budgets.
    """
    lines: list[str] = []

    lines.append("# API Contract")
    if bundle.extracted_from_milestone:
        lines.append(f"**Milestone:** {bundle.extracted_from_milestone}")
    lines.append(f"**Naming:** {bundle.field_naming_convention}")
    lines.append("")

    # --- Endpoints grouped by controller ---
    if bundle.endpoints:
        lines.append("## Endpoints")
        lines.append("")

        # Group by controller_file
        by_controller: dict[str, list[EndpointContract]] = {}
        for ep in bundle.endpoints:
            key = ep.controller_file or "(unknown)"
            by_controller.setdefault(key, []).append(ep)

        for controller, eps in sorted(by_controller.items()):
            lines.append(f"### `{controller}`")
            for ep in eps:
                # Build response info
                resp_info = ""
                if ep.response_type:
                    resp_fields_str = ", ".join(
                        f.get("name", "") for f in ep.response_fields
                    )
                    if resp_fields_str:
                        resp_info = f" -> {ep.response_type} ({resp_fields_str})"
                    else:
                        resp_info = f" -> {ep.response_type}"

                # Build request body info
                body_info = ""
                if ep.request_body_fields:
                    body_fields_str = ", ".join(
                        f"{f.get('name', '')}:{f.get('type', '')}"
                        for f in ep.request_body_fields
                    )
                    body_info = f"  Body: {{{body_fields_str}}}"

                # Build params info
                params_info = ""
                if ep.request_params:
                    params_info = f"  Params: [{', '.join(ep.request_params)}]"

                handler_tag = f" ({ep.handler_name})" if ep.handler_name else ""
                line = f"- `{ep.method} {ep.path}`{handler_tag}{resp_info}"
                lines.append(line)

                if body_info:
                    lines.append(f"  {body_info}")
                if params_info:
                    lines.append(f"  {params_info}")

            lines.append("")

    # --- Models ---
    if bundle.models:
        lines.append("## Models")
        lines.append("")
        for model in bundle.models:
            field_parts = []
            for f in model.fields:
                nullable_marker = "?" if f.get("nullable") else ""
                field_parts.append(f"{f.get('name', '')}: {f.get('type', '')}{nullable_marker}")
            fields_str = ", ".join(field_parts)
            lines.append(f"- **{model.name}**: {{{fields_str}}}")
        lines.append("")

    # --- Enums ---
    if bundle.enums:
        lines.append("## Enums")
        lines.append("")
        for enum in bundle.enums:
            values_str = " | ".join(enum.values)
            lines.append(f"- **{enum.name}**: {values_str}")
        lines.append("")

    # --- Assemble and truncate ---
    result = "\n".join(lines)

    if len(result) > max_chars:
        truncation_msg = f"\n\n... (truncated at {max_chars} chars, {len(bundle.endpoints)} endpoints total)"
        result = result[: max_chars - len(truncation_msg)] + truncation_msg

    return result
