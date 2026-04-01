"""
Integration verifier for frontend-backend API contract matching.

Statically parses frontend API calls and backend route definitions,
then diffs them to find mismatches in endpoints, HTTP methods, field
names, and parameters.  Catches integration bugs during the build
phase rather than at runtime.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skip-directory sets (defaults — can be overridden via config skip_directories)
# ---------------------------------------------------------------------------
FRONTEND_SKIP_DIRS = {"node_modules", ".next", "dist", "build"}
BACKEND_SKIP_DIRS = {"node_modules", "dist", "__pycache__"}
# Combined default used when a single skip set is provided from config
_DEFAULT_SKIP_DIRS = FRONTEND_SKIP_DIRS | BACKEND_SKIP_DIRS

# ---------------------------------------------------------------------------
# Compiled regex patterns -- frontend
# ---------------------------------------------------------------------------

# Matches single quotes, double quotes, or backticks as string delimiters
_Q = r"""['"`]"""       # character class: any JS string delimiter
_NQ = r"""[^'"`]"""     # character class: anything except a string delimiter

# fetch('/api/...', { method: 'POST', ... })
RE_FETCH = re.compile(
    r"fetch\(\s*" + _Q + r"(" + _NQ + r"+)" + _Q
    + r"(?:\s*,\s*\{[^}]*?method\s*:\s*" + _Q + r"(\w+)" + _Q + r"\s*)?",
    re.DOTALL,
)

# api.get('/...'), api.post('/...'), etc.  (custom ApiClient helpers)
# Handles TypeScript generics: api.get<{ data: Asset[] }>('/...')
RE_API_CLIENT = re.compile(
    r"api\.(get|post|put|patch|delete)(?:<[\s\S]*?>)?\s*\(\s*" + _Q + r"(" + _NQ + r"+)" + _Q,
    re.IGNORECASE,
)

# axios.get('/...'), axios.post('/...'), etc.
# Handles TypeScript generics: axios.get<Type>('/...')
RE_AXIOS = re.compile(
    r"axios\.(get|post|put|patch|delete)(?:<[\s\S]*?>)?\s*\(\s*" + _Q + r"(" + _NQ + r"+)" + _Q,
    re.IGNORECASE,
)

# useQuery(['key'], () => fetch/api/axios...)  --  capture the URL inside
# Handles TypeScript generics on both the hook and the inner call
RE_USE_QUERY = re.compile(
    r"useQuery\s*(?:<[\s\S]*?>)?\s*\(\s*\[?\s*" + _Q + r"(" + _NQ + r"*)" + _Q
    + r"[\s\S]*?(?:fetch|api\.\w+(?:<[\s\S]*?>)?|axios\.\w+(?:<[\s\S]*?>)?)\s*\(\s*"
    + _Q + r"(" + _NQ + r"+)" + _Q,
    re.DOTALL,
)

# useMutation(... fetch/api/axios...)
# Handles TypeScript generics on both the hook and the inner call
RE_USE_MUTATION = re.compile(
    r"useMutation\s*(?:<[\s\S]*?>)?\s*\([\s\S]*?(?:fetch|api\.(\w+)(?:<[\s\S]*?>)?|axios\.(\w+)(?:<[\s\S]*?>)?)\s*\(\s*"
    + _Q + r"(" + _NQ + r"+)" + _Q,
    re.DOTALL,
)

# Request body field names: { fieldName: ..., field_name: ... }
RE_BODY_FIELDS = re.compile(
    r"(?:body|data)\s*:\s*\{([^}]*)\}",
    re.DOTALL,
)

# Individual field key inside an object literal
RE_FIELD_KEY = re.compile(r"(\w+)\s*:")

# Response field access: data.fieldName, response.fieldName, result.field_name
RE_RESPONSE_FIELD = re.compile(
    r"(?:data|response|result|res)\.(\w+)",
)

# fetch method inside options object (standalone, for second-pass)
RE_FETCH_METHOD = re.compile(
    r"method\s*:\s*" + _Q + r"(\w+)" + _Q,
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Compiled regex patterns -- backend
# ---------------------------------------------------------------------------

# Matches single or double quote (no backtick for decorators / Python)
_PQ = r"""['"]"""       # Python/decorator quote
_NPQ = r"""[^'"]"""     # non-quote for Python/decorator strings

# NestJS decorators: @Get('/path'), @Post('/path'), @Get(), etc.
# The quoted path argument is optional so we also match @Get() with no argument,
# which maps to the controller's base path.
RE_NESTJS_DECORATOR = re.compile(
    r"@(Get|Post|Put|Patch|Delete)\(\s*(?:"
    + _PQ + r"(" + _NPQ + r"*)" + _PQ + r"?\s*)?\)",
    re.IGNORECASE,
)

# NestJS @Controller('/prefix')
RE_NESTJS_CONTROLLER = re.compile(
    r"@Controller\(\s*" + _PQ + r"(" + _NPQ + r"*)" + _PQ + r"?\s*\)",
)

# Express: router.get('/path', ...) or app.get('/path', ...)
RE_EXPRESS = re.compile(
    r"(?:router|app)\.(get|post|put|patch|delete)\(\s*" + _Q + r"(" + _NQ + r"+)" + _Q,
    re.IGNORECASE,
)

# FastAPI: @app.get('/path'), @router.get('/path')
RE_FASTAPI = re.compile(
    r"@(?:app|router)\.(get|post|put|patch|delete)\(\s*" + _PQ + r"(" + _NPQ + r"+)" + _PQ,
    re.IGNORECASE,
)

# Django: path('route/', view, name=...) or url(r'^route/$', view, ...)
RE_DJANGO = re.compile(
    r"(?:path|url)\(\s*r?" + _PQ + r"(" + _NPQ + r"+)" + _PQ,
)

# Handler/function name following a route definition
RE_HANDLER_NAME = re.compile(
    r"(?:def|function|async\s+function|const|let|var)\s+(\w+)",
)

# NestJS @Query('paramName', ...) decorator — extracts named query parameters
# Matches: @Query('page'), @Query("status"), @Query('page', new DefaultValuePipe(1), ParseIntPipe)
RE_NESTJS_QUERY_PARAM = re.compile(
    r"@Query\(\s*" + _PQ + r"(\w+)" + _PQ + r"[^)]*\)",
)

# NestJS @Query() with DTO type (no param name) — e.g., @Query() query: ListWorkOrdersDto
# Group 1 = the DTO type name
RE_NESTJS_QUERY_DTO = re.compile(
    r"@Query\(\s*\)\s*\w+\s*:\s*(\w+)",
)

# NestJS @Param('paramName', ...) decorator — extracts named path parameters
# Matches: @Param('id'), @Param("buildingId"), @Param('id', ParseIntPipe)
RE_NESTJS_PARAM = re.compile(
    r"@Param\(\s*" + _PQ + r"(\w+)" + _PQ + r"[^)]*\)",
)

# NestJS @UseGuards(Guard1, Guard2) — extracts guard class names
# Matches: @UseGuards(JwtAuthGuard), @UseGuards(JwtAuthGuard, RolesGuard)
RE_NESTJS_USE_GUARDS = re.compile(
    r"@UseGuards\(([^)]+)\)",
)

# NestJS @Roles('role1', 'role2') — extracts role names
# Matches: @Roles('admin'), @Roles('tenant_admin', 'facility_manager')
RE_NESTJS_ROLES = re.compile(
    r"@Roles\(([^)]+)\)",
)

# NestJS @ApiResponse({ status: 200, description: '...' })
# Captures the description string
RE_NESTJS_API_RESPONSE = re.compile(
    r"@Api(?:Ok)?Response\(\s*\{[^}]*description\s*:\s*" + _PQ + r"(" + _NPQ + r"*)" + _PQ,
)

# DTO class field: captures field names from class properties
# Matches: fieldName: type, fieldName?: type, @IsOptional() fieldName: type
RE_DTO_FIELD = re.compile(
    r"(?:^|\n)\s*(?:@\w+\([^)]*\)\s*)*(\w+)\??\s*:\s*\w+",
)

# Query parameter names from URL strings: ?key=value&key2=value2
# Captures parameter names (the part before '=') from query strings
RE_QUERY_PARAM_NAME = re.compile(
    r"[?&]([a-zA-Z_]\w*)\s*=",
)

# Match params object: api.get('/path', { params: { key1, key2, key3 } })
# Group 1 = URL path, Group 2 = inner content of the params object.
# Handles TypeScript generics, optional chaining, and multiline objects.
RE_PARAMS_OBJECT = re.compile(
    r"(?:api|axios)\.\w+(?:<[\s\S]*?>)?\s*\(\s*" + _Q + r"([^'\"` ]*)" + _Q
    + r"\s*,\s*\{[^}]*params\s*:\s*\{([^}]+)\}",
    re.DOTALL,
)

# Match params shorthand: api.get('/path', { params })
# Catches the ES6 shorthand pattern where params is a variable reference,
# NOT an inline object literal.  Group 1 = URL path.
RE_PARAMS_SHORTHAND = re.compile(
    r"(?:api|axios)\.\w+(?:<[\s\S]*?>)?\s*\(\s*" + _Q + r"([^'\"` ]*)" + _Q
    + r"\s*,\s*\{\s*params\s*\}",
    re.DOTALL,
)

# Variable-built params: const params = { page, limit: 20 } or
# const params: Record<...> = { page, limit: 20 }
# Group 1 = inner content of the initializer object literal.
RE_PARAMS_VAR_INIT = re.compile(
    r"(?:const|let|var)\s+params\s*(?::\s*[^=]+)?\s*=\s*\{([^}]*)\}",
    re.DOTALL,
)

# Dynamic param assignment: params.key = value or params['key'] = value
# Group 1 = the key name (dot access), Group 2 = the key name (bracket access).
RE_PARAMS_DOT_ASSIGN = re.compile(
    r"params\.([a-zA-Z_]\w*)\s*=",
)

RE_PARAMS_BRACKET_ASSIGN = re.compile(
    r"params\[" + _Q + r"([a-zA-Z_]\w*)" + _Q + r"\]\s*=",
)

# URLSearchParams: params.append('key', ...) or params.set('key', ...)
# Also matches searchParams and query as common variable names.
RE_URL_SEARCH_PARAMS = re.compile(
    r"(?:params|searchParams|query)\.(?:append|set)\(\s*" + _Q + r"(\w+)" + _Q,
)

# Frontend camelCase field access on any variable (broad matching).
# e.g., res.buildingId, data.slaCompliance, wo?.buildingId, asset.vendorId
# Matches any word-character variable name with optional chaining, then
# captures the camelCase property access.  Known non-API objects (Math,
# console, document, window, etc.) are filtered out at match time.
RE_FRONTEND_CAMEL_FIELD = re.compile(
    r"(\w+)\??\."
    r"([a-z][a-zA-Z]+[A-Z]\w*)",
)

# Variable prefixes to exclude from camelCase field detection — these are
# standard JS/TS built-in objects, not API response data.
_CAMEL_FIELD_EXCLUDE_PREFIXES = frozenset({
    # Built-in objects
    "Math", "JSON", "Object", "Array", "String", "Number", "Date", "Promise",
    "RegExp", "Map", "Set", "WeakMap", "WeakSet", "Symbol", "Proxy", "Reflect",
    "Error", "TypeError", "RangeError", "SyntaxError",
    # Browser/DOM APIs
    "console", "document", "window", "navigator", "localStorage",
    "sessionStorage", "location", "history", "screen", "performance",
    "crypto", "fetch", "XMLHttpRequest", "WebSocket", "URL",
    # Node built-ins
    "process", "Buffer", "fs", "path", "os", "http", "https", "child_process",
    # React/Next.js
    "React", "ReactDOM", "useRef", "useState", "useEffect", "useCallback",
    "useMemo", "useContext", "useReducer", "useLayoutEffect",
    "router", "Router", "NextResponse", "NextRequest",
    # Common framework objects that aren't API data
    "event", "evt", "e", "err", "error", "ctx", "context", "req", "request",
    "config", "options", "props", "state", "theme", "styles", "css",
    "module", "exports", "require", "import",
    # TypeScript utility
    "keyof", "typeof", "Partial", "Required", "Readonly", "Pick", "Omit",
    "this", "self", "super",
})

# Destructuring camelCase fields from API response objects
# e.g., const { buildingId, slaCompliance } = response;
#        const { buildingId } = res.data;
#        const { buildingId, ...rest } = await api.get(...);
# Captures the inner content of the destructuring braces.
RE_DESTRUCTURE_RESPONSE = re.compile(
    r"(?:const|let|var)\s+\{([^}]+)\}\s*=\s*"
    r"(?:(?:await\s+)?(?:res|data|response|result|api\.\w+)"
    r"|(?:\w+\.data))",
)

# Backend snake_case field definitions in Prisma schema, DTOs, models
RE_BACKEND_SNAKE_FIELD = re.compile(
    r"(?:^|\s)([a-z]+(?:_[a-z]+)+)\s",
)

# Defensive response shape patterns indicating wrapping inconsistency
RE_RESPONSE_SHAPE_DEFENSIVE = re.compile(
    r"(?:"
    r"Array\.isArray\(\s*(\w+)\s*\)\s*\?\s*\1\s*:\s*\1\.data"
    r"|Array\.isArray\(\s*(\w+)\s*\)\s*\?\s*\2\s*:\s*\2\[" + _Q + r"data" + _Q + r"\]"
    r"|(\w+)\.data\s*\|\|\s*\3"
    r"|(\w+)\?\.data\s*\?\?\s*\4"
    r"|(\w+)\.data\s*\?\s*\5\.data\s*:\s*\5"
    r")",
)

# Response fields in backend: res.json({ field: ... }), return { field: ... }
RE_RESPONSE_OBJECT = re.compile(
    r"(?:res\.json|return\s+Response|return\s+JsonResponse|return)\s*\(\s*\{([^}]*)\}",
    re.DOTALL,
)

# Accepted params: req.body.field, req.query.field, req.params.field
RE_REQ_FIELDS = re.compile(
    r"req(?:uest)?\.(?:body|query|params)\.(\w+)",
)

# FastAPI/Django param names from function signature
RE_FUNC_PARAMS = re.compile(
    r"def\s+\w+\s*\(([^)]*)\)",
)

# ---------------------------------------------------------------------------
# Compiled regex patterns -- Prisma schema & query detection
# ---------------------------------------------------------------------------

# Matches model declarations: model WorkOrder {
RE_PRISMA_MODEL_DECL = re.compile(r"^model\s+(\w+)\s*\{", re.MULTILINE)

# Matches relation fields WITH fields: clause (forward FK relations only)
# e.g.:  category  MaintenanceCategory?  @relation(fields: [category_id], references: [id])
#        tenant    Tenant                @relation(fields: [tenant_id], references: [id])
# Group 1: relation name, Group 2: related model type, Group 3: FK field name
RE_PRISMA_RELATION_FIELD = re.compile(
    r"^\s+(\w+)\s+(\w+)\??\s+@relation\([^)]*fields:\s*\[(\w+)\]",
    re.MULTILINE,
)

# Matches Prisma query calls in backend service files:
# e.g., this.prisma.workOrder.findMany(
#        prisma.asset.findFirst(
# Group 1: model accessor (camelCase), Group 2: query method
RE_PRISMA_QUERY_CALL = re.compile(
    r"(?:this\.)?prisma\.(\w+)\."
    r"(findMany|findUnique|findFirst|findFirstOrThrow|findUniqueOrThrow)\s*\(",
)

# Matches top-level relation names inside an include object:
# e.g., include: { category: true, priority: true }
# Group 1: relation name
RE_PRISMA_INCLUDE_KEY = re.compile(r"(\w+)\s*:\s*(?:true|\{)")

# Relations to skip — these are almost never displayed in the UI
_PRISMA_SKIP_RELATIONS = frozenset({
    "tenant",       # always used for filtering, not display
})

# FK fields to skip — tenant_id is a filter, not a display field
_PRISMA_SKIP_FK_FIELDS = frozenset({
    "tenant_id",
})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FrontendAPICall:
    """A single API call found in frontend source code."""
    file_path: str
    line_number: int
    endpoint_path: str
    http_method: str
    request_fields: list[str] = field(default_factory=list)
    expected_response_fields: list[str] = field(default_factory=list)
    query_params: list[str] = field(default_factory=list)


@dataclass
class BackendEndpoint:
    """A single endpoint defined in backend source code."""
    file_path: str
    route_path: str
    http_method: str
    handler_name: str
    accepted_params: list[str] = field(default_factory=list)
    response_fields: list[str] = field(default_factory=list)
    guards: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    api_response_desc: str = ""


@dataclass
class IntegrationMismatch:
    """A single mismatch between frontend and backend."""
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    category: str
    frontend_file: str
    backend_file: str
    description: str
    suggestion: str


@dataclass
class IntegrationReport:
    """Full report produced by the integration verifier."""
    total_frontend_calls: int
    total_backend_endpoints: int
    matched: int
    mismatches: list[IntegrationMismatch] = field(default_factory=list)
    missing_endpoints: list[str] = field(default_factory=list)
    unused_endpoints: list[str] = field(default_factory=list)
    field_name_mismatches: list[IntegrationMismatch] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Case-conversion helpers
# ---------------------------------------------------------------------------

def _snake_to_camel(name: str) -> str:
    """Convert a snake_case name to camelCase.

    >>> _snake_to_camel('building_id')
    'buildingId'
    """
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _camel_to_snake(name: str) -> str:
    """Convert a camelCase name to snake_case.

    >>> _camel_to_snake('buildingId')
    'building_id'
    """
    result = re.sub(r"([A-Z])", r"_\1", name)
    return result.lower().lstrip("_")


def _fields_equivalent(a: str, b: str) -> bool:
    """Return True if two field names refer to the same thing modulo case style."""
    if a == b:
        return True
    return _snake_to_camel(a) == b or _snake_to_camel(b) == a


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------

def normalize_path(path: str) -> str:
    """Normalize an endpoint path for comparison.

    * Strips trailing slashes (but preserves the leading one).
    * Replaces **all** parameter placeholders with a single canonical
      token ``:param`` so that every parameterised segment compares
      equal regardless of original syntax:

      - Express   ``:id``              -> ``:param``
      - Braced    ``{id}``             -> ``:param``
      - Template  ``${userId}``        -> ``:param``
      - Dotted    ``${editCategory.id}`` -> ``:param``
      - Escaped   ``\\${x}``           -> ``:param``

    * Lowercases the path.
    * Collapses duplicate slashes.
    * Strips query strings.

    >>> normalize_path('/api/v1/users/:userId/')
    '/api/v1/users/:param'
    >>> normalize_path('/api/v1/users/${userId}')
    '/api/v1/users/:param'
    >>> normalize_path('/roles/${roleId}/permissions')
    '/roles/:param/permissions'
    >>> normalize_path('/roles/:id/permissions')
    '/roles/:param/permissions'
    """
    # Strip trailing slash (keep leading)
    path = path.rstrip("/") or "/"

    # Collapse duplicate slashes
    path = re.sub(r"/+", "/", path)

    # Strip query string before normalizing (query params handled separately)
    path = path.split("?")[0]

    # --- Normalise ALL parameter forms to the canonical token :param ---

    # Escaped template literal \${...} (sometimes appears in source)
    path = re.sub(r"\\\$\{[^}]+\}", ":param", path)

    # Template literal ${expr.member} or ${expr} (dotted / complex expressions)
    # Must come before the simple ${id} rule so we don't leave partial matches.
    path = re.sub(r"\$\{[^}]+\}", ":param", path)

    # Already-braced {id} / {userId} (OpenAPI / NestJS style)
    path = re.sub(r"\{[^}]+\}", ":param", path)

    # Express-style :someParam  (word characters after a colon that is preceded
    # by a slash or sits at the start).  Skip if already ``:param``.
    path = re.sub(r":(?!param(?:/|$))\w+", ":param", path)

    return path.lower()


def _strip_api_prefix(path: str) -> str:
    """Strip common API prefixes for matching.

    Many projects serve all routes under ``/api/v1/…`` (or ``/api/…``),
    but the frontend may omit the prefix because an Axios base-URL or a
    NestJS global prefix handles it transparently.  By indexing the
    stripped form as well we can still match.

    >>> _strip_api_prefix('/api/v1/users/:param')
    '/users/:param'
    >>> _strip_api_prefix('/users/:param')
    '/users/:param'
    """
    for prefix in ("/api/v1/", "/api/v2/", "/api/"):
        if path.startswith(prefix):
            return "/" + path[len(prefix):]
    return path


# ---------------------------------------------------------------------------
# File-walking helpers
# ---------------------------------------------------------------------------

def _iter_files(root: Path, extensions: set[str], skip_dirs: set[str]):
    """Yield Path objects for files matching *extensions* under *root*,
    skipping directories in *skip_dirs*."""
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_dir():
            if child.name in skip_dirs or child.name.startswith("."):
                continue
            yield from _iter_files(child, extensions, skip_dirs)
        elif child.suffix in extensions:
            yield child


def _read_file(path: Path) -> str | None:
    """Read a file's content, returning None on error."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not read %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Frontend context helpers
# ---------------------------------------------------------------------------

def _extract_body_fields(text: str, start: int, window: int = 500) -> list[str]:
    """Extract request-body field names from *text* near position *start*."""
    snippet = text[start: start + window]
    m = RE_BODY_FIELDS.search(snippet)
    if not m:
        return []
    return RE_FIELD_KEY.findall(m.group(1))


def _extract_response_fields(text: str, start: int, window: int = 800) -> list[str]:
    """Extract response field names accessed near position *start*."""
    snippet = text[start: start + window]
    return list(dict.fromkeys(RE_RESPONSE_FIELD.findall(snippet)))


def _line_number(text: str, pos: int) -> int:
    """Return the 1-based line number for character position *pos* in *text*."""
    return text.count("\n", 0, pos) + 1


def _extract_query_params(url_string: str) -> list[str]:
    """Extract query parameter names from a URL string.

    Handles both literal query params and template-literal interpolated URLs.
    For example::

        /work-orders?status=${status}&priority=${priority}

    Returns ``['status', 'priority']``.

    Also handles plain query strings like ``?page=1&limit=10``.

    Args:
        url_string: The URL or URL template string.

    Returns:
        A deduplicated list of query parameter names.
    """
    # Find the query string portion
    qmark = url_string.find("?")
    if qmark == -1:
        return []

    query_part = url_string[qmark:]
    return list(dict.fromkeys(RE_QUERY_PARAM_NAME.findall(query_part)))


def _parse_params_object_keys(params_inner: str) -> list[str]:
    """Extract parameter names from the inner content of a ``{ params: { ... } }`` object.

    Handles both shorthand property syntax (``{ key1, key2 }``) and
    explicit key-value syntax (``{ key1: value1, key2: value2 }``).

    For example::

        'status, priority, buildingId, page, limit'
        => ['status', 'priority', 'buildingId', 'page', 'limit']

        'status: selectedStatus, building: buildingId'
        => ['status', 'building']

    Args:
        params_inner: The text inside the params braces (without the braces).

    Returns:
        A deduplicated list of parameter key names.
    """
    keys: list[str] = []
    # Split on commas, then extract the key from each segment
    for segment in params_inner.split(","):
        segment = segment.strip()
        if not segment:
            continue
        # If there's a colon, the key is the part before it (explicit key: value)
        if ":" in segment:
            key = segment.split(":")[0].strip()
        else:
            # Shorthand property: just the variable name
            # Remove spread operator if present (e.g., ...filters)
            if segment.startswith("..."):
                continue
            key = segment.strip()
        # Validate it looks like an identifier
        if key and re.match(r"^[a-zA-Z_]\w*$", key):
            keys.append(key)
    return list(dict.fromkeys(keys))


def _extract_variable_params(content: str, api_call_pos: int) -> list[str]:
    """Extract query param keys from a variable-built ``params`` object.

    Handles the dominant real-world pattern where params are built in a
    variable then passed via ES6 shorthand::

        const params: Record<string, string | number> = { page, limit: 20 };
        if (statusFilter) params.status = statusFilter;
        if (priorityFilter) params.priority = priorityFilter;
        const res = await api.get('/work-orders', { params });

    Looks backward from *api_call_pos* for a ``const params = { ... }``
    declaration, then collects both the initializer keys and any
    ``params.key = value`` assignments between the declaration and the
    API call.

    Args:
        content: Full file content.
        api_call_pos: Character position of the API call in the file.

    Returns:
        A deduplicated list of parameter key names.
    """
    # Search backward from the API call (up to 2000 chars) for the params
    # variable declaration.
    search_start = max(0, api_call_pos - 2000)
    preceding = content[search_start:api_call_pos]

    init_match = None
    # Find the LAST params variable declaration before the API call
    for m in RE_PARAMS_VAR_INIT.finditer(preceding):
        init_match = m

    keys: list[str] = []
    if init_match:
        # Extract keys from the initializer: { page, limit: 20, ... }
        keys.extend(_parse_params_object_keys(init_match.group(1)))
        # Search between the declaration and the API call for dot assignments
        between = preceding[init_match.end():]
    else:
        # No initializer found -- still check for dot assignments in the
        # preceding 500 chars (the variable may have been declared earlier).
        between = preceding[-500:]

    # Collect params.key = ... assignments
    for dm in RE_PARAMS_DOT_ASSIGN.finditer(between):
        key = dm.group(1)
        if key not in keys:
            keys.append(key)

    # Collect params['key'] = ... assignments
    for bm in RE_PARAMS_BRACKET_ASSIGN.finditer(between):
        key = bm.group(1)
        if key not in keys:
            keys.append(key)

    return list(dict.fromkeys(keys))


# ---------------------------------------------------------------------------
# Frontend scanner
# ---------------------------------------------------------------------------

def scan_frontend_api_calls(
    project_root: Path,
    skip_dirs: set[str] | None = None,
) -> list[FrontendAPICall]:
    """Scan frontend source files for API calls.

    Looks for ``fetch``, ``axios``, custom ``api.*`` helpers, and
    React Query hooks (``useQuery`` / ``useMutation``).

    Args:
        project_root: Root directory of the project.
        skip_dirs: Optional set of directory names to skip.
            Defaults to :data:`FRONTEND_SKIP_DIRS`.

    Returns:
        A list of ``FrontendAPICall`` instances found.
    """
    calls: list[FrontendAPICall] = []
    extensions = {".ts", ".tsx", ".js", ".jsx"}
    _skip = skip_dirs if skip_dirs is not None else FRONTEND_SKIP_DIRS

    for fpath in _iter_files(project_root, extensions, _skip):
        content = _read_file(fpath)
        if content is None:
            continue

        rel = str(fpath)

        # --- fetch() ---
        for m in RE_FETCH.finditer(content):
            url = m.group(1)
            method = (m.group(2) or "GET").upper()
            # If method wasn't captured in the regex, scan nearby text
            if m.group(2) is None:
                nearby = content[m.start(): m.start() + 400]
                method_match = RE_FETCH_METHOD.search(nearby)
                if method_match:
                    method = method_match.group(1).upper()
            pos = m.start()
            calls.append(FrontendAPICall(
                file_path=rel,
                line_number=_line_number(content, pos),
                endpoint_path=url,
                http_method=method,
                request_fields=_extract_body_fields(content, pos),
                expected_response_fields=_extract_response_fields(content, pos),
                query_params=_extract_query_params(url),
            ))

        # --- api.get/post/... ---
        for m in RE_API_CLIENT.finditer(content):
            method = m.group(1).upper()
            url = m.group(2)
            pos = m.start()
            calls.append(FrontendAPICall(
                file_path=rel,
                line_number=_line_number(content, pos),
                endpoint_path=url,
                http_method=method,
                request_fields=_extract_body_fields(content, pos),
                expected_response_fields=_extract_response_fields(content, pos),
                query_params=_extract_query_params(url),
            ))

        # --- axios.get/post/... ---
        for m in RE_AXIOS.finditer(content):
            method = m.group(1).upper()
            url = m.group(2)
            pos = m.start()
            calls.append(FrontendAPICall(
                file_path=rel,
                line_number=_line_number(content, pos),
                endpoint_path=url,
                http_method=method,
                request_fields=_extract_body_fields(content, pos),
                expected_response_fields=_extract_response_fields(content, pos),
                query_params=_extract_query_params(url),
            ))

        # --- useQuery ---
        for m in RE_USE_QUERY.finditer(content):
            url = m.group(2)
            pos = m.start()
            calls.append(FrontendAPICall(
                file_path=rel,
                line_number=_line_number(content, pos),
                endpoint_path=url,
                http_method="GET",
                request_fields=[],
                expected_response_fields=_extract_response_fields(content, pos),
                query_params=_extract_query_params(url),
            ))

        # --- useMutation ---
        for m in RE_USE_MUTATION.finditer(content):
            api_method = m.group(1) or m.group(2) or "post"
            url = m.group(3)
            pos = m.start()
            calls.append(FrontendAPICall(
                file_path=rel,
                line_number=_line_number(content, pos),
                endpoint_path=url,
                http_method=api_method.upper(),
                request_fields=_extract_body_fields(content, pos),
                expected_response_fields=_extract_response_fields(content, pos),
                query_params=_extract_query_params(url),
            ))

        # --- Second pass: params object pattern ---
        # e.g., api.get('/work-orders', { params: { status, priority, buildingId } })
        # Build a lookup from (file, normalized_url) to calls for merging
        file_calls_by_path: dict[str, list[FrontendAPICall]] = {}
        for c in calls:
            if c.file_path == rel:
                norm = normalize_path(c.endpoint_path)
                file_calls_by_path.setdefault(norm, []).append(c)

        for m in RE_PARAMS_OBJECT.finditer(content):
            url_path = m.group(1)
            params_inner = m.group(2)
            param_keys = _parse_params_object_keys(params_inner)
            if not param_keys:
                continue

            norm_url = normalize_path(url_path)
            matching_calls = file_calls_by_path.get(norm_url, [])

            if matching_calls:
                # Merge params into existing call(s) that match the URL
                for c in matching_calls:
                    existing = set(c.query_params)
                    for key in param_keys:
                        if key not in existing:
                            c.query_params.append(key)
            else:
                # No existing call matched -- create a new one from the
                # params-object match (the URL may have been missed by
                # the primary regex scan).
                pos = m.start()
                calls.append(FrontendAPICall(
                    file_path=rel,
                    line_number=_line_number(content, pos),
                    endpoint_path=url_path,
                    http_method="GET",
                    request_fields=[],
                    expected_response_fields=[],
                    query_params=param_keys,
                ))

        # --- Third pass: URLSearchParams pattern ---
        # e.g., params.append('category', selectedCategory);
        # Collect all URLSearchParams keys in this file, then associate
        # them with the nearest preceding API call.
        url_search_matches = list(RE_URL_SEARCH_PARAMS.finditer(content))
        if url_search_matches:
            # Collect the calls from this file sorted by position
            file_calls_sorted = sorted(
                [c for c in calls if c.file_path == rel],
                key=lambda c: c.line_number,
            )
            if file_calls_sorted:
                # Group URLSearchParams keys and associate with the
                # nearest API call (by line proximity).
                for sm in url_search_matches:
                    param_name = sm.group(1)
                    param_line = _line_number(content, sm.start())
                    # Find the closest API call (prefer the one just before)
                    best_call = file_calls_sorted[0]
                    best_dist = abs(param_line - best_call.line_number)
                    for c in file_calls_sorted:
                        dist = abs(param_line - c.line_number)
                        if dist < best_dist:
                            best_dist = dist
                            best_call = c
                    if param_name not in best_call.query_params:
                        best_call.query_params.append(param_name)

        # --- Fourth pass: variable-reference params shorthand ---
        # e.g., const params = { page, limit }; params.status = x; api.get('/path', { params })
        # Rebuild the file_calls_by_path lookup in case new calls were added
        file_calls_by_path2: dict[str, list[FrontendAPICall]] = {}
        for c in calls:
            if c.file_path == rel:
                norm = normalize_path(c.endpoint_path)
                file_calls_by_path2.setdefault(norm, []).append(c)

        for m in RE_PARAMS_SHORTHAND.finditer(content):
            url_path = m.group(1)
            param_keys = _extract_variable_params(content, m.start())
            if not param_keys:
                continue

            norm_url = normalize_path(url_path)
            matching_calls = file_calls_by_path2.get(norm_url, [])

            if matching_calls:
                for c in matching_calls:
                    existing = set(c.query_params)
                    for key in param_keys:
                        if key not in existing:
                            c.query_params.append(key)
            else:
                pos = m.start()
                calls.append(FrontendAPICall(
                    file_path=rel,
                    line_number=_line_number(content, pos),
                    endpoint_path=url_path,
                    http_method="GET",
                    request_fields=[],
                    expected_response_fields=[],
                    query_params=param_keys,
                ))

    logger.info("Scanned frontend: found %d API calls", len(calls))
    return calls


# ---------------------------------------------------------------------------
# Backend scanner
# ---------------------------------------------------------------------------

def _extract_dto_fields_from_content(content: str, dto_name: str) -> list[str]:
    """Extract field names from a DTO class definition within file content.

    Args:
        content: The file content to search in.
        dto_name: Name of the DTO class to find (e.g., ``ListWorkOrdersDto``).

    Returns:
        A list of field names from the DTO class, or empty list if not found.
    """
    # Look for `class DtoName {` or `export class DtoName {`
    # Use a balanced approach: find the class opening, then find its closing brace
    class_start_pattern = re.compile(
        r"(?:export\s+)?class\s+" + re.escape(dto_name) + r"\s*(?:extends\s+\w+\s*)?(?:implements\s+\w+\s*)?\{",
        re.DOTALL,
    )
    cm = class_start_pattern.search(content)
    if not cm:
        return []

    # Find the matching closing brace (handle nested braces)
    start = cm.end()
    depth = 1
    pos = start
    while pos < len(content) and depth > 0:
        if content[pos] == "{":
            depth += 1
        elif content[pos] == "}":
            depth -= 1
        pos += 1

    class_body = content[start:pos - 1] if depth == 0 else content[start:start + 3000]

    fields: list[str] = []
    for fm in RE_DTO_FIELD.finditer(class_body):
        field_name = fm.group(1)
        # Skip decorators, class keywords, and common non-field names
        if field_name in ("class", "export", "import", "constructor", "static",
                          "private", "protected", "public", "readonly", "abstract",
                          "return", "this", "super", "new", "if", "else", "for",
                          "while", "switch", "case", "break", "continue", "throw",
                          "try", "catch", "finally", "async", "await", "function"):
            continue
        if field_name.startswith("@"):
            continue
        fields.append(field_name)
    return list(dict.fromkeys(fields))


def _extract_dto_fields(
    project_root: Path, dto_name: str, current_file_content: str | None = None
) -> list[str]:
    """Extract field names from a NestJS DTO class definition.

    First checks the current file content (for inline DTOs), then searches
    DTO/model files under *project_root*.

    Args:
        project_root: Root directory of the project.
        dto_name: Name of the DTO class to find (e.g., ``ListWorkOrdersDto``).
        current_file_content: Content of the file where the DTO reference was
            found (checked first for inline DTO definitions).

    Returns:
        A list of field names from the DTO class.
    """
    # First check the current file (DTOs are often inline in NestJS controllers)
    if current_file_content:
        fields = _extract_dto_fields_from_content(current_file_content, dto_name)
        if fields:
            return fields

    extensions = {".ts", ".js"}
    # Common DTO locations
    dto_indicators = {"dto", "dtos", "model", "models", "types", "schemas"}
    # Also check for files whose name matches the dto name pattern
    dto_snake = _camel_to_snake(dto_name).replace("_", "-")

    for fpath in _iter_files(project_root, extensions, BACKEND_SKIP_DIRS):
        # Prioritize files likely to contain DTOs
        parts_lower = {p.lower() for p in fpath.parts}
        fname_lower = fpath.name.lower()
        is_dto_location = bool(parts_lower & dto_indicators)
        is_dto_file = any(kw in fname_lower for kw in (
            "dto", "model", "type", "schema", "controller",
        ))
        is_name_match = dto_snake in fname_lower

        if not (is_dto_location or is_dto_file or is_name_match):
            continue

        content = _read_file(fpath)
        if content is None:
            continue

        fields = _extract_dto_fields_from_content(content, dto_name)
        if fields:
            return fields

    return []


def scan_backend_endpoints(
    project_root: Path,
    skip_dirs: set[str] | None = None,
) -> list[BackendEndpoint]:
    """Scan backend source files for endpoint definitions.

    Supports NestJS (decorators), Express (``router.*``/``app.*``),
    FastAPI (``@app.*``/``@router.*``), and Django (``path``/``url``).

    Args:
        project_root: Root directory of the project.
        skip_dirs: Optional set of directory names to skip.
            Defaults to :data:`BACKEND_SKIP_DIRS`.

    Returns:
        A list of ``BackendEndpoint`` instances found.
    """
    endpoints: list[BackendEndpoint] = []
    extensions = {".ts", ".tsx", ".js", ".jsx", ".py"}
    # Cache DTO lookups to avoid repeated file scans
    _dto_cache: dict[str, list[str]] = {}
    _skip = skip_dirs if skip_dirs is not None else BACKEND_SKIP_DIRS

    for fpath in _iter_files(project_root, extensions, _skip):
        content = _read_file(fpath)
        if content is None:
            continue

        rel = str(fpath)

        # ---- NestJS ----
        controller_prefix = ""
        ctrl_m = RE_NESTJS_CONTROLLER.search(content)
        if ctrl_m:
            controller_prefix = ctrl_m.group(1).strip("/")

        # Extract class-level @UseGuards and @Roles (apply to all methods)
        class_guards: list[str] = []
        class_roles: list[str] = []
        try:
            first_method_pos = len(content)
            for dm in RE_NESTJS_DECORATOR.finditer(content):
                first_method_pos = dm.start()
                break
            ctrl_area = content[:first_method_pos]
            for gm in RE_NESTJS_USE_GUARDS.finditer(ctrl_area):
                for guard in gm.group(1).split(","):
                    guard = guard.strip()
                    if guard and guard not in class_guards:
                        class_guards.append(guard)
            for rm in RE_NESTJS_ROLES.finditer(ctrl_area):
                for role_raw in re.findall(_PQ + r"(\w+)" + _PQ, rm.group(1)):
                    if role_raw not in class_roles:
                        class_roles.append(role_raw)
        except Exception:
            pass

        for m in RE_NESTJS_DECORATOR.finditer(content):
            method = m.group(1).upper()
            route = m.group(2) or ""
            if controller_prefix:
                full_route = "/" + controller_prefix
                if route:
                    full_route += "/" + route.lstrip("/")
                full_route = full_route.replace("//", "/")
            else:
                full_route = "/" + route.lstrip("/") if route else "/"
            # Try to find handler name on the next line
            handler = ""
            after = content[m.end(): m.end() + 200]
            hm = RE_HANDLER_NAME.search(after)
            if hm:
                handler = hm.group(1)
            # Accepted params from req.body/query/params (Express-style fallback)
            method_block = content[m.end(): m.end() + 2000]
            accepted = list(dict.fromkeys(RE_REQ_FIELDS.findall(method_block)))

            # --- NestJS @Query('paramName') decorators ---
            try:
                for qm in RE_NESTJS_QUERY_PARAM.finditer(method_block):
                    param_name = qm.group(1)
                    if param_name not in accepted:
                        accepted.append(param_name)
            except Exception:
                pass

            # --- NestJS @Query() with DTO type ---
            try:
                for qdm in RE_NESTJS_QUERY_DTO.finditer(method_block):
                    dto_name = qdm.group(1)
                    # Look up DTO fields (with caching)
                    if dto_name not in _dto_cache:
                        _dto_cache[dto_name] = _extract_dto_fields(
                            project_root, dto_name,
                            current_file_content=content,
                        )
                    for field_name in _dto_cache[dto_name]:
                        if field_name not in accepted:
                            accepted.append(field_name)
            except Exception:
                pass

            # --- NestJS @Param('paramName') decorators ---
            try:
                for pm in RE_NESTJS_PARAM.finditer(method_block):
                    param_name = pm.group(1)
                    if param_name not in accepted:
                        accepted.append(param_name)
            except Exception:
                pass

            # --- NestJS @UseGuards, @Roles, @ApiResponse (method-level) ---
            before_start = max(0, m.start() - 800)
            before_block = content[before_start: m.start()]
            # Find the last } that closes a method body (followed by
            # whitespace, not by ')' which would be inside a decorator).
            # This avoids cutting off at } inside @ApiResponse({...}).
            brace_boundary = -1
            for bm in re.finditer(r"\}\s*\n", before_block):
                brace_boundary = bm.start()
            if brace_boundary >= 0:
                before_block = before_block[brace_boundary + 1:]

            method_guards = list(class_guards)
            method_roles = list(class_roles)
            api_resp_desc = ""

            try:
                for gm in RE_NESTJS_USE_GUARDS.finditer(before_block):
                    for guard in gm.group(1).split(","):
                        guard = guard.strip()
                        if guard and guard not in method_guards:
                            method_guards.append(guard)
                for rm in RE_NESTJS_ROLES.finditer(before_block):
                    for role_raw in re.findall(
                        _PQ + r"(\w+)" + _PQ, rm.group(1)
                    ):
                        if role_raw not in method_roles:
                            method_roles.append(role_raw)
                arm = RE_NESTJS_API_RESPONSE.search(before_block)
                if not arm:
                    # Also check after the route decorator (some controllers
                    # place @ApiResponse after @Get/@Post)
                    arm = RE_NESTJS_API_RESPONSE.search(method_block)
                if arm:
                    api_resp_desc = arm.group(1)
            except Exception:
                pass

            resp_fields = _extract_backend_response_fields(method_block)
            endpoints.append(BackendEndpoint(
                file_path=rel,
                route_path=full_route,
                http_method=method,
                handler_name=handler,
                accepted_params=accepted,
                response_fields=resp_fields,
                guards=method_guards,
                roles=method_roles,
                api_response_desc=api_resp_desc,
            ))

        # ---- Express ----
        for m in RE_EXPRESS.finditer(content):
            method = m.group(1).upper()
            route = m.group(2)
            handler = ""
            after = content[m.end(): m.end() + 200]
            hm = RE_HANDLER_NAME.search(after)
            if hm:
                handler = hm.group(1)
            method_block = content[m.end(): m.end() + 2000]
            accepted = list(dict.fromkeys(RE_REQ_FIELDS.findall(method_block)))
            resp_fields = _extract_backend_response_fields(method_block)
            endpoints.append(BackendEndpoint(
                file_path=rel,
                route_path=route,
                http_method=method,
                handler_name=handler,
                accepted_params=accepted,
                response_fields=resp_fields,
            ))

        # ---- FastAPI ----
        for m in RE_FASTAPI.finditer(content):
            method = m.group(1).upper()
            route = m.group(2)
            handler = ""
            after = content[m.end(): m.end() + 300]
            hm = re.search(r"def\s+(\w+)", after)
            if hm:
                handler = hm.group(1)
            # Extract params from function signature
            func_m = RE_FUNC_PARAMS.search(after)
            accepted: list[str] = []
            if func_m:
                raw_params = func_m.group(1)
                for param in raw_params.split(","):
                    param = param.strip()
                    if not param or param == "self" or param.startswith("request"):
                        continue
                    param_name = param.split(":")[0].split("=")[0].strip()
                    if param_name:
                        accepted.append(param_name)
            method_block = content[m.end(): m.end() + 2000]
            resp_fields = _extract_backend_response_fields(method_block)
            endpoints.append(BackendEndpoint(
                file_path=rel,
                route_path=route,
                http_method=method,
                handler_name=handler,
                accepted_params=accepted,
                response_fields=resp_fields,
            ))

        # ---- Django ----
        for m in RE_DJANGO.finditer(content):
            route = "/" + m.group(1).lstrip("^").rstrip("$").strip("/")
            # Django path() doesn't encode the method -- default to ALL
            handler = ""
            after = content[m.end(): m.end() + 200]
            hm = re.search(r",\s*(\w+)", after)
            if hm:
                handler = hm.group(1)
            endpoints.append(BackendEndpoint(
                file_path=rel,
                route_path=route,
                http_method="ALL",
                handler_name=handler,
                accepted_params=[],
                response_fields=[],
            ))

    logger.info("Scanned backend: found %d endpoints", len(endpoints))
    return endpoints


def _extract_backend_response_fields(block: str) -> list[str]:
    """Extract response field names from a backend handler block."""
    fields: list[str] = []
    for m in RE_RESPONSE_OBJECT.finditer(block):
        fields.extend(RE_FIELD_KEY.findall(m.group(1)))
    return list(dict.fromkeys(fields))


# ---------------------------------------------------------------------------
# Project-wide field naming analysis (Gap 3)
# ---------------------------------------------------------------------------

def detect_field_naming_mismatches(project_root: Path) -> list[IntegrationMismatch]:
    """Detect project-wide camelCase vs snake_case field naming mismatches.

    Scans ALL frontend ``.ts``/``.tsx`` files for camelCase field accesses
    on API response objects (e.g., ``res.buildingId``, ``data.slaCompliance``)
    and ALL backend DTO/model/schema files for snake_case field definitions.

    For each frontend camelCase field that has a corresponding snake_case
    version in the backend, a MEDIUM severity mismatch is reported.

    This catches the very common pattern where a NestJS/Express backend
    returns ``snake_case`` fields (from the database) but the frontend
    reads them as ``camelCase``.

    Args:
        project_root: Root directory of the project.

    Returns:
        A list of ``IntegrationMismatch`` for each detected naming conflict.
    """
    mismatches: list[IntegrationMismatch] = []

    # --- Collect backend snake_case fields ---
    backend_snake_fields: dict[str, list[str]] = {}  # field -> [file_paths]
    backend_extensions = {".ts", ".tsx", ".js", ".py"}
    backend_indicator_dirs = {
        "dto", "dtos", "model", "models", "entity", "entities",
        "schema", "schemas", "prisma", "types",
    }

    for fpath in _iter_files(project_root, backend_extensions, BACKEND_SKIP_DIRS):
        # Only scan files likely to contain field definitions
        parts_lower = {p.lower() for p in fpath.parts}
        is_model_file = bool(parts_lower & backend_indicator_dirs)
        fname_lower = fpath.name.lower()
        is_schema = any(kw in fname_lower for kw in (
            "dto", "model", "entity", "schema", "prisma", "type",
        ))
        if not is_model_file and not is_schema:
            continue

        content = _read_file(fpath)
        if content is None:
            continue

        rel = str(fpath)
        for m in RE_BACKEND_SNAKE_FIELD.finditer(content):
            field_name = m.group(1)
            # Skip very short or common non-field matches
            if len(field_name) < 3:
                continue
            backend_snake_fields.setdefault(field_name, [])
            if rel not in backend_snake_fields[field_name]:
                backend_snake_fields[field_name].append(rel)

    # ALWAYS scan Prisma/schema files (not just as fallback) — these are the
    # primary source of snake_case field definitions in NestJS+Prisma projects.
    prisma_files = list(_iter_files(
        project_root, {".prisma"}, BACKEND_SKIP_DIRS
    ))
    for fpath in prisma_files:
        content = _read_file(fpath)
        if content is None:
            continue
        rel = str(fpath)
        for m in RE_BACKEND_SNAKE_FIELD.finditer(content):
            field_name = m.group(1)
            if len(field_name) < 3:
                continue
            backend_snake_fields.setdefault(field_name, [])
            if rel not in backend_snake_fields[field_name]:
                backend_snake_fields[field_name].append(rel)

    # Also scan backend service/controller files — they often reference
    # snake_case fields from the ORM directly.
    for fpath in _iter_files(project_root, backend_extensions, BACKEND_SKIP_DIRS):
        fname_lower = fpath.name.lower()
        if any(kw in fname_lower for kw in ("service", "controller", "resolver")):
            content = _read_file(fpath)
            if content is None:
                continue
            rel = str(fpath)
            for m in RE_BACKEND_SNAKE_FIELD.finditer(content):
                field_name = m.group(1)
                if len(field_name) < 3:
                    continue
                backend_snake_fields.setdefault(field_name, [])
                if rel not in backend_snake_fields[field_name]:
                    backend_snake_fields[field_name].append(rel)

    if not backend_snake_fields:
        logger.debug("No snake_case backend fields found; skipping naming check")
        return []

    # --- Scan frontend for camelCase response field accesses ---
    frontend_extensions = {".ts", ".tsx", ".js", ".jsx"}
    seen_pairs: set[tuple[str, str]] = set()  # (camelField, snakeField) dedup

    for fpath in _iter_files(project_root, frontend_extensions, FRONTEND_SKIP_DIRS):
        content = _read_file(fpath)
        if content is None:
            continue

        rel = str(fpath)

        # Collect camelCase field names from dot/optional-chaining access
        camel_fields_in_file: list[str] = []
        for m in RE_FRONTEND_CAMEL_FIELD.finditer(content):
            var_name = m.group(1)
            field_name = m.group(2)
            # Skip known non-API objects
            if var_name in _CAMEL_FIELD_EXCLUDE_PREFIXES:
                continue
            camel_fields_in_file.append(field_name)

        # Also collect from destructuring patterns:
        # const { buildingId, slaCompliance } = response;
        for m in RE_DESTRUCTURE_RESPONSE.finditer(content):
            inner = m.group(1)
            for segment in inner.split(","):
                segment = segment.strip()
                if not segment or segment.startswith("..."):
                    continue
                # Handle renaming: { originalName: localName }
                field_name = segment.split(":")[0].strip()
                if field_name and re.match(r"^[a-z][a-zA-Z]+[A-Z]\w*$", field_name):
                    camel_fields_in_file.append(field_name)

        for camel_field in camel_fields_in_file:
            snake_field = _camel_to_snake(camel_field)

            # Check if the corresponding snake_case field exists in backend
            if snake_field in backend_snake_fields:
                pair_key = (camel_field, snake_field)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                backend_files = backend_snake_fields[snake_field]
                mismatches.append(IntegrationMismatch(
                    severity="MEDIUM",
                    category="field_naming_convention",
                    frontend_file=rel,
                    backend_file=backend_files[0] if backend_files else "",
                    description=(
                        f"Frontend accesses '{camel_field}' (camelCase) but "
                        f"backend defines '{snake_field}' (snake_case). "
                        f"Without a serialization layer, this field will be "
                        f"undefined at runtime."
                    ),
                    suggestion=(
                        f"Add a response serialization/transformation layer "
                        f"(e.g., class-transformer with @Expose) to convert "
                        f"'{snake_field}' -> '{camel_field}', or update the "
                        f"frontend to use '{snake_field}'."
                    ),
                ))

    logger.info(
        "Field naming analysis: found %d camelCase/snake_case mismatches",
        len(mismatches),
    )
    return mismatches


def detect_response_shape_mismatches(project_root: Path) -> list[IntegrationMismatch]:
    """Detect inconsistent response wrapping patterns in frontend code.

    Scans for defensive access patterns that indicate the frontend developer
    was unsure whether the API returns data directly or wrapped in a
    ``{ data: ... }`` envelope.  Common indicators include:

    * ``Array.isArray(res) ? res : res.data``
    * ``res.data || res``
    * ``res?.data ?? res``

    These patterns suggest the backend response shape is inconsistent across
    endpoints, which leads to fragile code.

    Args:
        project_root: Root directory of the project.

    Returns:
        A list of ``IntegrationMismatch`` for each defensive pattern found.
    """
    mismatches: list[IntegrationMismatch] = []
    extensions = {".ts", ".tsx", ".js", ".jsx"}

    # Additional patterns to catch with simple string matching
    defensive_patterns = [
        (r"Array\.isArray\(\s*(\w+)\s*\)\s*\?\s*\1\s*:\s*\1\.data", "Array.isArray({var}) ? {var} : {var}.data"),
        (r"(\w+)\.data\s*\|\|\s*\1(?!\w)", "{var}.data || {var}"),
        (r"(\w+)\?\.data\s*\?\?\s*\1(?!\w)", "{var}?.data ?? {var}"),
        (r"(\w+)\.data\s*\?\s*\1\.data\s*:\s*\1(?!\w)", "{var}.data ? {var}.data : {var}"),
    ]

    compiled_patterns = [(re.compile(p), desc) for p, desc in defensive_patterns]

    for fpath in _iter_files(project_root, extensions, FRONTEND_SKIP_DIRS):
        content = _read_file(fpath)
        if content is None:
            continue

        rel = str(fpath)

        for pattern, desc_template in compiled_patterns:
            for m in pattern.finditer(content):
                var_name = m.group(1)
                line_num = _line_number(content, m.start())
                mismatches.append(IntegrationMismatch(
                    severity="MEDIUM",
                    category="response_shape_inconsistency",
                    frontend_file=f"{rel}:{line_num}",
                    backend_file="",
                    description=(
                        f"Defensive response unwrapping detected: "
                        f"'{m.group(0).strip()}' suggests inconsistent "
                        f"response envelope (sometimes raw data, sometimes "
                        f"wrapped in .data)."
                    ),
                    suggestion=(
                        "Standardise all API responses to use a consistent "
                        "envelope shape (e.g., always return "
                        "{ data: ..., meta: ... }) and update the frontend "
                        "to always unwrap via res.data."
                    ),
                ))

    logger.info(
        "Response shape analysis: found %d inconsistency indicators",
        len(mismatches),
    )
    return mismatches


# ---------------------------------------------------------------------------
# Matching & diffing
# ---------------------------------------------------------------------------

def match_endpoints(
    frontend_calls: list[FrontendAPICall],
    backend_endpoints: list[BackendEndpoint],
) -> IntegrationReport:
    """Match frontend API calls against backend endpoint definitions.

    Produces an ``IntegrationReport`` that includes missing endpoints,
    unused endpoints, method mismatches, and field name mismatches.

    Args:
        frontend_calls: Parsed frontend API calls.
        backend_endpoints: Parsed backend endpoint definitions.

    Returns:
        An ``IntegrationReport`` summarising all findings.
    """
    mismatches: list[IntegrationMismatch] = []
    field_mismatches: list[IntegrationMismatch] = []
    missing_endpoints: list[str] = []
    unused_endpoints_set: set[str] = set()
    matched = 0

    # Build lookup: normalized_path -> list[BackendEndpoint]
    backend_map: dict[str, list[BackendEndpoint]] = {}
    for ep in backend_endpoints:
        norm = normalize_path(ep.route_path)
        backend_map.setdefault(norm, []).append(ep)
        unused_endpoints_set.add(norm)

    # Build secondary lookup with API prefixes stripped so that
    # e.g. backend "/api/v1/assets" can match frontend "/assets".
    # Maps stripped_path -> list of original normalized keys.
    stripped_map: dict[str, list[str]] = {}
    for norm_key in backend_map:
        stripped = _strip_api_prefix(norm_key)
        if stripped != norm_key:
            stripped_map.setdefault(stripped, []).append(norm_key)

    def _find_candidates(norm_call: str) -> tuple[list[BackendEndpoint] | None, str | None]:
        """Try progressively looser matching strategies.

        Returns ``(candidates, matched_norm_key)`` or ``(None, None)``.
        """
        # 1. Exact match on normalized path
        if norm_call in backend_map:
            return backend_map[norm_call], norm_call

        # 2. Strip API prefix from frontend path, then exact match
        stripped_call = _strip_api_prefix(norm_call)
        if stripped_call != norm_call and stripped_call in backend_map:
            return backend_map[stripped_call], stripped_call

        # 3. Frontend path (possibly stripped) matches a stripped backend path
        for lookup_path in (norm_call, stripped_call):
            if lookup_path in stripped_map:
                orig_key = stripped_map[lookup_path][0]
                return backend_map[orig_key], orig_key

        # 4. Suffix match — match the last N segments of the frontend path
        #    against backend paths. E.g. "/assets/:param" matches
        #    "/api/v1/assets/:param".
        call_segments = [s for s in norm_call.split("/") if s]
        if call_segments:
            for norm_key, eps in backend_map.items():
                key_segments = [s for s in norm_key.split("/") if s]
                if (
                    len(call_segments) <= len(key_segments)
                    and key_segments[-len(call_segments):] == call_segments
                ):
                    return eps, norm_key

        return None, None

    seen_missing: set[str] = set()

    for call in frontend_calls:
        norm_call = normalize_path(call.endpoint_path)
        candidates, matched_key = _find_candidates(norm_call)

        if not candidates:
            if norm_call not in seen_missing:
                missing_endpoints.append(call.endpoint_path)
                seen_missing.add(norm_call)
                mismatches.append(IntegrationMismatch(
                    severity="HIGH",
                    category="missing_endpoint",
                    frontend_file=call.file_path,
                    backend_file="",
                    description=(
                        f"Frontend calls {call.http_method} {call.endpoint_path} "
                        f"but no backend endpoint matches."
                    ),
                    suggestion=(
                        f"Create a backend handler for {call.http_method} {call.endpoint_path}."
                    ),
                ))
            continue

        # Remove from unused set
        if matched_key is not None:
            unused_endpoints_set.discard(matched_key)
        unused_endpoints_set.discard(norm_call)

        # Find best method match
        method_matched_eps = [
            ep for ep in candidates
            if ep.http_method == call.http_method or ep.http_method == "ALL"
        ]

        if not method_matched_eps:
            matched += 1  # path matched, but method didn't
            backend_methods = ", ".join(sorted({ep.http_method for ep in candidates}))
            mismatches.append(IntegrationMismatch(
                severity="HIGH",
                category="method_mismatch",
                frontend_file=call.file_path,
                backend_file=candidates[0].file_path,
                description=(
                    f"Frontend uses {call.http_method} {call.endpoint_path} "
                    f"but backend only defines [{backend_methods}]."
                ),
                suggestion=(
                    f"Change the frontend to use one of [{backend_methods}] "
                    f"or add a {call.http_method} handler in the backend."
                ),
            ))
            method_matched_eps = candidates  # still check fields

        else:
            matched += 1

        # Check field name mismatches
        for ep in method_matched_eps:
            # Request fields vs accepted params
            _check_field_mismatches(
                call.request_fields,
                ep.accepted_params,
                call,
                ep,
                direction="request",
                mismatches_out=field_mismatches,
            )
            # Response fields
            _check_field_mismatches(
                call.expected_response_fields,
                ep.response_fields,
                call,
                ep,
                direction="response",
                mismatches_out=field_mismatches,
            )
            # Query parameter mismatches
            if call.query_params and ep.accepted_params:
                _check_query_param_mismatches(
                    call.query_params,
                    ep.accepted_params,
                    call,
                    ep,
                    mismatches_out=field_mismatches,
                )

    # Unused endpoints
    unused_list = sorted(unused_endpoints_set)

    for norm in unused_list:
        eps = backend_map[norm]
        for ep in eps:
            mismatches.append(IntegrationMismatch(
                severity="LOW",
                category="unused_endpoint",
                frontend_file="",
                backend_file=ep.file_path,
                description=(
                    f"Backend defines {ep.http_method} {ep.route_path} "
                    f"but no frontend code calls it."
                ),
                suggestion="Verify this endpoint is needed or remove dead code.",
            ))

    return IntegrationReport(
        total_frontend_calls=len(frontend_calls),
        total_backend_endpoints=len(backend_endpoints),
        matched=matched,
        mismatches=mismatches,
        missing_endpoints=missing_endpoints,
        unused_endpoints=[
            ep.route_path
            for norm in unused_list
            for ep in backend_map[norm]
        ],
        field_name_mismatches=field_mismatches,
    )


def _check_field_mismatches(
    frontend_fields: list[str],
    backend_fields: list[str],
    call: FrontendAPICall,
    ep: BackendEndpoint,
    direction: str,
    mismatches_out: list[IntegrationMismatch],
) -> None:
    """Compare field lists and append any case-style mismatches."""
    if not frontend_fields or not backend_fields:
        return

    backend_set_lower = {f.lower() for f in backend_fields}

    for ff in frontend_fields:
        # Exact match -- fine
        if ff in backend_fields:
            continue

        # Case-insensitive match -- likely a snake/camel mismatch
        if ff.lower() in backend_set_lower:
            # Find the backend version
            be_field = next(
                (bf for bf in backend_fields if bf.lower() == ff.lower()), ff
            )
            mismatches_out.append(IntegrationMismatch(
                severity="MEDIUM",
                category=f"field_case_mismatch_{direction}",
                frontend_file=call.file_path,
                backend_file=ep.file_path,
                description=(
                    f"Field name case mismatch in {direction}: "
                    f"frontend uses '{ff}', backend uses '{be_field}'."
                ),
                suggestion=(
                    "Standardise to one style. Prefer camelCase in JS/TS, "
                    "snake_case in Python."
                ),
            ))
            continue

        # Check snake<->camel equivalence
        matched_backend = None
        for bf in backend_fields:
            if _fields_equivalent(ff, bf):
                matched_backend = bf
                break

        if matched_backend:
            mismatches_out.append(IntegrationMismatch(
                severity="MEDIUM",
                category=f"field_case_mismatch_{direction}",
                frontend_file=call.file_path,
                backend_file=ep.file_path,
                description=(
                    f"Field name style mismatch in {direction}: "
                    f"frontend uses '{ff}', backend uses '{matched_backend}'."
                ),
                suggestion=(
                    f"Use a consistent naming convention or add a "
                    f"serialization layer to translate between "
                    f"'{ff}' and '{matched_backend}'."
                ),
            ))
        else:
            # Field not found at all in backend
            mismatches_out.append(IntegrationMismatch(
                severity="HIGH",
                category=f"field_missing_{direction}",
                frontend_file=call.file_path,
                backend_file=ep.file_path,
                description=(
                    f"Frontend {direction} field '{ff}' has no match in "
                    f"backend (available: {backend_fields})."
                ),
                suggestion=(
                    f"Add '{ff}' to the backend handler's "
                    f"{'accepted parameters' if direction == 'request' else 'response object'} "
                    f"or remove it from the frontend."
                ),
            ))


def _check_query_param_mismatches(
    frontend_params: list[str],
    backend_params: list[str],
    call: FrontendAPICall,
    ep: BackendEndpoint,
    mismatches_out: list[IntegrationMismatch],
) -> None:
    """Compare frontend query parameter names against backend accepted params.

    Detects mismatches where the frontend sends a query parameter under a
    different name than what the backend expects (e.g., ``buildingId`` vs
    ``building_id``, ``priority`` vs ``priority_id``).

    Args:
        frontend_params: Query parameter names extracted from the frontend URL.
        backend_params: Accepted parameter names from the backend handler.
        call: The frontend API call being checked.
        ep: The backend endpoint being compared against.
        mismatches_out: List to append any detected mismatches to.
    """
    backend_set = set(backend_params)
    backend_set_lower = {p.lower() for p in backend_params}

    for fp in frontend_params:
        # Exact match -- fine
        if fp in backend_set:
            continue

        # Check snake<->camel equivalence
        matched_backend = None
        for bp in backend_params:
            if _fields_equivalent(fp, bp):
                matched_backend = bp
                break

        if matched_backend:
            mismatches_out.append(IntegrationMismatch(
                severity="MEDIUM",
                category="query_param_case_mismatch",
                frontend_file=call.file_path,
                backend_file=ep.file_path,
                description=(
                    f"Query parameter naming mismatch: frontend sends "
                    f"'{fp}', backend expects '{matched_backend}' "
                    f"for {call.http_method} {call.endpoint_path}."
                ),
                suggestion=(
                    f"Rename the query parameter to match: use "
                    f"'{matched_backend}' in the frontend or '{fp}' "
                    f"in the backend."
                ),
            ))
        elif fp.lower() in backend_set_lower:
            be_param = next(
                (bp for bp in backend_params if bp.lower() == fp.lower()), fp
            )
            mismatches_out.append(IntegrationMismatch(
                severity="MEDIUM",
                category="query_param_case_mismatch",
                frontend_file=call.file_path,
                backend_file=ep.file_path,
                description=(
                    f"Query parameter case mismatch: frontend sends "
                    f"'{fp}', backend expects '{be_param}' "
                    f"for {call.http_method} {call.endpoint_path}."
                ),
                suggestion=(
                    f"Standardise query parameter names. Use "
                    f"'{be_param}' consistently."
                ),
            ))
        else:
            # Check for partial name matches (e.g., 'priority' vs 'priority_id')
            partial_match = None
            for bp in backend_params:
                fp_lower = fp.lower()
                bp_lower = bp.lower()
                # One is a prefix/suffix of the other
                if (fp_lower in bp_lower or bp_lower in fp_lower) and \
                        fp_lower != bp_lower:
                    partial_match = bp
                    break
                # camelCase -> snake_case comparison
                fp_snake = _camel_to_snake(fp)
                if (fp_snake in bp_lower or bp_lower in fp_snake) and \
                        fp_snake != bp_lower:
                    partial_match = bp
                    break

            if partial_match:
                mismatches_out.append(IntegrationMismatch(
                    severity="MEDIUM",
                    category="query_param_name_mismatch",
                    frontend_file=call.file_path,
                    backend_file=ep.file_path,
                    description=(
                        f"Query parameter name mismatch: frontend sends "
                        f"'{fp}', backend expects '{partial_match}' "
                        f"for {call.http_method} {call.endpoint_path}."
                    ),
                    suggestion=(
                        f"Align query parameter names: rename frontend "
                        f"'{fp}' to '{partial_match}' or update the "
                        f"backend to accept '{fp}'."
                    ),
                ))
            else:
                mismatches_out.append(IntegrationMismatch(
                    severity="HIGH",
                    category="query_param_missing",
                    frontend_file=call.file_path,
                    backend_file=ep.file_path,
                    description=(
                        f"Frontend sends query parameter '{fp}' but "
                        f"backend does not accept it "
                        f"(accepted: {backend_params}) "
                        f"for {call.http_method} {call.endpoint_path}."
                    ),
                    suggestion=(
                        f"Add '{fp}' to the backend's accepted query "
                        f"parameters or remove it from the frontend URL."
                    ),
                ))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_report_for_prompt(
    report: IntegrationReport,
    max_chars: int = 10000,
) -> str:
    """Render an ``IntegrationReport`` as Markdown suitable for LLM context.

    The output is truncated to *max_chars* characters if necessary.

    Args:
        report: The integration report to format.
        max_chars: Maximum character budget for the output.

    Returns:
        A Markdown-formatted string.
    """
    lines: list[str] = []
    lines.append("# Integration Verification Report")
    lines.append("")
    lines.append(f"- **Frontend API calls:** {report.total_frontend_calls}")
    lines.append(f"- **Backend endpoints:** {report.total_backend_endpoints}")
    lines.append(f"- **Matched:** {report.matched}")
    lines.append(f"- **Missing endpoints:** {len(report.missing_endpoints)}")
    lines.append(f"- **Unused endpoints:** {len(report.unused_endpoints)}")
    lines.append(f"- **Field mismatches:** {len(report.field_name_mismatches)}")
    lines.append("")

    # CRITICAL severity first
    critical_issues = [m for m in report.mismatches if m.severity == "CRITICAL"]
    if critical_issues:
        lines.append("## CRITICAL Severity Issues")
        lines.append("")
        for m in critical_issues:
            lines.append(f"### [{m.category}] {m.description}")
            if m.frontend_file:
                lines.append(f"- Frontend: `{m.frontend_file}`")
            if m.backend_file:
                lines.append(f"- Backend: `{m.backend_file}`")
            lines.append(f"- Suggestion: {m.suggestion}")
            lines.append("")

    # HIGH severity
    high_issues = [m for m in report.mismatches if m.severity == "HIGH"]
    if high_issues:
        lines.append("## HIGH Severity Issues")
        lines.append("")
        for m in high_issues:
            lines.append(f"### [{m.category}] {m.description}")
            if m.frontend_file:
                lines.append(f"- Frontend: `{m.frontend_file}`")
            if m.backend_file:
                lines.append(f"- Backend: `{m.backend_file}`")
            lines.append(f"- Suggestion: {m.suggestion}")
            lines.append("")

    # MEDIUM
    medium_issues = [m for m in report.mismatches if m.severity == "MEDIUM"]
    medium_issues.extend(report.field_name_mismatches)
    if medium_issues:
        lines.append("## MEDIUM Severity Issues")
        lines.append("")
        for m in medium_issues:
            lines.append(f"### [{m.category}] {m.description}")
            if m.frontend_file:
                lines.append(f"- Frontend: `{m.frontend_file}`")
            if m.backend_file:
                lines.append(f"- Backend: `{m.backend_file}`")
            lines.append(f"- Suggestion: {m.suggestion}")
            lines.append("")

    # LOW
    low_issues = [m for m in report.mismatches if m.severity == "LOW"]
    if low_issues:
        lines.append("## LOW Severity Issues")
        lines.append("")
        for m in low_issues:
            lines.append(f"- [{m.category}] {m.description}")
        lines.append("")

    # Missing endpoints summary
    if report.missing_endpoints:
        lines.append("## Missing Endpoints (frontend calls, no backend)")
        lines.append("")
        for ep in report.missing_endpoints:
            lines.append(f"- `{ep}`")
        lines.append("")

    # Unused endpoints summary
    if report.unused_endpoints:
        lines.append("## Unused Endpoints (backend defined, no frontend call)")
        lines.append("")
        for ep in report.unused_endpoints:
            lines.append(f"- `{ep}`")
        lines.append("")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 30] + "\n\n... (truncated) ..."
    return text


def format_report_for_log(report: IntegrationReport) -> str:
    """Render an ``IntegrationReport`` as structured log output.

    Args:
        report: The integration report to format.

    Returns:
        A human-readable multi-line string.
    """
    lines: list[str] = []
    lines.append("=== Integration Verification Report ===")
    lines.append(f"Frontend API calls : {report.total_frontend_calls}")
    lines.append(f"Backend endpoints  : {report.total_backend_endpoints}")
    lines.append(f"Matched            : {report.matched}")
    lines.append(f"Missing endpoints  : {len(report.missing_endpoints)}")
    lines.append(f"Unused endpoints   : {len(report.unused_endpoints)}")
    lines.append(f"Field mismatches   : {len(report.field_name_mismatches)}")
    lines.append(f"Total mismatches   : {len(report.mismatches)}")
    lines.append("")

    if report.mismatches:
        lines.append("--- Mismatches ---")
        for m in report.mismatches:
            lines.append(
                f"[{m.severity}] {m.category}: {m.description}"
            )
            if m.suggestion:
                lines.append(f"       -> {m.suggestion}")
        lines.append("")

    if report.field_name_mismatches:
        lines.append("--- Field Name Mismatches ---")
        for m in report.field_name_mismatches:
            lines.append(
                f"[{m.severity}] {m.category}: {m.description}"
            )
            if m.suggestion:
                lines.append(f"       -> {m.suggestion}")
        lines.append("")

    if report.missing_endpoints:
        lines.append("--- Missing Endpoints ---")
        for ep in report.missing_endpoints:
            lines.append(f"  {ep}")
        lines.append("")

    if report.unused_endpoints:
        lines.append("--- Unused Endpoints ---")
        for ep in report.unused_endpoints:
            lines.append(f"  {ep}")
        lines.append("")

    lines.append("=== End Report ===")
    return "\n".join(lines)


def save_report(report: IntegrationReport, output_path: Path) -> None:
    """Save an ``IntegrationReport`` as a JSON file.

    Args:
        report: The integration report to save.
        output_path: Path for the output JSON file.
    """
    data = asdict(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )
    logger.info("Report saved to %s", output_path)


# ---------------------------------------------------------------------------
# Prisma missing-include detection
# ---------------------------------------------------------------------------


def _parse_prisma_schema(
    schema_text: str,
) -> dict[str, list[tuple[str, str, str]]]:
    """Parse a Prisma schema and extract forward-FK relations per model.

    Returns a dict mapping PascalCase model names to a list of tuples
    ``(relation_name, related_model, fk_field)`` for each ``@relation``
    field that carries a ``fields:`` clause (i.e. the FK-owning side).

    Reverse / array relations (e.g. ``orders Order[]``) are skipped
    because they have no ``fields:`` clause.

    Example return value::

        {
            'WorkOrder': [
                ('category', 'MaintenanceCategory', 'category_id'),
                ('priority', 'MaintenancePriority', 'priority_id'),
            ],
            'Asset': [
                ('category', 'AssetCategory', 'category_id'),
            ],
        }
    """
    # Split schema into model blocks
    model_positions: list[tuple[str, int]] = []
    for m in RE_PRISMA_MODEL_DECL.finditer(schema_text):
        model_positions.append((m.group(1), m.start()))

    result: dict[str, list[tuple[str, str, str]]] = {}

    for idx, (model_name, start) in enumerate(model_positions):
        # Determine end of this model block
        if idx + 1 < len(model_positions):
            end = model_positions[idx + 1][1]
        else:
            end = len(schema_text)
        block = schema_text[start:end]

        relations: list[tuple[str, str, str]] = []
        for rm in RE_PRISMA_RELATION_FIELD.finditer(block):
            rel_name = rm.group(1)
            related_model = rm.group(2)
            fk_field = rm.group(3)

            # Skip tenant and self-referential relations
            if rel_name in _PRISMA_SKIP_RELATIONS:
                continue
            if fk_field in _PRISMA_SKIP_FK_FIELDS:
                continue
            # Skip self-referential (parent/children) relations
            if related_model == model_name:
                continue

            relations.append((rel_name, related_model, fk_field))

        if relations:
            result[model_name] = relations

    return result


def _extract_query_args_text(text: str, call_end: int) -> str:
    """Extract the full argument text of a Prisma query call.

    Starting from *call_end* (right after the opening ``(``), walks forward
    counting braces and parentheses to find the matching ``)`` and returns
    everything in between.  Falls back to a fixed window if matching fails.
    """
    depth = 1
    limit = min(len(text), call_end + 3000)
    for i in range(call_end, limit):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[call_end:i]
    # Fallback: return a fixed window
    return text[call_end:call_end + 2000]


def _extract_included_relations(query_args: str) -> set[str]:
    """Extract relation names from an ``include: { ... }`` clause.

    Parses the top-level keys of the include object.  Handles simple
    ``relation: true`` and nested ``relation: { select: ... }`` forms.
    """
    # Find include: { ... } — need to handle nested braces
    inc_match = re.search(r"include\s*:\s*\{", query_args)
    if not inc_match:
        return set()

    # Walk forward from the opening brace to find matching close
    start = inc_match.end() - 1  # position of the '{'
    depth = 0
    end = len(query_args)
    for i in range(start, len(query_args)):
        if query_args[i] == "{":
            depth += 1
        elif query_args[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    include_body = query_args[start + 1:end]
    return set(RE_PRISMA_INCLUDE_KEY.findall(include_body))


def detect_missing_prisma_includes(
    project_root: Path,
    skip_dirs: set[str] | None = None,
) -> list[IntegrationMismatch]:
    """Detect Prisma queries missing relation includes that frontend expects.

    Parses the Prisma schema to find model relations, then scans backend
    service files for Prisma query calls.  For each ``findMany`` or
    ``findFirst`` / ``findUnique`` call, compares the ``include`` clause
    against the model's available relations to find missing includes.

    A missing include means the API response will contain a raw UUID
    foreign-key field instead of the resolved relation object, causing
    the frontend to display UUIDs instead of human-readable names.

    Args:
        project_root: Root directory of the project to scan.
        skip_dirs: Optional set of directory names to skip.

    Returns:
        A list of ``IntegrationMismatch`` instances for each missing include.
    """
    issues: list[IntegrationMismatch] = []
    _skip = skip_dirs if skip_dirs is not None else BACKEND_SKIP_DIRS

    # --- Step 1: Find and parse Prisma schema ---
    schema_path = None
    for candidate in [
        project_root / "prisma" / "schema.prisma",
        project_root / "apps" / "api" / "prisma" / "schema.prisma",
        project_root / "server" / "prisma" / "schema.prisma",
        project_root / "backend" / "prisma" / "schema.prisma",
    ]:
        if candidate.is_file():
            schema_path = candidate
            break

    # If not found in standard locations, search for it
    if schema_path is None:
        for fpath in _iter_files(project_root, {".prisma"}, _skip):
            if fpath.name == "schema.prisma" and "node_modules" not in str(fpath):
                schema_path = fpath
                break

    if schema_path is None:
        logger.debug("No Prisma schema found in %s", project_root)
        return issues

    schema_text = _read_file(schema_path)
    if not schema_text:
        return issues

    model_relations = _parse_prisma_schema(schema_text)
    if not model_relations:
        logger.debug("No model relations found in Prisma schema")
        return issues

    logger.info(
        "Parsed Prisma schema: %d models with relations",
        len(model_relations),
    )

    # --- Step 2: Build accessor → model lookup ---
    # Prisma uses camelCase accessors: WorkOrder → workOrder, SLATimer → sLATimer
    accessor_to_model: dict[str, str] = {}
    for model_name in model_relations:
        accessor = model_name[0].lower() + model_name[1:]
        accessor_to_model[accessor] = model_name

    # --- Step 3: Scan backend service files for Prisma queries ---
    extensions = {".ts", ".js"}
    for fpath in _iter_files(project_root, extensions, _skip):
        # Only scan service files (where Prisma queries live)
        fname = fpath.name
        if not (fname.endswith(".service.ts") or fname.endswith(".service.js")):
            continue

        content = _read_file(fpath)
        if content is None:
            continue

        rel_path = str(fpath)

        for qm in RE_PRISMA_QUERY_CALL.finditer(content):
            accessor = qm.group(1)
            query_method = qm.group(2)
            line_num = _line_number(content, qm.start())

            # Look up the model
            model_name = accessor_to_model.get(accessor)
            if model_name is None:
                continue

            relations = model_relations.get(model_name, [])
            if not relations:
                continue

            # Extract the query arguments and find included relations
            call_end = qm.end()  # position right after '('
            query_args = _extract_query_args_text(content, call_end)
            included = _extract_included_relations(query_args)

            # Check for select: clause — if select is used, the query
            # intentionally picks specific fields, so skip it
            if re.search(r"\bselect\s*:", query_args):
                continue

            # Find missing relations
            for rel_name, related_model, fk_field in relations:
                if rel_name in included:
                    continue

                # Determine severity based on query method
                # findMany (list endpoints) → MEDIUM (most common UUID display bug)
                # findFirst/findUnique → LOW (may be internal validation)
                if query_method == "findMany":
                    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = "MEDIUM"
                else:
                    severity = "LOW"

                issues.append(IntegrationMismatch(
                    severity=severity,
                    category="missing_prisma_include",
                    frontend_file="",
                    backend_file=rel_path,
                    description=(
                        f"Prisma {accessor}.{query_method}() at line {line_num} "
                        f"does not include relation '{rel_name}' "
                        f"(FK: {fk_field} -> {related_model}). "
                        f"API response will contain raw UUID in '{fk_field}' "
                        f"instead of resolved '{rel_name}' object."
                    ),
                    suggestion=(
                        f"Add `include: {{ {rel_name}: true }}` to the Prisma "
                        f"query, or use `select` to explicitly choose fields. "
                        f"Frontend code accessing `item.{rel_name}.name` will "
                        f"fail without this include."
                    ),
                ))

    logger.info(
        "Prisma include analysis: found %d potential missing includes",
        len(issues),
    )
    return issues


# ---------------------------------------------------------------------------
# V2: BlockingGateResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class BlockingGateResult:
    """Structured result for blocking-gate mode.

    When ``run_mode="block"``, the verifier returns this alongside the
    ``IntegrationReport`` so that ``cli.py`` can decide whether to fail
    the milestone.
    """
    passed: bool
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    reason: str = ""
    findings: list[IntegrationMismatch] = field(default_factory=list)
    report: IntegrationReport | None = None


# ---------------------------------------------------------------------------
# V2: Verification check configuration
# ---------------------------------------------------------------------------

@dataclass
class VerificationChecksConfig:
    """Toggle individual V2 checks on or off.

    All checks default to enabled.  Set to ``False`` to skip a check.
    """
    route_structure: bool = True
    response_shape_validation: bool = True
    auth_flow: bool = True
    enum_cross_check: bool = True


# ---------------------------------------------------------------------------
# V2: Route Structure Consistency Check
# ---------------------------------------------------------------------------

# Regex to extract resource segments from a route path (ignoring params)
# e.g., /buildings/:id/floors -> ['buildings', 'floors']
RE_ROUTE_RESOURCE_SEGMENTS = re.compile(r"/([a-zA-Z][a-zA-Z0-9_-]*)")


def _extract_resource_segments(path: str) -> list[str]:
    """Extract non-parameter segments from a route path.

    >>> _extract_resource_segments('/buildings/:id/floors')
    ['buildings', 'floors']
    >>> _extract_resource_segments('/floors')
    ['floors']
    """
    norm = normalize_path(path)
    return [seg for seg in norm.split("/") if seg and seg != ":param"]


def _is_nested_route(path: str) -> bool:
    """Return True if the route contains nested resources (parent/:id/child)."""
    segments = _extract_resource_segments(path)
    return len(segments) >= 2


def detect_route_structure_mismatches(
    frontend_calls: list[FrontendAPICall],
    backend_endpoints: list[BackendEndpoint],
) -> list[IntegrationMismatch]:
    """Detect nested-vs-top-level route structure mismatches.

    If the frontend calls ``POST /buildings/:id/floors`` but the backend
    only defines ``POST /floors`` (top-level), this is a CRITICAL mismatch
    that always produces 404s.

    Args:
        frontend_calls: Parsed frontend API calls.
        backend_endpoints: Parsed backend endpoint definitions.

    Returns:
        A list of CRITICAL-severity ``IntegrationMismatch`` instances.
    """
    mismatches: list[IntegrationMismatch] = []

    # Build a lookup: last resource segment + method -> backend endpoints
    backend_by_resource: dict[tuple[str, str], list[BackendEndpoint]] = {}
    for ep in backend_endpoints:
        segments = _extract_resource_segments(ep.route_path)
        if segments:
            key = (segments[-1].lower(), ep.http_method)
            backend_by_resource.setdefault(key, []).append(ep)

    # Build normalized backend path set for quick exact-match check
    backend_norm_paths: set[str] = set()
    for ep in backend_endpoints:
        backend_norm_paths.add(normalize_path(ep.route_path))
        backend_norm_paths.add(_strip_api_prefix(normalize_path(ep.route_path)))

    seen: set[str] = set()

    for call in frontend_calls:
        fe_norm = normalize_path(call.endpoint_path)
        fe_stripped = _strip_api_prefix(fe_norm)

        # Skip if exact match exists (no structure mismatch)
        if fe_norm in backend_norm_paths or fe_stripped in backend_norm_paths:
            continue

        fe_segments = _extract_resource_segments(call.endpoint_path)
        if not fe_segments:
            continue

        # Check if frontend uses a nested route but backend has a flat route
        # for the same resource
        last_resource = fe_segments[-1].lower()
        key = (last_resource, call.http_method)

        if key in backend_by_resource and _is_nested_route(call.endpoint_path):
            for ep in backend_by_resource[key]:
                ep_segments = _extract_resource_segments(ep.route_path)
                # Backend is flat (single resource) while frontend is nested
                if not _is_nested_route(ep.route_path):
                    dedup_key = f"{call.endpoint_path}|{ep.route_path}"
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                    mismatches.append(IntegrationMismatch(
                        severity="CRITICAL",
                        category="route_structure_mismatch",
                        frontend_file=call.file_path,
                        backend_file=ep.file_path,
                        description=(
                            f"Route structure mismatch: frontend calls "
                            f"{call.http_method} {call.endpoint_path} (nested) "
                            f"but backend defines {ep.http_method} {ep.route_path} "
                            f"(top-level). This always produces 404 errors."
                        ),
                        suggestion=(
                            f"Either change the backend to use a nested route "
                            f"({call.endpoint_path}) or update the frontend to "
                            f"call the top-level route ({ep.route_path})."
                        ),
                    ))

        # Also check reverse: frontend flat, backend nested
        if key in backend_by_resource and not _is_nested_route(call.endpoint_path):
            for ep in backend_by_resource[key]:
                if _is_nested_route(ep.route_path):
                    ep_norm = normalize_path(ep.route_path)
                    ep_stripped = _strip_api_prefix(ep_norm)
                    if fe_norm != ep_norm and fe_stripped != ep_stripped:
                        dedup_key = f"{call.endpoint_path}|{ep.route_path}"
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)
                        mismatches.append(IntegrationMismatch(
                            severity="CRITICAL",
                            category="route_structure_mismatch",
                            frontend_file=call.file_path,
                            backend_file=ep.file_path,
                            description=(
                                f"Route structure mismatch: frontend calls "
                                f"{call.http_method} {call.endpoint_path} (top-level) "
                                f"but backend defines {ep.http_method} {ep.route_path} "
                                f"(nested). This always produces 404 errors."
                            ),
                            suggestion=(
                                f"Either change the frontend to use the nested route "
                                f"({ep.route_path}) or update the backend to use a "
                                f"top-level route ({call.endpoint_path})."
                            ),
                        ))

    logger.info(
        "Route structure analysis: found %d nested/flat mismatches",
        len(mismatches),
    )
    return mismatches


# ---------------------------------------------------------------------------
# V2: Response Shape Validation
# ---------------------------------------------------------------------------

# Patterns that detect bare-array returns from list endpoints
RE_BARE_ARRAY_RETURN = re.compile(
    r"(?:return|res\.json|res\.send|res\.status\(\d+\)\.json)\s*\(\s*(?:await\s+)?"
    r"(?:this\.)?\w+\.\w+\.findMany\s*\(",
    re.DOTALL,
)

# Pattern to detect list endpoints (GET endpoints returning collections)
RE_LIST_ENDPOINT_INDICATOR = re.compile(
    r"(?:findMany|find_all|list|getAll|get_all|fetchAll|fetch_all)\s*\(",
    re.IGNORECASE,
)

# Frontend defensive unwrapping patterns (more comprehensive than existing)
RE_DEFENSIVE_ARRAY_CHECK = re.compile(
    r"Array\.isArray\(\s*(\w+)(?:\.data)?\s*\)",
)

# Frontend pattern: response treated as both array and object with .data
RE_AMBIGUOUS_RESPONSE_ACCESS = re.compile(
    r"(?:(\w+)\.(?:data|results|items)\s*(?:\|\||&&|\?)\s*\1"
    r"|(\w+)\s*(?:\|\||&&|\?)\s*\2\.(?:data|results|items))",
)


def detect_response_shape_validation_issues(
    project_root: Path,
    frontend_calls: list[FrontendAPICall] | None = None,
    backend_endpoints: list[BackendEndpoint] | None = None,
) -> list[IntegrationMismatch]:
    """Validate that list endpoints return consistent response shapes.

    Checks for:
    - Backend list endpoints returning bare arrays instead of ``{data: [], meta: {}}``
    - Frontend defensive patterns like ``Array.isArray(res) ? res : res.data``
      that indicate shape inconsistency
    - Mismatched wrapping between different list endpoints

    Args:
        project_root: Root directory of the project.
        frontend_calls: Optional pre-scanned frontend calls.
        backend_endpoints: Optional pre-scanned backend endpoints.

    Returns:
        A list of HIGH-severity ``IntegrationMismatch`` instances.
    """
    mismatches: list[IntegrationMismatch] = []
    extensions = {".ts", ".tsx", ".js", ".jsx"}

    # --- Backend: detect bare-array returns from list endpoints ---
    backend_extensions = {".ts", ".js"}
    for fpath in _iter_files(project_root, backend_extensions, BACKEND_SKIP_DIRS):
        content = _read_file(fpath)
        if content is None:
            continue

        rel = str(fpath)

        # Find list/findMany calls that return directly (bare array)
        for m in RE_BARE_ARRAY_RETURN.finditer(content):
            line_num = _line_number(content, m.start())
            mismatches.append(IntegrationMismatch(
                severity="HIGH",
                category="response_shape_bare_array",
                frontend_file="",
                backend_file=f"{rel}:{line_num}",
                description=(
                    f"List endpoint appears to return a bare array from "
                    f"findMany() without wrapping in {{data: [], meta: {{}}}}. "
                    f"Bare arrays break pagination and make response shape "
                    f"inconsistent across endpoints."
                ),
                suggestion=(
                    "Wrap the findMany() result: return { data: results, "
                    "meta: { total, page, limit } } instead of returning "
                    "the array directly."
                ),
            ))

    # --- Frontend: detect defensive unwrapping (stronger than existing check) ---
    for fpath in _iter_files(project_root, extensions, FRONTEND_SKIP_DIRS):
        content = _read_file(fpath)
        if content is None:
            continue

        rel = str(fpath)

        # Detect Array.isArray checks on API response data
        for m in RE_DEFENSIVE_ARRAY_CHECK.finditer(content):
            var_name = m.group(1)
            # Check context: is this near an API call or response handling?
            context_start = max(0, m.start() - 500)
            context = content[context_start:m.start() + 200]
            if any(kw in context.lower() for kw in (
                "fetch", "api.", "axios.", "response", "res.", "data",
                "usequery", "usemutation",
            )):
                line_num = _line_number(content, m.start())
                mismatches.append(IntegrationMismatch(
                    severity="HIGH",
                    category="response_shape_defensive_check",
                    frontend_file=f"{rel}:{line_num}",
                    backend_file="",
                    description=(
                        f"Defensive Array.isArray() check on API response "
                        f"variable '{var_name}' suggests the response shape "
                        f"is inconsistent (sometimes array, sometimes object)."
                    ),
                    suggestion=(
                        "Standardise all list API responses to always return "
                        "{ data: [...], meta: { total, page, limit } } and "
                        "update frontend to always access response.data."
                    ),
                ))

        # Detect ambiguous response access patterns
        for m in RE_AMBIGUOUS_RESPONSE_ACCESS.finditer(content):
            var_name = m.group(1) or m.group(2)
            line_num = _line_number(content, m.start())
            mismatches.append(IntegrationMismatch(
                severity="HIGH",
                category="response_shape_ambiguous_access",
                frontend_file=f"{rel}:{line_num}",
                backend_file="",
                description=(
                    f"Ambiguous response access pattern on '{var_name}' — "
                    f"code treats it as both a direct value and a wrapper "
                    f"with .data/.results/.items property."
                ),
                suggestion=(
                    "Standardise API response shape and remove the "
                    "ambiguous access pattern."
                ),
            ))

    logger.info(
        "Response shape validation: found %d issues",
        len(mismatches),
    )
    return mismatches


# ---------------------------------------------------------------------------
# V2: Auth Flow Compatibility Check
# ---------------------------------------------------------------------------

# Auth-related endpoint patterns
RE_AUTH_ENDPOINT_FE = re.compile(
    r"(?:fetch|api\.\w+|axios\.\w+)(?:<[\s\S]*?>)?\s*\(\s*"
    + _Q + r"([^'\"` ]*(?:auth|login|logout|refresh|mfa|verify|register|signup|token|session)[^'\"` ]*)" + _Q,
    re.IGNORECASE,
)

RE_AUTH_ENDPOINT_BE = re.compile(
    r"(?:@(?:Get|Post|Put|Patch|Delete)\(\s*" + _PQ
    + r"([^'\"]*(?:auth|login|logout|refresh|mfa|verify|register|signup|token|session)[^'\"]*)"
    + _PQ
    + r"|(?:router|app)\.(?:get|post|put|patch|delete)\(\s*" + _Q
    + r"([^'\"` ]*(?:auth|login|logout|refresh|mfa|verify|register|signup|token|session)[^'\"` ]*)" + _Q
    + r")",
    re.IGNORECASE,
)

# MFA challenge patterns
RE_MFA_CHALLENGE_TOKEN = re.compile(
    r"(?:challenge[_-]?token|mfa[_-]?token|challenge[_-]?id|verification[_-]?id)",
    re.IGNORECASE,
)

RE_MFA_INLINE_CODE = re.compile(
    r"(?:mfa[_-]?code|otp[_-]?code|verification[_-]?code|totp[_-]?code|inline[_-]?code)",
    re.IGNORECASE,
)

# Token refresh patterns
RE_REFRESH_TOKEN_PATTERN = re.compile(
    r"(?:refresh[_-]?token|refreshToken)",
    re.IGNORECASE,
)

RE_TOKEN_ROTATION_PATTERN = re.compile(
    r"(?:access[_-]?token|accessToken).*(?:refresh[_-]?token|refreshToken)",
    re.DOTALL,
)


def detect_auth_flow_mismatches(
    project_root: Path,
) -> list[IntegrationMismatch]:
    """Detect mismatches between frontend and backend authentication flows.

    Checks for:
    - Login/MFA/refresh endpoints that exist in frontend but not backend
    - Challenge-token vs inline-code MFA implementation mismatches
    - Refresh token handling inconsistencies
    - Request/response shape mismatches on auth endpoints

    Args:
        project_root: Root directory of the project.

    Returns:
        A list of CRITICAL-severity ``IntegrationMismatch`` instances.
    """
    mismatches: list[IntegrationMismatch] = []
    extensions = {".ts", ".tsx", ".js", ".jsx"}
    backend_extensions = {".ts", ".js", ".py"}

    # --- Collect frontend auth endpoints and patterns ---
    fe_auth_endpoints: list[tuple[str, str, str]] = []  # (file, path, method)
    fe_mfa_style: str = ""  # "challenge_token" or "inline_code" or ""
    fe_has_refresh: bool = False

    for fpath in _iter_files(project_root, extensions, FRONTEND_SKIP_DIRS):
        content = _read_file(fpath)
        if content is None:
            continue
        rel = str(fpath)

        for m in RE_AUTH_ENDPOINT_FE.finditer(content):
            endpoint = m.group(1)
            fe_auth_endpoints.append((rel, endpoint, ""))

        if RE_MFA_CHALLENGE_TOKEN.search(content):
            fe_mfa_style = fe_mfa_style or "challenge_token"
        if RE_MFA_INLINE_CODE.search(content):
            if fe_mfa_style == "challenge_token":
                fe_mfa_style = "mixed"
            elif not fe_mfa_style:
                fe_mfa_style = "inline_code"

        if RE_REFRESH_TOKEN_PATTERN.search(content):
            fe_has_refresh = True

    # --- Collect backend auth endpoints and patterns ---
    be_auth_endpoints: list[tuple[str, str]] = []  # (file, path)
    be_mfa_style: str = ""
    be_has_refresh: bool = False

    for fpath in _iter_files(project_root, backend_extensions, BACKEND_SKIP_DIRS):
        content = _read_file(fpath)
        if content is None:
            continue
        rel = str(fpath)

        for m in RE_AUTH_ENDPOINT_BE.finditer(content):
            endpoint = m.group(1) or m.group(2)
            if endpoint:
                be_auth_endpoints.append((rel, endpoint))

        if RE_MFA_CHALLENGE_TOKEN.search(content):
            be_mfa_style = be_mfa_style or "challenge_token"
        if RE_MFA_INLINE_CODE.search(content):
            if be_mfa_style == "challenge_token":
                be_mfa_style = "mixed"
            elif not be_mfa_style:
                be_mfa_style = "inline_code"

        if RE_REFRESH_TOKEN_PATTERN.search(content):
            be_has_refresh = True

    # --- Compare MFA styles ---
    if fe_mfa_style and be_mfa_style and fe_mfa_style != be_mfa_style:
        mismatches.append(IntegrationMismatch(
            severity="CRITICAL",
            category="auth_mfa_flow_mismatch",
            frontend_file="(project-wide)",
            backend_file="(project-wide)",
            description=(
                f"MFA flow mismatch: frontend uses '{fe_mfa_style}' pattern "
                f"but backend uses '{be_mfa_style}' pattern. "
                f"Challenge-token MFA requires a two-step flow (get challenge, "
                f"then verify), while inline-code MFA sends the code directly."
            ),
            suggestion=(
                "Align MFA implementation: either both sides use challenge-token "
                "(POST /auth/mfa/challenge then POST /auth/mfa/verify with "
                "challengeToken + code) or both use inline-code (POST /auth/mfa "
                "with code only)."
            ),
        ))

    # --- Compare refresh token handling ---
    if fe_has_refresh and not be_has_refresh:
        mismatches.append(IntegrationMismatch(
            severity="CRITICAL",
            category="auth_refresh_token_missing",
            frontend_file="(project-wide)",
            backend_file="(project-wide)",
            description=(
                "Frontend implements refresh-token logic but no backend "
                "refresh-token endpoint or handling was detected. "
                "Token refresh calls will fail with 404."
            ),
            suggestion=(
                "Add a POST /auth/refresh endpoint to the backend that "
                "accepts a refresh token and returns a new access token."
            ),
        ))
    elif be_has_refresh and not fe_has_refresh:
        mismatches.append(IntegrationMismatch(
            severity="HIGH",
            category="auth_refresh_token_unused",
            frontend_file="(project-wide)",
            backend_file="(project-wide)",
            description=(
                "Backend implements refresh-token handling but frontend "
                "does not use refresh tokens. Users will be logged out "
                "when the access token expires."
            ),
            suggestion=(
                "Add refresh-token logic to the frontend HTTP client "
                "(e.g., axios interceptor that refreshes on 401)."
            ),
        ))

    # --- Compare auth endpoint availability ---
    if fe_auth_endpoints and not be_auth_endpoints:
        mismatches.append(IntegrationMismatch(
            severity="CRITICAL",
            category="auth_endpoints_missing",
            frontend_file=fe_auth_endpoints[0][0],
            backend_file="",
            description=(
                f"Frontend references {len(fe_auth_endpoints)} auth endpoint(s) "
                f"but no auth endpoints were detected in the backend."
            ),
            suggestion=(
                "Implement authentication endpoints in the backend "
                "(login, logout, refresh, etc.)."
            ),
        ))
    elif be_auth_endpoints and not fe_auth_endpoints:
        mismatches.append(IntegrationMismatch(
            severity="HIGH",
            category="auth_endpoints_unused",
            frontend_file="",
            backend_file=be_auth_endpoints[0][0],
            description=(
                f"Backend defines {len(be_auth_endpoints)} auth endpoint(s) "
                f"but no auth calls were detected in the frontend."
            ),
            suggestion=(
                "Implement authentication flow in the frontend "
                "(login form, token storage, refresh interceptor)."
            ),
        ))

    logger.info(
        "Auth flow analysis: found %d mismatches",
        len(mismatches),
    )
    return mismatches


# ---------------------------------------------------------------------------
# V2: Enum Value Cross-Check
# ---------------------------------------------------------------------------

# Prisma enum with values
RE_PRISMA_ENUM = re.compile(
    r"enum\s+(\w+)\s*\{([^}]+)\}",
    re.MULTILINE | re.DOTALL,
)

# Prisma @default("value") on enum fields
RE_PRISMA_DEFAULT_ENUM = re.compile(
    r"(\w+)\s+(\w+)\s+@default\(\s*(\w+)\s*\)",
)

# Backend DTO @IsIn(['val1', 'val2', ...]) validators
RE_BACKEND_ISIN = re.compile(
    r"@IsIn\(\s*\[([^\]]+)\]\s*\)",
)

# Backend DTO @IsEnum(EnumType) validators
RE_BACKEND_ISENUM = re.compile(
    r"@IsEnum\(\s*(\w+)\s*\)",
)

# Frontend hardcoded status/type arrays
# e.g., const STATUS_OPTIONS = ['open', 'closed', 'pending'];
# or: const types = ["corrective", "preventive", "emergency"];
RE_FRONTEND_STATUS_ARRAY = re.compile(
    r"(?:const|let|var)\s+(\w*(?:status|type|category|priority|role|state|option|kind|mode|level|phase)(?:es|s|_options|_values|_list|_types|_array)?)\s*"
    r"(?::\s*[^=]+)?\s*=\s*\[([^\]]+)\]",
    re.IGNORECASE,
)

# Frontend dropdown/select option values
# e.g., <option value="open">Open</option> or { value: 'open', label: 'Open' }
RE_FRONTEND_OPTION_VALUE = re.compile(
    r"(?:value\s*[=:]\s*)" + _Q + r"(\w+)" + _Q,
)

# TypeScript enum declaration
RE_TS_ENUM_DECL = re.compile(
    r"(?:export\s+)?enum\s+(\w+)\s*\{([^}]+)\}",
    re.MULTILINE | re.DOTALL,
)


def _parse_enum_values(body: str) -> list[str]:
    """Parse enum member values from an enum body string.

    Handles:
    - Simple identifiers: ``OPEN, CLOSED, PENDING``
    - String-assigned: ``OPEN = 'open', CLOSED = 'closed'``
    - Prisma enum: ``open\\n  closed\\n  pending``

    Returns a list of lowercase values.
    """
    values: list[str] = []
    for line in body.split("\n"):
        line = line.strip().rstrip(",")
        if not line or line.startswith("//") or line.startswith("/*"):
            continue
        # Handle assignment: OPEN = 'open' or OPEN = "open"
        if "=" in line:
            rhs = line.split("=", 1)[1].strip().strip("'\"").strip()
            if rhs:
                values.append(rhs.lower())
        else:
            # Plain identifier
            ident = line.strip().rstrip(",").strip()
            if ident and re.match(r"^\w+$", ident):
                values.append(ident.lower())
    return values


def _parse_string_list(text: str) -> list[str]:
    """Parse a list of quoted strings from text like ``'a', 'b', "c"``."""
    return [
        m.strip().lower()
        for m in re.findall(r"""['"](\w+)['"]""", text)
    ]


def detect_enum_value_mismatches(
    project_root: Path,
) -> list[IntegrationMismatch]:
    """Cross-check enum/status values between backend and frontend.

    Extracts enum values from:
    - Prisma schema enum declarations and @default() values
    - Backend DTO @IsIn([...]) validators and TypeScript enums
    - Frontend hardcoded status/type arrays and dropdown options

    Compares sets for each named enum/status group and flags mismatches.

    Args:
        project_root: Root directory of the project.

    Returns:
        A list of HIGH-severity ``IntegrationMismatch`` instances.
    """
    mismatches: list[IntegrationMismatch] = []

    # --- Collect backend enum values ---
    # key: normalized enum name -> { "values": set, "source": file }
    backend_enums: dict[str, dict] = {}
    backend_extensions = {".ts", ".js", ".prisma"}

    for fpath in _iter_files(project_root, backend_extensions, BACKEND_SKIP_DIRS):
        content = _read_file(fpath)
        if content is None:
            continue
        rel = str(fpath)

        # Prisma enums
        if fpath.suffix == ".prisma":
            for m in RE_PRISMA_ENUM.finditer(content):
                enum_name = m.group(1)
                enum_body = m.group(2)
                values = _parse_enum_values(enum_body)
                if values:
                    key = enum_name.lower()
                    backend_enums[key] = {
                        "values": set(values),
                        "source": rel,
                        "name": enum_name,
                    }

        # TypeScript enums
        for m in RE_TS_ENUM_DECL.finditer(content):
            enum_name = m.group(1)
            enum_body = m.group(2)
            values = _parse_enum_values(enum_body)
            if values:
                key = enum_name.lower()
                if key not in backend_enums:
                    backend_enums[key] = {
                        "values": set(values),
                        "source": rel,
                        "name": enum_name,
                    }
                else:
                    backend_enums[key]["values"].update(values)

        # @IsIn validators in DTOs
        for m in RE_BACKEND_ISIN.finditer(content):
            values = _parse_string_list(m.group(1))
            if values:
                # Try to find the field name following the decorator
                after = content[m.end():m.end() + 200]
                field_match = re.search(r"(\w+)\s*[?!]?\s*:", after)
                if field_match:
                    field_name = field_match.group(1)
                    key = field_name.lower()
                    if key not in backend_enums:
                        backend_enums[key] = {
                            "values": set(values),
                            "source": rel,
                            "name": field_name,
                        }
                    else:
                        backend_enums[key]["values"].update(values)

    if not backend_enums:
        logger.debug("No backend enums found; skipping enum cross-check")
        return []

    # --- Collect frontend enum values ---
    frontend_enums: dict[str, dict] = {}
    frontend_extensions = {".ts", ".tsx", ".js", ".jsx"}

    for fpath in _iter_files(project_root, frontend_extensions, FRONTEND_SKIP_DIRS):
        content = _read_file(fpath)
        if content is None:
            continue
        rel = str(fpath)

        # TypeScript enums in frontend
        for m in RE_TS_ENUM_DECL.finditer(content):
            enum_name = m.group(1)
            values = _parse_enum_values(m.group(2))
            if values:
                key = enum_name.lower()
                frontend_enums[key] = {
                    "values": set(values),
                    "source": rel,
                    "name": enum_name,
                }

        # Hardcoded status/type arrays
        for m in RE_FRONTEND_STATUS_ARRAY.finditer(content):
            var_name = m.group(1)
            values = _parse_string_list(m.group(2))
            if values:
                key = var_name.lower()
                # Normalize common suffixes
                for suffix in ("_options", "_values", "_list", "_types",
                               "_array", "options", "values", "types",
                               "es", "s"):
                    if key.endswith(suffix) and len(key) > len(suffix):
                        key = key[:-len(suffix)]
                        break
                frontend_enums[key] = {
                    "values": set(values),
                    "source": rel,
                    "name": var_name,
                }

    if not frontend_enums:
        logger.debug("No frontend enums found; skipping enum cross-check")
        return []

    # --- Cross-check: find matching enum names and compare values ---
    for fe_key, fe_data in frontend_enums.items():
        # Try exact match first, then fuzzy
        be_data = None
        be_key = None

        if fe_key in backend_enums:
            be_data = backend_enums[fe_key]
            be_key = fe_key
        else:
            # Try matching by checking if one name contains the other
            for bk, bd in backend_enums.items():
                if fe_key in bk or bk in fe_key:
                    be_data = bd
                    be_key = bk
                    break

        if be_data is None:
            continue

        fe_values = fe_data["values"]
        be_values = be_data["values"]

        # Find values in frontend but not backend
        fe_only = fe_values - be_values
        # Find values in backend but not frontend
        be_only = be_values - fe_values

        if fe_only or be_only:
            desc_parts = []
            if fe_only:
                desc_parts.append(
                    f"frontend has {sorted(fe_only)} not in backend"
                )
            if be_only:
                desc_parts.append(
                    f"backend has {sorted(be_only)} not in frontend"
                )

            mismatches.append(IntegrationMismatch(
                severity="HIGH",
                category="enum_value_mismatch",
                frontend_file=fe_data["source"],
                backend_file=be_data["source"],
                description=(
                    f"Enum value mismatch for '{fe_data['name']}' "
                    f"(backend: '{be_data['name']}'): "
                    + "; ".join(desc_parts)
                    + f". Frontend values: {sorted(fe_values)}, "
                    f"backend values: {sorted(be_values)}."
                ),
                suggestion=(
                    f"Synchronise enum values between frontend "
                    f"({fe_data['source']}) and backend ({be_data['source']}). "
                    f"Consider generating a shared types file."
                ),
            ))

    logger.info(
        "Enum cross-check: found %d mismatches",
        len(mismatches),
    )
    return mismatches


# ---------------------------------------------------------------------------
# V2: Pluralization Bug Detection
# ---------------------------------------------------------------------------

# Common irregular plurals: singular -> correct plural
_IRREGULAR_PLURALS: dict[str, str] = {
    "property": "properties",
    "category": "categories",
    "entity": "entities",
    "company": "companies",
    "warranty": "warranties",
    "policy": "policies",
    "facility": "facilities",
    "priority": "priorities",
    "inventory": "inventories",
    "activity": "activities",
    "history": "histories",
    "country": "countries",
    "currency": "currencies",
    "delivery": "deliveries",
    "identity": "identities",
    "community": "communities",
    "amenity": "amenities",
    "accessory": "accessories",
    "boundary": "boundaries",
    "discovery": "discoveries",
    "entry": "entries",
    "gallery": "galleries",
    "inquiry": "inquiries",
    "itinerary": "itineraries",
    "library": "libraries",
    "penalty": "penalties",
    "salary": "salaries",
    "strategy": "strategies",
    "territory": "territories",
    "university": "universities",
    "vacancy": "vacancies",
    "person": "people",
    "child": "children",
    "man": "men",
    "woman": "women",
    "datum": "data",
    "medium": "media",
    "criterion": "criteria",
    "analysis": "analyses",
    "index": "indices",
    "status": "statuses",
    "address": "addresses",
    "class": "classes",
    "process": "processes",
    "batch": "batches",
    "match": "matches",
    "search": "searches",
    "tax": "taxes",
    "box": "boxes",
    "bus": "buses",
    "quiz": "quizzes",
    "half": "halves",
    "leaf": "leaves",
    "shelf": "shelves",
    "staff": "staff",
}

# Build reverse lookup: wrong naive plural -> (correct plural, singular)
_NAIVE_PLURAL_ERRORS: dict[str, tuple[str, str]] = {}
for _singular, _correct_plural in _IRREGULAR_PLURALS.items():
    # Naive pluralization: just add 's'
    _naive = _singular + "s"
    if _naive != _correct_plural:
        _NAIVE_PLURAL_ERRORS[_naive] = (_correct_plural, _singular)
    # Also handle naive 'es' for words ending in consonant
    _naive_es = _singular + "es"
    if _naive_es != _correct_plural and _naive_es != _naive:
        _NAIVE_PLURAL_ERRORS[_naive_es] = (_correct_plural, _singular)


def detect_pluralization_bugs(
    frontend_calls: list[FrontendAPICall],
    backend_endpoints: list[BackendEndpoint],
) -> list[IntegrationMismatch]:
    """Detect incorrect pluralization in route paths.

    Catches common bugs like ``/propertys`` instead of ``/properties``,
    ``/categorys`` instead of ``/categories``, etc.

    Scans both frontend API calls and backend endpoint definitions.

    Args:
        frontend_calls: Parsed frontend API calls.
        backend_endpoints: Parsed backend endpoint definitions.

    Returns:
        A list of HIGH-severity ``IntegrationMismatch`` instances.
    """
    mismatches: list[IntegrationMismatch] = []
    seen: set[str] = set()

    def _check_path(path: str, file_path: str, side: str) -> None:
        segments = [s for s in path.lower().split("/") if s and s != ":param"]
        for seg in segments:
            # Skip path params
            if seg.startswith(":") or seg.startswith("{") or seg.startswith("$"):
                continue
            if seg in _NAIVE_PLURAL_ERRORS:
                correct, singular = _NAIVE_PLURAL_ERRORS[seg]
                dedup = f"{seg}|{file_path}"
                if dedup in seen:
                    continue
                seen.add(dedup)
                mismatches.append(IntegrationMismatch(
                    severity="HIGH",
                    category="pluralization_error",
                    frontend_file=file_path if side == "frontend" else "",
                    backend_file=file_path if side == "backend" else "",
                    description=(
                        f"Incorrect pluralization in route: '/{seg}' should be "
                        f"'/{correct}' (plural of '{singular}'). "
                        f"This will cause 404 errors."
                    ),
                    suggestion=(
                        f"Rename the route segment from '/{seg}' to '/{correct}'."
                    ),
                ))

    for call in frontend_calls:
        _check_path(call.endpoint_path, call.file_path, "frontend")

    for ep in backend_endpoints:
        _check_path(ep.route_path, ep.file_path, "backend")

    logger.info(
        "Pluralization check: found %d errors",
        len(mismatches),
    )
    return mismatches


# ---------------------------------------------------------------------------
# V2: Query Parameter Alias Detection
# ---------------------------------------------------------------------------

# Common query parameter aliases that often cause mismatches
# Maps (frontend_name, backend_name) pairs that refer to the same concept
_QUERY_PARAM_ALIASES: list[tuple[str, str]] = [
    ("dateFrom", "from"),
    ("dateTo", "to"),
    ("startDate", "from"),
    ("endDate", "to"),
    ("start_date", "from"),
    ("end_date", "to"),
    ("dateFrom", "start_date"),
    ("dateTo", "end_date"),
    ("dateFrom", "startDate"),
    ("dateTo", "endDate"),
    ("pageSize", "limit"),
    ("page_size", "limit"),
    ("perPage", "limit"),
    ("per_page", "limit"),
    ("pageNumber", "page"),
    ("page_number", "page"),
    ("sortBy", "sort"),
    ("sort_by", "sort"),
    ("sortOrder", "order"),
    ("sort_order", "order"),
    ("orderBy", "sort"),
    ("order_by", "sort"),
    ("searchQuery", "search"),
    ("search_query", "search"),
    ("q", "search"),
    ("query", "search"),
    ("filterBy", "filter"),
    ("filter_by", "filter"),
    ("category_id", "categoryId"),
    ("building_id", "buildingId"),
    ("tenant_id", "tenantId"),
]


def detect_query_param_alias_mismatches(
    frontend_calls: list[FrontendAPICall],
    backend_endpoints: list[BackendEndpoint],
) -> list[IntegrationMismatch]:
    """Detect query parameter alias mismatches between frontend and backend.

    Checks for common naming patterns where frontend and backend use different
    names for the same concept (e.g., ``dateFrom``/``dateTo`` vs ``from``/``to``).

    Args:
        frontend_calls: Parsed frontend API calls.
        backend_endpoints: Parsed backend endpoint definitions.

    Returns:
        A list of HIGH-severity ``IntegrationMismatch`` instances.
    """
    mismatches: list[IntegrationMismatch] = []

    # Build alias lookup: for each param name, what other names could it map to?
    alias_map: dict[str, set[str]] = {}
    for a, b in _QUERY_PARAM_ALIASES:
        alias_map.setdefault(a.lower(), set()).add(b.lower())
        alias_map.setdefault(b.lower(), set()).add(a.lower())

    # Build backend param index: normalized_path -> set of accepted param names
    backend_params_by_path: dict[str, tuple[set[str], BackendEndpoint]] = {}
    for ep in backend_endpoints:
        norm = normalize_path(ep.route_path)
        stripped = _strip_api_prefix(norm)
        for key in (norm, stripped):
            if ep.accepted_params:
                backend_params_by_path[key] = (
                    {p.lower() for p in ep.accepted_params},
                    ep,
                )

    seen: set[str] = set()

    for call in frontend_calls:
        if not call.query_params:
            continue

        norm = normalize_path(call.endpoint_path)
        stripped = _strip_api_prefix(norm)

        be_data = backend_params_by_path.get(norm) or backend_params_by_path.get(stripped)
        if be_data is None:
            continue

        be_params, ep = be_data

        for fp in call.query_params:
            fp_lower = fp.lower()
            # Already matches exactly
            if fp_lower in be_params:
                continue

            # Check if any known alias matches a backend param
            aliases = alias_map.get(fp_lower, set())
            for alias in aliases:
                if alias in be_params:
                    # Find the original-case backend param
                    be_original = next(
                        (p for p in ep.accepted_params if p.lower() == alias),
                        alias,
                    )
                    dedup = f"{fp}|{be_original}|{norm}"
                    if dedup in seen:
                        continue
                    seen.add(dedup)
                    mismatches.append(IntegrationMismatch(
                        severity="HIGH",
                        category="query_param_alias_mismatch",
                        frontend_file=call.file_path,
                        backend_file=ep.file_path,
                        description=(
                            f"Query parameter alias mismatch: frontend sends "
                            f"'{fp}' but backend expects '{be_original}' "
                            f"for {call.http_method} {call.endpoint_path}. "
                            f"These are common aliases for the same concept."
                        ),
                        suggestion=(
                            f"Align parameter names: change frontend '{fp}' to "
                            f"'{be_original}' or update backend to accept '{fp}'."
                        ),
                    ))
                    break

    logger.info(
        "Query param alias check: found %d mismatches",
        len(mismatches),
    )
    return mismatches


# ---------------------------------------------------------------------------
# V2: RoutePatternEnforcer — class-based route violation detection
# ---------------------------------------------------------------------------

@dataclass
class RoutePatternViolation:
    """A specific route pattern violation with a typed violation code."""
    violation_type: str   # "ROUTE-001" | "ROUTE-002" | "ROUTE-003" | "ROUTE-004"
    frontend_path: str    # The path the frontend calls
    backend_path: str | None  # The closest backend match (or None)
    frontend_file: str    # Source file
    severity: str         # "CRITICAL" | "HIGH"
    suggestion: str       # Actionable fix suggestion


# Similarity threshold for ROUTE-004 fuzzy action path matching
_ROUTE_SIMILARITY_THRESHOLD = 0.6


class RoutePatternEnforcer:
    """Detects route pattern violations between frontend calls and backend endpoints.

    Violation codes:
    - ROUTE-001: Frontend calls nested route, backend only has top-level (CRITICAL)
    - ROUTE-002: Frontend calls endpoint that does not exist (CRITICAL)
    - ROUTE-003: Singular/plural path segment mismatch (HIGH)
    - ROUTE-004: Frontend uses different action path than backend (HIGH)

    This is an ADDITIONAL layer on top of existing mismatch detection.
    It does NOT replace existing fuzzy matching.
    """

    # Common nested patterns: /parent/:id/child -> top-level /child
    NESTED_ROUTE_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r'/(\w+)/:[^/]+/(\w+)'), 'nested_resource'),
        (re.compile(r'/(\w+)/:[^/]+/(\w+)/:[^/]+'), 'nested_resource_with_id'),
    ]

    def __init__(
        self,
        frontend_calls: list[FrontendAPICall],
        backend_endpoints: list[BackendEndpoint],
    ) -> None:
        self.frontend_calls = frontend_calls
        self.backend_endpoints = backend_endpoints

        # Build backend lookup structures once
        self._backend_norm_paths: set[tuple[str, str]] = set()
        self._backend_by_method: dict[str, list[BackendEndpoint]] = {}
        self._backend_by_resource: dict[tuple[str, str], list[BackendEndpoint]] = {}

        for ep in backend_endpoints:
            norm = normalize_path(ep.route_path)
            stripped = _strip_api_prefix(norm)
            self._backend_norm_paths.add((norm, ep.http_method))
            self._backend_norm_paths.add((stripped, ep.http_method))
            self._backend_by_method.setdefault(ep.http_method, []).append(ep)
            segments = _extract_resource_segments(ep.route_path)
            if segments:
                key = (segments[-1].lower(), ep.http_method)
                self._backend_by_resource.setdefault(key, []).append(ep)

    @classmethod
    def from_raw_paths(
        cls,
        frontend_paths: list[tuple[str, str]],
        backend_paths: list[tuple[str, str]],
    ) -> "RoutePatternEnforcer":
        """Create an enforcer from raw (path, method) tuples.

        This allows the pre-coding gate to use the enforcer with data
        from API_CONTRACTS.json and SVC-xxx entries without needing
        full ``FrontendAPICall`` / ``BackendEndpoint`` objects.

        Args:
            frontend_paths: List of ``(endpoint_path, http_method)`` tuples.
            backend_paths: List of ``(route_path, http_method)`` tuples.

        Returns:
            A configured ``RoutePatternEnforcer`` instance.
        """
        frontend_calls = [
            FrontendAPICall(
                file_path="<pre-coding-gate>",
                line_number=0,
                endpoint_path=path,
                http_method=method.upper(),
                request_fields=[],
                expected_response_fields=[],
            )
            for path, method in frontend_paths
        ]
        backend_endpoints = [
            BackendEndpoint(
                file_path="<api-contracts>",
                route_path=path,
                http_method=method.upper(),
                handler_name="",
                accepted_params=[],
                response_fields=[],
            )
            for path, method in backend_paths
        ]
        return cls(frontend_calls, backend_endpoints)

    def check(self) -> list[RoutePatternViolation]:
        """Run all route pattern checks and return violations."""
        violations: list[RoutePatternViolation] = []
        seen: set[str] = set()

        for call in self.frontend_calls:
            fe_norm = normalize_path(call.endpoint_path)
            fe_stripped = _strip_api_prefix(fe_norm)

            # Check exact match first
            has_exact = (
                (fe_norm, call.http_method) in self._backend_norm_paths
                or (fe_stripped, call.http_method) in self._backend_norm_paths
            )
            if has_exact:
                # Even with exact match, check ROUTE-003 (plural mismatch)
                v003 = self._check_route_003(call, seen)
                if v003:
                    violations.extend(v003)
                continue

            fe_segments = _extract_resource_segments(call.endpoint_path)
            if not fe_segments:
                continue

            last_resource = fe_segments[-1].lower()
            key = (last_resource, call.http_method)

            # ROUTE-001: nested frontend, flat backend
            if _is_nested_route(call.endpoint_path) and key in self._backend_by_resource:
                found_001 = False
                for ep in self._backend_by_resource[key]:
                    if not _is_nested_route(ep.route_path):
                        dedup = f"001|{call.endpoint_path}|{ep.route_path}"
                        if dedup not in seen:
                            seen.add(dedup)
                            violations.append(RoutePatternViolation(
                                violation_type="ROUTE-001",
                                frontend_path=call.endpoint_path,
                                backend_path=ep.route_path,
                                frontend_file=call.file_path,
                                severity="CRITICAL",
                                suggestion=(
                                    f"Frontend uses nested route '{call.endpoint_path}', "
                                    f"but backend only has top-level '{ep.route_path}'. "
                                    f"Either add a nested route alias on the backend "
                                    f"controller, or change the frontend to call "
                                    f"'{ep.route_path}' with parent_id as a query parameter."
                                ),
                            ))
                            found_001 = True
                if found_001:
                    continue

            # ROUTE-004: fuzzy action path mismatch (e.g. /test vs /test-connection)
            v004 = self._check_route_004(call, fe_segments, seen)
            if v004:
                violations.extend(v004)
                continue

            # ROUTE-003: plural mismatch when no exact match
            v003 = self._check_route_003(call, seen)
            if v003:
                violations.extend(v003)
                continue

            # ROUTE-002: frontend calls endpoint that does not exist at all
            dedup = f"002|{call.http_method}|{call.endpoint_path}"
            if dedup not in seen:
                seen.add(dedup)
                violations.append(RoutePatternViolation(
                    violation_type="ROUTE-002",
                    frontend_path=call.endpoint_path,
                    backend_path=None,
                    frontend_file=call.file_path,
                    severity="CRITICAL",
                    suggestion=(
                        f"Frontend calls {call.http_method} {call.endpoint_path} "
                        f"but no backend endpoint exists. Add the endpoint or "
                        f"remove the frontend call."
                    ),
                ))

        logger.info(
            "RoutePatternEnforcer: found %d violations "
            "(ROUTE-001: %d, ROUTE-002: %d, ROUTE-003: %d, ROUTE-004: %d)",
            len(violations),
            sum(1 for v in violations if v.violation_type == "ROUTE-001"),
            sum(1 for v in violations if v.violation_type == "ROUTE-002"),
            sum(1 for v in violations if v.violation_type == "ROUTE-003"),
            sum(1 for v in violations if v.violation_type == "ROUTE-004"),
        )
        return violations

    def _check_route_003(
        self,
        call: FrontendAPICall,
        seen: set[str],
    ) -> list[RoutePatternViolation]:
        """Check for singular/plural segment mismatches (ROUTE-003)."""
        violations: list[RoutePatternViolation] = []
        fe_segments = _extract_resource_segments(call.endpoint_path)
        if not fe_segments:
            return violations

        for ep in self._backend_by_method.get(call.http_method, []):
            be_segments = _extract_resource_segments(ep.route_path)
            if not be_segments:
                continue
            # Same number of segments but last differs by plural
            if len(fe_segments) == len(be_segments):
                for fe_seg, be_seg in zip(fe_segments, be_segments):
                    fe_low = fe_seg.lower()
                    be_low = be_seg.lower()
                    if fe_low == be_low:
                        continue
                    # Check if one is a pluralization variant of the other
                    if self._is_plural_variant(fe_low, be_low):
                        dedup = f"003|{fe_low}|{be_low}"
                        if dedup not in seen:
                            seen.add(dedup)
                            violations.append(RoutePatternViolation(
                                violation_type="ROUTE-003",
                                frontend_path=call.endpoint_path,
                                backend_path=ep.route_path,
                                frontend_file=call.file_path,
                                severity="HIGH",
                                suggestion=(
                                    f"Plural mismatch: frontend uses '/{fe_seg}' "
                                    f"but backend uses '/{be_seg}'. "
                                    f"Align the path segment names."
                                ),
                            ))
        return violations

    def _check_route_004(
        self,
        call: FrontendAPICall,
        fe_segments: list[str],
        seen: set[str],
    ) -> list[RoutePatternViolation]:
        """Check for fuzzy action path mismatches (ROUTE-004).

        Catches cases like ``/integrations/:id/test`` vs
        ``/integrations/:id/test-connection`` where the action suffix
        is similar but not identical.
        """
        violations: list[RoutePatternViolation] = []
        fe_norm = normalize_path(call.endpoint_path)
        fe_stripped = _strip_api_prefix(fe_norm)

        for ep in self._backend_by_method.get(call.http_method, []):
            be_norm = normalize_path(ep.route_path)
            be_stripped = _strip_api_prefix(be_norm)

            # Already an exact match (handled above)
            if fe_norm == be_norm or fe_stripped == be_stripped:
                continue
            if fe_stripped == be_norm or fe_norm == be_stripped:
                continue

            be_segments = _extract_resource_segments(ep.route_path)
            if not be_segments:
                continue

            # Must have the same number of segments to be a fuzzy match
            if len(fe_segments) != len(be_segments):
                continue

            # All segments except one must match exactly
            diff_indices = [
                i for i, (a, b) in enumerate(zip(fe_segments, be_segments))
                if a.lower() != b.lower()
            ]
            if len(diff_indices) != 1:
                continue

            idx = diff_indices[0]
            fe_action = fe_segments[idx].lower()
            be_action = be_segments[idx].lower()

            # Skip if it's a plural mismatch (handled by ROUTE-003)
            if self._is_plural_variant(fe_action, be_action):
                continue

            # Fuzzy similarity check: use SequenceMatcher ratio OR
            # prefix/hyphenated-extension match (e.g. "test" vs "test-connection")
            ratio = SequenceMatcher(None, fe_action, be_action).ratio()
            is_prefix_match = (
                fe_action.startswith(be_action + "-")
                or fe_action.startswith(be_action + "_")
                or be_action.startswith(fe_action + "-")
                or be_action.startswith(fe_action + "_")
            )
            if ratio >= _ROUTE_SIMILARITY_THRESHOLD or is_prefix_match:
                dedup = f"004|{fe_action}|{be_action}"
                if dedup not in seen:
                    seen.add(dedup)
                    violations.append(RoutePatternViolation(
                        violation_type="ROUTE-004",
                        frontend_path=call.endpoint_path,
                        backend_path=ep.route_path,
                        frontend_file=call.file_path,
                        severity="HIGH",
                        suggestion=(
                            f"Action path mismatch: frontend uses '/{fe_action}' "
                            f"but backend uses '/{be_action}' "
                            f"(similarity: {ratio:.0%}). These look like the same "
                            f"action with different naming. Align the path segment."
                        ),
                    ))
        return violations

    @staticmethod
    def _is_plural_variant(a: str, b: str) -> bool:
        """Check if *a* and *b* are singular/plural variants of each other."""
        if a == b:
            return False
        # Simple heuristic: one ends with 's' and stripping it gives the other
        if a.endswith("s") and a[:-1] == b:
            return True
        if b.endswith("s") and b[:-1] == a:
            return True
        # 'ies' / 'y' variant
        if a.endswith("ies") and a[:-3] + "y" == b:
            return True
        if b.endswith("ies") and b[:-3] + "y" == a:
            return True
        # 'es' variant for words ending in s/x/z/ch/sh
        if a.endswith("es") and a[:-2] == b:
            return True
        if b.endswith("es") and b[:-2] == a:
            return True
        # Check against known irregular plurals
        if a in _IRREGULAR_PLURALS and _IRREGULAR_PLURALS[a] == b:
            return True
        if b in _IRREGULAR_PLURALS and _IRREGULAR_PLURALS[b] == a:
            return True
        # Reverse lookup: if a is a known plural form
        if a in _IRREGULAR_PLURALS.values():
            for sing, plur in _IRREGULAR_PLURALS.items():
                if plur == a and sing == b:
                    return True
        if b in _IRREGULAR_PLURALS.values():
            for sing, plur in _IRREGULAR_PLURALS.items():
                if plur == b and sing == a:
                    return True
        return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def verify_integration(
    project_root: Path,
    skip_dirs: set[str] | None = None,
    run_mode: str = "warn",
    checks_config: VerificationChecksConfig | None = None,
) -> IntegrationReport | BlockingGateResult:
    """Run the full frontend-backend integration verification pipeline.

    1. Scan frontend files for API calls.
    2. Scan backend files for endpoint definitions.
    3. Match and diff to produce an ``IntegrationReport``.
    4. Detect project-wide field naming convention mismatches.
    5. Detect inconsistent response shape / envelope patterns.
    6. (V2) Detect route structure mismatches.
    7. (V2) Validate response shape consistency.
    8. (V2) Check auth flow compatibility.
    9. (V2) Cross-check enum values.
    10. (V2) RoutePatternEnforcer: ROUTE-001..004 violation detection.

    Args:
        project_root: Root directory of the project to verify.
        skip_dirs: Optional set of directory names to skip during scanning.
            When provided, used for both frontend and backend scans.
            Defaults to module-level FRONTEND_SKIP_DIRS / BACKEND_SKIP_DIRS.
        run_mode: ``"warn"`` (default, log and continue) or ``"block"``
            (return a ``BlockingGateResult`` that cli.py can use to fail
            the milestone on HIGH/CRITICAL findings).
        checks_config: Optional config to toggle individual V2 checks.
            Defaults to all checks enabled.

    Returns:
        In ``"warn"`` mode: an ``IntegrationReport`` (backward compatible).
        In ``"block"`` mode: a ``BlockingGateResult`` wrapping the report.
    """
    logger.info("Starting integration verification for %s (mode=%s)", project_root, run_mode)
    _checks = checks_config or VerificationChecksConfig()

    frontend_calls = scan_frontend_api_calls(project_root, skip_dirs=skip_dirs)
    backend_endpoints = scan_backend_endpoints(project_root, skip_dirs=skip_dirs)
    report = match_endpoints(frontend_calls, backend_endpoints)

    # --- Gap 3: Project-wide field naming analysis ---
    field_naming_issues = detect_field_naming_mismatches(project_root)
    if field_naming_issues:
        report.field_name_mismatches.extend(field_naming_issues)

    # --- Gap 3: Response shape inconsistency detection ---
    response_shape_issues = detect_response_shape_mismatches(project_root)
    if response_shape_issues:
        report.mismatches.extend(response_shape_issues)

    # --- Prisma missing-include detection ---
    prisma_include_issues = detect_missing_prisma_includes(
        project_root, skip_dirs=skip_dirs
    )
    if prisma_include_issues:
        report.mismatches.extend(prisma_include_issues)

    # --- V2: Route structure consistency check ---
    if _checks.route_structure:
        route_structure_issues = detect_route_structure_mismatches(
            frontend_calls, backend_endpoints,
        )
        if route_structure_issues:
            report.mismatches.extend(route_structure_issues)

    # --- V2: Response shape validation ---
    if _checks.response_shape_validation:
        response_validation_issues = detect_response_shape_validation_issues(
            project_root, frontend_calls, backend_endpoints,
        )
        if response_validation_issues:
            report.mismatches.extend(response_validation_issues)

    # --- V2: Auth flow compatibility ---
    if _checks.auth_flow:
        auth_flow_issues = detect_auth_flow_mismatches(project_root)
        if auth_flow_issues:
            report.mismatches.extend(auth_flow_issues)

    # --- V2: Enum value cross-check ---
    if _checks.enum_cross_check:
        enum_issues = detect_enum_value_mismatches(project_root)
        if enum_issues:
            report.mismatches.extend(enum_issues)

    # --- V2: Pluralization bug detection ---
    plural_issues = detect_pluralization_bugs(frontend_calls, backend_endpoints)
    if plural_issues:
        report.mismatches.extend(plural_issues)

    # --- V2: Query parameter alias detection ---
    alias_issues = detect_query_param_alias_mismatches(
        frontend_calls, backend_endpoints,
    )
    if alias_issues:
        report.mismatches.extend(alias_issues)

    # --- V2: RoutePatternEnforcer (additional class-based layer) ---
    enforcer = RoutePatternEnforcer(frontend_calls, backend_endpoints)
    route_violations = enforcer.check()
    for v in route_violations:
        # Convert RoutePatternViolation to IntegrationMismatch for the report
        report.mismatches.append(IntegrationMismatch(
            severity=v.severity,
            category=f"route_pattern_{v.violation_type.lower().replace('-', '_')}",
            frontend_file=v.frontend_file,
            backend_file=v.backend_path or "",
            description=(
                f"[{v.violation_type}] Route pattern violation: "
                f"frontend calls {v.frontend_path}"
                + (f", backend has {v.backend_path}" if v.backend_path else "")
                + f". {v.suggestion}"
            ),
            suggestion=v.suggestion,
        ))

    # --- Compute severity counts ---
    critical_count = sum(1 for m in report.mismatches if m.severity == "CRITICAL")
    high_count = sum(1 for m in report.mismatches if m.severity == "HIGH")
    medium_count = (
        sum(1 for m in report.mismatches if m.severity == "MEDIUM")
        + len(report.field_name_mismatches)
    )
    low_count = sum(1 for m in report.mismatches if m.severity == "LOW")

    logger.info(
        "Integration verification complete: %d matched, "
        "%d CRITICAL / %d HIGH / %d MEDIUM / %d LOW issues",
        report.matched,
        critical_count,
        high_count,
        medium_count,
        low_count,
    )

    if run_mode == "block":
        passed = critical_count == 0 and high_count == 0
        reason = ""
        if not passed:
            parts = []
            if critical_count:
                parts.append(f"{critical_count} CRITICAL")
            if high_count:
                parts.append(f"{high_count} HIGH")
            reason = f"Integration gate failed: {' + '.join(parts)} severity issues"
        return BlockingGateResult(
            passed=passed,
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            reason=reason,
            findings=[
                m for m in report.mismatches
                if m.severity in ("CRITICAL", "HIGH")
            ],
            report=report,
        )

    return report


def run_blocking_gate(
    project_root: Path,
    skip_dirs: set[str] | None = None,
) -> BlockingGateResult:
    """Convenience wrapper: run integration verification in blocking mode.

    Returns a ``BlockingGateResult`` indicating whether the milestone
    should proceed (``passed=True``) or be marked FAILED (``passed=False``).
    """
    result = verify_integration(
        project_root,
        skip_dirs=skip_dirs,
        run_mode="block",
    )
    if isinstance(result, BlockingGateResult):
        return result
    # Fallback: if verify_integration returned IntegrationReport (shouldn't happen)
    return BlockingGateResult(
        passed=True,
        critical_count=0,
        high_count=0,
        medium_count=0,
        low_count=0,
        reason="",
        report=result if isinstance(result, IntegrationReport) else None,
    )
