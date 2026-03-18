"""Anti-pattern spot checker for Agent Team (Agent 19).

Scans project source files for common anti-patterns using compiled regex
patterns and returns a list of violations.  Each check targets a specific
anti-pattern from the code quality standards (FRONT-xxx, BACK-xxx, SLOP-xxx).

All checks are regex-based, require no external dependencies (stdlib only),
and are designed to run quickly as a non-blocking advisory phase inside the
progressive verification pipeline (see ``verification.py`` Phase 6).

Typical usage::

    from pathlib import Path
    from agent_team_v15.quality_checks import run_spot_checks

    violations = run_spot_checks(Path("/path/to/project"))
    for v in violations:
        print(f"[{v.check}] {v.message} at {v.file_path}:{v.line}")
"""

from __future__ import annotations

import collections
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ScanScope:
    """Controls which files a scan examines.

    When passed to a scan function, limits scanning to the specified files
    instead of walking the entire project tree.  When ``None`` is passed
    (the default), scans behave identically to the original full-project mode.

    Attributes:
        mode: "full" (scan everything), "changed_only" (only changed files),
              or "changed_and_imports" (changed files + their importers).
        changed_files: Absolute paths of files changed since last commit.
    """

    mode: str = "full"
    changed_files: list[Path] = field(default_factory=list)


def compute_changed_files(project_root: Path) -> list[Path]:
    """Compute files changed since last commit + untracked new files.

    Uses ``git diff --name-only HEAD`` for modified files and
    ``git ls-files --others --exclude-standard`` for new untracked files.

    Returns absolute paths. Returns an empty list if:
    - Not a git repository
    - git is not available
    - Any subprocess error occurs

    An empty list signals the caller to fall back to full-project scanning.
    """
    try:
        diff_output = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=project_root,
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL,
        ).strip()
        untracked = subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=project_root,
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL,
        ).strip()
        files: list[Path] = []
        for line in (diff_output + "\n" + untracked).splitlines():
            line = line.strip()
            if line:
                files.append((project_root / line).resolve())
        return files
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return []


@dataclass
class Violation:
    """A single anti-pattern violation detected during spot checking."""

    check: str       # e.g. "FRONT-007", "BACK-002", "SLOP-003"
    message: str     # Human-readable description
    file_path: str   # Relative path to the file (POSIX-normalized)
    line: int        # Line number where the pattern was found
    severity: str    # "error" | "warning" | "info"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_VIOLATIONS = 500

_MAX_FILE_SIZE = 100_000  # 100 KB — skip files larger than this

EXCLUDED_DIRS: frozenset[str] = frozenset({
    ".venv", "venv", "node_modules", "__pycache__", ".git",
    "dist", "build", "vendor", ".tox", ".mypy_cache", ".pytest_cache",
    "site-packages", ".egg-info", ".next", "env", ".angular",
    "coverage", ".nuxt", ".output", ".svelte-kit",
})

# Mutable module-level skip set.  Starts as EXCLUDED_DIRS; callers can
# extend it via ``configure_scan_exclusions()`` to merge config-driven dirs.
_SKIP_DIRS: frozenset[str] = EXCLUDED_DIRS


def configure_scan_exclusions(extra_dirs: list[str] | None = None) -> None:
    """Merge user-configured exclusion directories into the module skip set.

    Call this once from the CLI before invoking any scan functions.
    The merged set is used by *all* scan functions (``_iter_source_files``,
    ``_should_skip_dir``, ``_path_in_excluded_dir``, and the XREF skip set).

    Args:
        extra_dirs: Additional directory names to exclude (from config
            ``post_orchestration_scans.scan_exclude_dirs``).  ``None`` or
            an empty list is a no-op.
    """
    global _SKIP_DIRS, _XREF_SKIP_PARTS  # noqa: PLW0603
    if extra_dirs:
        _SKIP_DIRS = EXCLUDED_DIRS | frozenset(extra_dirs)
    else:
        _SKIP_DIRS = EXCLUDED_DIRS
    # Keep XREF skip set in sync
    _XREF_SKIP_PARTS = _SKIP_DIRS | frozenset({".env"})

_SEVERITY_ORDER: dict[str, int] = {
    "error": 0,
    "warning": 1,
    "info": 2,
}


# ---------------------------------------------------------------------------
# Fix loop intelligence (v16) — unfixable classification + repeat detection
# ---------------------------------------------------------------------------

# Violation code prefixes that indicate infrastructure issues unfixable by code edits
_UNFIXABLE_PREFIXES = (
    "DEPLOY-",      # Deployment config (Docker/nginx port/env mismatches)
    "ASSET-",       # Broken asset references (build artifacts, missing files)
)

# Message substrings indicating violations that code-level fix passes cannot address
_UNFIXABLE_MESSAGE_PATTERNS = [
    "docker",
    "dockerfile",
    "no such file or directory",
    "npm run build",
    "package-lock.json",
    "requirements.txt not found",
    "nginx.conf",
    "permission denied",
    "enoent",
]

# Module-level cache for violation signatures between fix passes.
# Keyed by scan type name (e.g., "mock_data_scan", "handler_completeness_scan").
_previous_signatures: dict[str, frozenset] = {}


def is_fixable_violation(v: Violation) -> bool:
    """Return True if a violation can be addressed by a code-level fix pass.

    Returns False for infrastructure/Docker/deployment violations and
    violations with known unfixable message patterns.

    Adapted from super-team pipeline.py ``_is_fixable_violation()``.
    """
    if any(v.check.startswith(pfx) for pfx in _UNFIXABLE_PREFIXES):
        return False
    msg_lower = v.message.lower()
    for pattern in _UNFIXABLE_MESSAGE_PATTERNS:
        if pattern in msg_lower:
            return False
    return True


# Violation classification categories
FIXABLE_CODE = "FIXABLE_CODE"        # Missing import, wrong field name, missing validation
FIXABLE_LOGIC = "FIXABLE_LOGIC"      # Stub handler needing business logic implementation
UNFIXABLE_INFRA = "UNFIXABLE_INFRA"  # Docker build, lockfile, deployment config
UNFIXABLE_ARCH = "UNFIXABLE_ARCH"    # Architectural issue requiring milestone re-run

# Check prefixes that indicate logic-level fixes (stubs, mocks)
_LOGIC_FIX_PREFIXES = ("STUB-", "MOCK-")

# Check prefixes that indicate architectural issues
_ARCH_PREFIXES = ("ENTITY-001",)  # Missing model = needs milestone re-run


def classify_violation(v: Violation) -> str:
    """Classify a violation into one of four categories.

    Categories:
        FIXABLE_CODE: Code-level fix (wrong field name, missing import, validation)
        FIXABLE_LOGIC: Logic-level fix (stub handler, mock data replacement)
        UNFIXABLE_INFRA: Infrastructure issue (Docker, lockfile, deployment)
        UNFIXABLE_ARCH: Architectural issue (missing entity model, redesign needed)

    Returns one of the category constants.
    """
    # Check infrastructure-unfixable first
    if not is_fixable_violation(v):
        return UNFIXABLE_INFRA

    # Check if it's an architectural issue
    if any(v.check.startswith(pfx) for pfx in _ARCH_PREFIXES):
        return UNFIXABLE_ARCH

    # Check if it requires logic implementation (stubs, mocks)
    if any(v.check.startswith(pfx) for pfx in _LOGIC_FIX_PREFIXES):
        return FIXABLE_LOGIC

    # Default: code-level fix
    return FIXABLE_CODE


def get_violation_signature(violations: list[Violation]) -> frozenset:
    """Create a hashable signature of a violation set for repeat detection.

    The signature captures the essential identity of each violation (check code,
    file path, and first 50 chars of message) so that identical violation sets
    across fix passes can be detected and the loop stopped.

    Adapted from super-team pipeline.py ``_get_violation_signature()``.
    """
    return frozenset(
        (v.check, v.file_path, v.message[:50])
        for v in violations
    )


def filter_fixable_violations(
    violations: list[Violation],
    scan_name: str = "",
) -> tuple[list[Violation], bool]:
    """Filter to fixable-only violations and detect repeats.

    Returns ``(fixable_violations, should_skip)`` where *should_skip* is True
    if the violation set is identical to the previous call for the same
    *scan_name* (meaning fixes are not making progress).

    Usage in a fix loop::

        fixable, should_skip = filter_fixable_violations(violations, "mock_data_scan")
        if should_skip or not fixable:
            break  # stop fix loop
    """
    fixable = [v for v in violations if is_fixable_violation(v)]
    if not fixable:
        return fixable, True  # Nothing fixable — skip

    if scan_name:
        sig = get_violation_signature(fixable)
        prev = _previous_signatures.get(scan_name)
        if prev is not None and sig == prev:
            return fixable, True  # Same as previous pass — not making progress
        _previous_signatures[scan_name] = sig

    return fixable, False


def reset_fix_signatures() -> None:
    """Clear all stored violation signatures. Call at the start of a new run."""
    _previous_signatures.clear()
    _fix_attempt_counts.clear()


# ---------------------------------------------------------------------------
# Fix attempt tracking (v16 Phase 3.3)
# ---------------------------------------------------------------------------

# Track how many fix attempts each violation has had.
# Keyed by (check, file_path, message[:50]) tuple.
_fix_attempt_counts: dict[tuple[str, str, str], int] = {}

# After this many attempts, mark as persistent (unfixable)
MAX_FIX_ATTEMPTS = 2


def _violation_key(v: Violation) -> tuple[str, str, str]:
    """Create a stable key for tracking fix attempts per violation."""
    return (v.check, v.file_path, v.message[:50])


def track_fix_attempt(violations: list[Violation]) -> None:
    """Record that a fix pass was attempted for the given violations.

    Call this AFTER dispatching a fix agent for these violations.
    """
    for v in violations:
        key = _violation_key(v)
        _fix_attempt_counts[key] = _fix_attempt_counts.get(key, 0) + 1


def get_persistent_violations(violations: list[Violation]) -> list[Violation]:
    """Return violations that have exceeded MAX_FIX_ATTEMPTS.

    These violations have been attempted multiple times without resolution
    and should be treated as unfixable for this run.
    """
    return [
        v for v in violations
        if _fix_attempt_counts.get(_violation_key(v), 0) >= MAX_FIX_ATTEMPTS
    ]


def filter_non_persistent(violations: list[Violation]) -> list[Violation]:
    """Return violations that have NOT exceeded MAX_FIX_ATTEMPTS.

    Use this to exclude persistent violations before dispatching a fix pass.
    """
    return [
        v for v in violations
        if _fix_attempt_counts.get(_violation_key(v), 0) < MAX_FIX_ATTEMPTS
    ]


# ---------------------------------------------------------------------------
# Compiled regex patterns (module-level for reuse)
# ---------------------------------------------------------------------------

# FRONT-007: TypeScript `any` type usage
_RE_TS_ANY = re.compile(r":\s*any\b")

# BACK-002: N+1 query patterns (for-await loops or await-find-for patterns)
_RE_N_PLUS_1_FOR_AWAIT = re.compile(r"for[\s(].*await\s")
_RE_N_PLUS_1_AWAIT_FIND = re.compile(r"await.*\.find.*for")

# BACK-001: SQL string concatenation (injection risk)
_RE_SQL_CONCAT_PREFIX = re.compile(
    r"\+\s*['\"].*(?:SELECT|INSERT|UPDATE|DELETE)", re.IGNORECASE
)
_RE_SQL_CONCAT_SUFFIX = re.compile(
    r"(?:SELECT|INSERT|UPDATE|DELETE).*['\"]\s*\+", re.IGNORECASE
)

# FRONT-010: console.log in production code
_RE_CONSOLE_LOG = re.compile(r"console\.log\(")

# SLOP-003: Generic/overused fonts
_RE_GENERIC_FONT = re.compile(
    r"(?:font-family|fontFamily).*(?:Inter|Roboto|Arial)", re.IGNORECASE
)

# SLOP-001: Default/generic Tailwind colors (indigo/blue 500/600)
_RE_DEFAULT_TAILWIND = re.compile(r"bg-(?:indigo|blue)-(?:500|600)")

# Patterns to identify test files (excluded from FRONT-010)
_RE_TEST_FILE = re.compile(
    r"(?:\.test\.|\.spec\.|__tests__|\.stories\.|test_)", re.IGNORECASE
)

# BACK-016: Non-transactional multi-step writes
_RE_DELETE_MANY = re.compile(r"\.(?:deleteMany|delete)\s*\(", re.IGNORECASE)
_RE_CREATE_MANY = re.compile(r"\.(?:createMany|create)\s*\(", re.IGNORECASE)
_RE_TRANSACTION = re.compile(r"\$transaction|\btransaction\b|\.atomic\b|db\.session", re.IGNORECASE)

# BACK-018: Unvalidated route parameters
_RE_PARAM_PARSE = re.compile(r"(?:Number|parseInt|parseFloat)\s*\(\s*req\.params")
_RE_ISNAN = re.compile(r"\bisNaN\b")

# BACK-017: Validation result discarded
_RE_SCHEMA_PARSE_ASSIGNED = re.compile(
    r"(?:const|let|var|return|=)\s*.*(?:parse|safeParse|validate)\s*\(", re.IGNORECASE,
)

# MOCK-001: RxJS mock patterns in service files
_RE_RXJS_OF_MOCK = re.compile(r'\bof\s*\(\s*[\[\{]')
_RE_RXJS_DELAY_PIPE = re.compile(r'\.pipe\s*\([^)]*delay\s*\(')
_RE_MOCK_RETURN_OF = re.compile(r'return\s+of\s*\(')

# MOCK-002: Promise.resolve with hardcoded data
_RE_PROMISE_RESOLVE_MOCK = re.compile(r'Promise\.resolve\s*\(\s*[\[\{]')

# MOCK-003: Mock variable names
_RE_MOCK_VARIABLE = re.compile(
    r'\b(?:mock|fake|dummy|sample|stub|hardcoded)'
    r'(?:Data|Response|Result|Items|List|Array|Users|Tenders|Bids|Projects)\b',
    re.IGNORECASE,
)

# MOCK-004: setTimeout/setInterval simulating API responses
_RE_TIMEOUT_MOCK = re.compile(r'setTimeout\s*\(\s*(?:\(\s*\)\s*=>|function)')

# MOCK-005: delay() used to simulate network latency
_RE_DELAY_SIMULATE = re.compile(r'\bdelay\s*\(\s*\d+\s*\)')

# MOCK-006: BehaviorSubject with hardcoded initial data (non-null/non-empty)
_RE_BEHAVIOR_SUBJECT_MOCK = re.compile(
    r'new\s+BehaviorSubject\s*[<(]\s*[\[\{]',
)

# MOCK-007: new Observable returning hardcoded data
_RE_OBSERVABLE_MOCK = re.compile(
    r'new\s+Observable\s*[<(]\s*(?:\(\s*\w+\s*\)\s*=>|function)',
)

# MOCK-008: Hardcoded count/badge values in component files
_RE_HARDCODED_UI_COUNT = re.compile(
    r'(?:count|badge|notification|unread|pending|total(?:Count|Items|Results))\s*[:=]\s*[\'"]?\d+[\'"]?',
    re.IGNORECASE,
)

_RE_COMPONENT_PATH = re.compile(
    r'(?:component|page|view|screen|widget|panel|sidebar|topbar|navbar|header|footer|layout)',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# UI Compliance patterns (UI-001..004)
# ---------------------------------------------------------------------------

# UI-001: Hardcoded hex color in CSS/style attributes (not in config/variable files)
_RE_HARDCODED_HEX_CSS = re.compile(
    r'(?:color|background|border|fill|stroke)\s*:\s*#[0-9a-fA-F]{3,8}\b'
)
_RE_HARDCODED_HEX_STYLE = re.compile(
    r"(?:color|backgroundColor|borderColor|fill|stroke)\s*[:=]\s*['\"]#[0-9a-fA-F]{3,8}['\"]"
)

# UI-001b: Hardcoded hex in Tailwind arbitrary value classes
_RE_TAILWIND_ARBITRARY_HEX = re.compile(
    r'(?:bg|text|border|ring|shadow|fill|stroke)-\[#[0-9a-fA-F]{3,8}\]'
)

# UI-002: Default Tailwind colors (extended — indigo/violet/purple 400..700)
_RE_DEFAULT_TAILWIND_EXTENDED = re.compile(
    r'\b(?:bg|text|border|ring)-(?:indigo|violet|purple)-(?:4|5|6|7)00\b'
)

# UI-003: Generic fonts in config/theme files
_RE_GENERIC_FONT_CONFIG = re.compile(
    r"(?:fontFamily|font-family|fonts)\s*[:=].*\b(?:Inter|Roboto|Arial|Helvetica|system-ui)\b",
    re.IGNORECASE,
)

# UI-004: Arbitrary spacing not on 4px grid (odd pixel values in padding/margin/gap)
# Includes directional Tailwind variants: pt/pb/pl/pr, mt/mb/ml/mr
_RE_ARBITRARY_SPACING = re.compile(
    r'(?:padding|margin|gap)\s*:\s*(\d+)px|(?:p[tlbrxy]?-|m[tlbrxy]?-|space-[xy]-)(?:\[)?(\d+)(?:px)?(?:\])?'
)

# Config/theme file detection (exempt from hardcoded color checks)
# Uses path-segment boundaries to avoid matching component names like "ThemeToggle"
_RE_CONFIG_FILE = re.compile(
    r'(?:^|[/\\])(?:tailwind\.config|theme|variables|tokens|design[-_]system|_variables)(?:\.|[/\\]|$)',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# E2E Testing quality patterns (E2E-001..007)
# ---------------------------------------------------------------------------

# E2E-001: Hardcoded sleep/timeout in E2E tests (use waitFor instead)
_RE_E2E_SLEEP = re.compile(r'setTimeout\s*\(|time\.sleep\s*\(')

# E2E-002: Hardcoded port in E2E test files (use config/env)
_RE_E2E_HARDCODED_PORT = re.compile(r'localhost:\d{4}|127\.0\.0\.1:\d{4}')
# Exempt: references to env/config
_RE_E2E_PORT_EXEMPT = re.compile(r'(?:process\.env|BASE_URL|baseURL|BASE_URL|config\.|getenv)')

# E2E-003: Mock data in E2E tests (must use real calls)
_RE_E2E_MOCK_DATA = re.compile(
    r'\b(?:mockData|fakeResponse|Promise\.resolve\s*\(\s*\[)'
)

# E2E-004: Empty test body (no assertions)
_RE_E2E_EMPTY_TEST = re.compile(
    r'(?:test|it)\s*\([^,]+,\s*async\s*(?:\(\s*\)|\(\s*\{[^}]*\}\s*\))\s*=>\s*\{\s*\}\s*\)'
)

# E2E-005: Auth test presence check (inverted — warn if NOT found)
_RE_E2E_AUTH_TEST = re.compile(
    r'(?:test|it|describe)\s*\(\s*[\'"].*(?:login|auth|sign.?in)',
    re.IGNORECASE,
)

# E2E-006: Placeholder text in UI components
# NOTE: "placeholder" alone is NOT matched — it is a standard HTML attribute.
# We match "placeholder text/content" and other indicator phrases.
# The `.` wildcard intentionally matches any separator (space, underscore, dash).
_RE_E2E_PLACEHOLDER = re.compile(
    r'(?:placeholder.text|placeholder.content|coming.soon|will.be.implemented|future.milestone|under.construction|not.yet.available|lorem.ipsum)',
    re.IGNORECASE,
)
# Comment patterns to exclude from E2E-006
_RE_COMMENT_LINE = re.compile(r'^\s*(?://|#|/\*|\*|{/\*)')

# E2E-007: Role access failure in E2E results
_RE_E2E_ROLE_FAILURE = re.compile(r'(?:403|Forbidden|Unauthorized|Access.Denied)', re.IGNORECASE)

# Path patterns for E2E test directories
_RE_E2E_DIR = re.compile(r'(?:^|[/\\])(?:e2e|playwright)[/\\]', re.IGNORECASE)

# Path patterns for service/client files
_RE_SERVICE_PATH = re.compile(
    r'(?:services?|clients?|api|http|data-access|repositor|provider|store|facade|composable)',
    re.IGNORECASE,
)

# Function definition patterns for duplicate detection
_RE_FUNC_DEF_JS = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(|"
    r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?(?:\(|=>)",
)
_RE_FUNC_DEF_PY = re.compile(r"^(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)


# ---------------------------------------------------------------------------
# Dual ORM detection patterns (DB-001..003)
# ---------------------------------------------------------------------------

_RE_DB_SQL_STRING = re.compile(
    r"""(?:SELECT|INSERT|UPDATE|DELETE|WHERE|SET|JOIN)\s""",
    re.IGNORECASE,
)
_RE_DB_SQL_ENUM_INT_CMP = re.compile(
    r"""(?:WHERE|AND|OR|SET)\s+\w+\s*=\s*\d+""",
    re.IGNORECASE,
)
_RE_DB_SQL_ENUM_STR_CMP = re.compile(
    r"""(?:WHERE|AND|OR|SET)\s+\w+\s*=\s*['"]""",
    re.IGNORECASE,
)
_RE_DB_SQL_BOOL_INT = re.compile(
    r"""(?:WHERE|AND|OR|SET)\s+\w+\s*=\s*[01]\b""",
    re.IGNORECASE,
)
_RE_DB_SQL_DATETIME_FORMAT = re.compile(
    r"""(?:WHERE|AND|OR|SET)\s+\w+\s*(?:=|<|>|<=|>=|BETWEEN)\s*['"]?\d{4}[-/]\d{2}[-/]\d{2}""",
    re.IGNORECASE,
)
_RE_DB_CSHARP_ENUM_PROP = re.compile(
    r"""public\s+(\w+)\s+(\w+)\s*\{""",
)
_RE_DB_CSHARP_BOOL_PROP = re.compile(
    r"""public\s+bool\??\s+(\w+)\s*\{""",
)
_RE_DB_CSHARP_DATETIME_PROP = re.compile(
    r"""public\s+(?:DateTime|DateTimeOffset|DateOnly|TimeOnly)\??\s+(\w+)\s*\{""",
)
_EXT_ENTITY = frozenset({".cs", ".py", ".ts", ".js"})

# Common C# entity/navigation types to exclude from enum property detection
_CSHARP_NON_ENUM_TYPES = frozenset({
    "int", "long", "string", "bool", "decimal", "float",
    "double", "DateTime", "DateTimeOffset", "DateOnly", "TimeOnly",
    "Guid", "byte", "short", "byte[]",
    "ICollection", "IList", "List", "IEnumerable", "HashSet",
    "class", "interface", "struct", "enum", "record",
    "static", "abstract", "override", "async", "void", "virtual",
    "Task", "Action", "Func",
})

# Suffixes that indicate a type is NOT an enum (service, DTO, entity, etc.)
_CSHARP_NON_ENUM_SUFFIXES = (
    "Dto", "DTO", "Service", "Controller", "Repository",
    "Manager", "Handler", "Factory", "Builder", "Provider",
    "Validator", "Mapper", "Context", "Configuration",
    "Options", "Settings", "Response", "Request", "Command",
    "Query", "Event", "Exception", "Attribute", "Helper",
    "Model", "ViewModel", "Entity",
)

# ---------------------------------------------------------------------------
# Default value detection patterns (DB-004..005)
# ---------------------------------------------------------------------------

_RE_DB_CSHARP_BOOL_NO_DEFAULT = re.compile(
    r"""public\s+bool\s+(\w+)\s*\{\s*get;\s*(?:set|init|private\s+set|protected\s+set);\s*\}(?!\s*=)""",
)
_RE_DB_CSHARP_ENUM_NO_DEFAULT = re.compile(
    r"""public\s+(\w+)\s+(\w+)\s*\{\s*get;\s*(?:set|init|private\s+set|protected\s+set);\s*\}(?!\s*=)""",
)
_RE_DB_CSHARP_NULLABLE_PROP = re.compile(
    r"""public\s+(\w+)\?\s+(\w+)\s*\{""",
)
_RE_DB_PRISMA_NO_DEFAULT = re.compile(
    r"""(\w+)\s+(?:Boolean|Int)\s*$""",
    re.MULTILINE,
)
# Prisma String fields with status-like names that should have defaults
_RE_DB_PRISMA_STRING_STATUS_NO_DEFAULT = re.compile(
    r"""((?:status|state|type|role|category|priority|phase|level))\s+String\s*$""",
    re.MULTILINE | re.IGNORECASE,
)
# Prisma enum field without default: "status  TenderStatus" (type starts with uppercase, not a built-in)
_RE_DB_PRISMA_ENUM_NO_DEFAULT = re.compile(
    r"""(\w+)\s+([A-Z]\w+)\s*$""",
    re.MULTILINE,
)
_PRISMA_BUILTIN_TYPES = frozenset({
    "String", "Boolean", "Int", "BigInt", "Float", "Decimal",
    "DateTime", "Json", "Bytes",
})
_RE_DB_DJANGO_BOOL_NO_DEFAULT = re.compile(
    r"""BooleanField\s*\(\s*\)""",
)
_RE_DB_SQLALCHEMY_NO_DEFAULT = re.compile(
    r"""Column\s*\(\s*(?:Boolean|Enum)\b[^)]*\)""",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Relationship completeness patterns (DB-006..008)
# ---------------------------------------------------------------------------

_RE_DB_CSHARP_FK_PROP = re.compile(
    r"""public\s+(?:int|long|Guid|string)\??\s+(\w+Id)\s*\{""",
)
_RE_DB_CSHARP_NAV_PROP = re.compile(
    r"""public\s+(?:virtual\s+)?(?:(?:ICollection|IList|IEnumerable|List|HashSet)<(\w+)>\s+(\w+)|(\w+)\s+(\w+))\s*\{""",
)
_RE_DB_CSHARP_HAS_MANY = re.compile(
    r"""\.Has(?:Many|One)\s*\(\s*\w*\s*=>\s*\w+\.(\w+)\)""",
)
_RE_DB_TYPEORM_RELATION = re.compile(
    r"""@(?:ManyToOne|OneToMany|OneToOne|ManyToMany)\s*\(""",
)
_RE_DB_TYPEORM_JOIN_COLUMN = re.compile(
    r"""@JoinColumn\s*\(\s*\{[^}]*name\s*:\s*['"](\w+)['"]""",
)
_RE_DB_TYPEORM_RELATION_DETAIL = re.compile(
    r"""@(ManyToOne|OneToMany|OneToOne|ManyToMany)\s*\(\s*\(\)\s*=>\s*(\w+)""",
)
_RE_DB_DJANGO_FK = re.compile(
    r"""(?:ForeignKey|OneToOneField|ManyToManyField)\s*\(""",
)
_RE_DB_DJANGO_FK_DETAIL = re.compile(
    r"""(\w+)\s*=\s*models\.(?:ForeignKey|OneToOneField)\s*\(\s*['"]?(\w+)['"]?""",
)
_RE_DB_SQLALCHEMY_RELATIONSHIP = re.compile(
    r"""relationship\s*\(""",
)
_RE_DB_SQLALCHEMY_FK_COLUMN = re.compile(
    r"""(\w+)\s*=\s*Column\s*\([^)]*ForeignKey\s*\(\s*['"](\w+)\.(\w+)['"]""",
)
_RE_DB_SQLALCHEMY_RELATIONSHIP_DETAIL = re.compile(
    r"""(\w+)\s*=\s*relationship\s*\(\s*['"](\w+)['"]""",
)

# Entity/model file indicators
_RE_ENTITY_INDICATOR_CS = re.compile(
    r"""\[Table\]|\bDbContext\b|:\s*DbContext\b""",
)
_RE_ENTITY_INDICATOR_TS = re.compile(
    r"""@Entity\s*\(|Schema\s*\(""",
)
_RE_ENTITY_INDICATOR_PY = re.compile(
    r"""\bmodels\.Model\b|Base\.metadata|Base\s*=\s*declarative_base|class\s+\w+\s*\([^)]*Base[^)]*\)""",
)
_RE_ENTITY_DIR = re.compile(
    r"""(?:^|[/\\])(?:Entities|Models|Domain|entities|models)[/\\]""",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# File extension sets for each check
# ---------------------------------------------------------------------------

_EXT_TYPESCRIPT: frozenset[str] = frozenset({".ts", ".tsx"})
_EXT_BACKEND: frozenset[str] = frozenset({".ts", ".js", ".py"})
_EXT_JS_ALL: frozenset[str] = frozenset({".ts", ".tsx", ".js", ".jsx"})
_EXT_STYLE: frozenset[str] = frozenset({".css", ".scss", ".ts", ".tsx"})
_EXT_TEMPLATE: frozenset[str] = frozenset({".ts", ".tsx", ".jsx", ".html"})
_EXT_UI: frozenset[str] = frozenset({
    ".tsx", ".jsx", ".vue", ".svelte", ".css", ".scss", ".html",
})
_EXT_E2E: frozenset[str] = frozenset({".ts", ".tsx", ".js", ".jsx", ".py"})
_EXT_TEMPLATE_CONTENT: frozenset[str] = frozenset({
    ".tsx", ".jsx", ".vue", ".svelte", ".html", ".component.ts",
})


# ---------------------------------------------------------------------------
# Private check helpers
# ---------------------------------------------------------------------------


def _check_ts_any(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """FRONT-007: Detect TypeScript `any` type usage.

    Flags lines containing `: any` in .ts and .tsx files.  This is an error
    because ``any`` defeats the type system entirely.
    """
    if extension not in _EXT_TYPESCRIPT:
        return []

    violations: list[Violation] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if _RE_TS_ANY.search(line):
            violations.append(Violation(
                check="FRONT-007",
                message="TypeScript `any` type detected — use `unknown`, generics, or specific types",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))
    return violations


def _check_n_plus_1(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """BACK-002: Detect N+1 query patterns.

    Flags ``for ... await`` loops and ``await ... .find ... for`` patterns in
    backend source files (.ts, .js, .py).  These typically indicate a loop
    that issues one query per iteration instead of batching.
    """
    if extension not in _EXT_BACKEND:
        return []

    violations: list[Violation] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if _RE_N_PLUS_1_FOR_AWAIT.search(line) or _RE_N_PLUS_1_AWAIT_FIND.search(line):
            violations.append(Violation(
                check="BACK-002",
                message="Possible N+1 query pattern — use batch fetches, JOINs, or DataLoader",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))
    return violations


def _check_sql_concat(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """BACK-001: Detect SQL string concatenation (injection risk).

    Flags lines that concatenate string literals containing SQL keywords
    (SELECT, INSERT, UPDATE, DELETE) with the ``+`` operator.  This is
    an error because it opens the door to SQL injection.
    """
    if extension not in _EXT_BACKEND:
        return []

    violations: list[Violation] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if _RE_SQL_CONCAT_PREFIX.search(line) or _RE_SQL_CONCAT_SUFFIX.search(line):
            violations.append(Violation(
                check="BACK-001",
                message="SQL string concatenation detected — use parameterized queries",
                file_path=rel_path,
                line=lineno,
                severity="error",
            ))
    return violations


def _check_console_log(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """FRONT-010: Detect console.log in non-test production files.

    Flags ``console.log(`` calls in .ts, .tsx, .js, .jsx files, excluding
    test files (identified by name patterns like ``.test.``, ``.spec.``,
    ``__tests__``, ``.stories.``, ``test_``).
    """
    if extension not in _EXT_JS_ALL:
        return []

    # Skip test/story files
    if _RE_TEST_FILE.search(rel_path):
        return []

    violations: list[Violation] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if _RE_CONSOLE_LOG.search(line):
            violations.append(Violation(
                check="FRONT-010",
                message="console.log found in non-test file — use structured logging",
                file_path=rel_path,
                line=lineno,
                severity="info",
            ))
    return violations


def _check_generic_fonts(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """SLOP-003: Detect generic/overused fonts.

    Flags font-family or fontFamily declarations that reference Inter,
    Roboto, or Arial in .css, .scss, .ts, and .tsx files.  These are the
    default fonts that every tutorial uses and signal a lack of intentional
    design.
    """
    if extension not in _EXT_STYLE:
        return []

    violations: list[Violation] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if _RE_GENERIC_FONT.search(line):
            violations.append(Violation(
                check="SLOP-003",
                message="Generic/overused font detected (Inter/Roboto/Arial) — use a distinctive typeface",
                file_path=rel_path,
                line=lineno,
                severity="info",
            ))
    return violations


def _check_default_tailwind_colors(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """SLOP-001: Detect default/generic Tailwind colors.

    Flags ``bg-indigo-500``, ``bg-indigo-600``, ``bg-blue-500``, and
    ``bg-blue-600`` classes in .ts, .tsx, .jsx, and .html files.  These
    are the default Tailwind hero colors that signal copy-paste from docs.
    """
    if extension not in _EXT_TEMPLATE:
        return []

    violations: list[Violation] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if _RE_DEFAULT_TAILWIND.search(line):
            violations.append(Violation(
                check="SLOP-001",
                message="Default Tailwind color (indigo/blue-500/600) — use project-specific palette",
                file_path=rel_path,
                line=lineno,
                severity="info",
            ))
    return violations


def _check_transaction_safety(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """BACK-016: Detect deleteMany followed by createMany without transaction wrapper.

    Scans for delete+create pairs within the same file and checks whether a
    $transaction or equivalent wrapper is present in the surrounding scope.
    """
    if extension not in _EXT_BACKEND:
        return []

    lines = content.splitlines()
    violations: list[Violation] = []

    for i, line in enumerate(lines):
        if _RE_DELETE_MANY.search(line):
            # Look ahead up to 20 lines for a create pattern
            window = "\n".join(lines[i:i + 20])
            if _RE_CREATE_MANY.search(window):
                # Check broader scope for transaction wrapper
                scope_start = max(0, i - 10)
                scope = "\n".join(lines[scope_start:i + 20])
                if not _RE_TRANSACTION.search(scope):
                    violations.append(Violation(
                        check="BACK-016",
                        message="Sequential delete + create without transaction — wrap in $transaction()",
                        file_path=rel_path,
                        line=i + 1,
                        severity="warning",
                    ))
    return violations


def _check_param_validation(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """BACK-018: Detect Number(req.params) or parseInt(req.params) without NaN check.

    Two-pass: find param parsing, then check next 5 lines for isNaN guard.
    """
    if extension not in _EXT_BACKEND:
        return []

    lines = content.splitlines()
    violations: list[Violation] = []

    for i, line in enumerate(lines):
        if _RE_PARAM_PARSE.search(line):
            # Check next 5 lines for isNaN guard
            window = "\n".join(lines[i:i + 6])
            if not _RE_ISNAN.search(window):
                violations.append(Violation(
                    check="BACK-018",
                    message="Route parameter parsed without NaN check — validate and return 400 on invalid",
                    file_path=rel_path,
                    line=i + 1,
                    severity="warning",
                ))
    return violations


def _check_validation_data_flow(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """BACK-017: Detect schema.parse(req.body) where result is not assigned.

    Flags statement-level calls to .parse() / .validate() that discard the
    return value (the sanitized/parsed data is not used downstream).
    """
    if extension not in _EXT_BACKEND:
        return []

    violations: list[Violation] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        # Check for parse/validate calls that are not assigned
        if ("parse(" in stripped or "validate(" in stripped) and "req." in stripped:
            if not _RE_SCHEMA_PARSE_ASSIGNED.search(stripped):
                if stripped.endswith(";") or stripped.endswith(")"):
                    violations.append(Violation(
                        check="BACK-017",
                        message="Validation result discarded — assign parsed data: `req.body = schema.parse(req.body)`",
                        file_path=rel_path,
                        line=lineno,
                        severity="warning",
                    ))
    return violations


def _check_mock_data_patterns(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """MOCK-001..007: Detect mock data patterns in service/client files.

    Flags RxJS of() with hardcoded data, Promise.resolve() with hardcoded data,
    mock variable naming patterns, delay() latency simulation, setTimeout-based
    API simulation, BehaviorSubject with hardcoded data, and new Observable
    returning mock data in service, client, API, and data access files.

    Excludes test files and files not in service-related paths.
    Scans both JS/TS and Python service files.
    """
    _mock_extensions = _EXT_JS_ALL | {".py"}
    if extension not in _mock_extensions:
        return []

    # Skip test files
    if _RE_TEST_FILE.search(rel_path):
        return []

    # Only scan service-related files
    if not _RE_SERVICE_PATH.search(rel_path):
        return []

    violations: list[Violation] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if _RE_RXJS_OF_MOCK.search(line):
            violations.append(Violation(
                check="MOCK-001",
                message="RxJS of() with hardcoded data in service file — must use real HTTP call",
                file_path=rel_path,
                line=lineno,
                severity="error",
            ))
        if _RE_MOCK_RETURN_OF.search(line):
            violations.append(Violation(
                check="MOCK-001",
                message="Service method returns of() instead of real HTTP call",
                file_path=rel_path,
                line=lineno,
                severity="error",
            ))
        if _RE_RXJS_DELAY_PIPE.search(line):
            violations.append(Violation(
                check="MOCK-001",
                message="RxJS delay() pipe simulating API latency — must use real HTTP call",
                file_path=rel_path,
                line=lineno,
                severity="error",
            ))
        if _RE_PROMISE_RESOLVE_MOCK.search(line):
            violations.append(Violation(
                check="MOCK-002",
                message="Promise.resolve() with hardcoded data — must use real HTTP/fetch call",
                file_path=rel_path,
                line=lineno,
                severity="error",
            ))
        if _RE_MOCK_VARIABLE.search(line):
            violations.append(Violation(
                check="MOCK-003",
                message="Mock/fake/dummy data variable in service file — replace with real API data",
                file_path=rel_path,
                line=lineno,
                severity="error",
            ))
        if _RE_TIMEOUT_MOCK.search(line):
            violations.append(Violation(
                check="MOCK-004",
                message="setTimeout simulating async API in service — must use real HTTP call",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))
        if _RE_DELAY_SIMULATE.search(line):
            violations.append(Violation(
                check="MOCK-005",
                message="delay() simulating network latency — suggests mock data pattern",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))
        if _RE_BEHAVIOR_SUBJECT_MOCK.search(line):
            violations.append(Violation(
                check="MOCK-006",
                message="BehaviorSubject initialized with hardcoded data — use null + HTTP populate",
                file_path=rel_path,
                line=lineno,
                severity="error",
            ))
        if _RE_OBSERVABLE_MOCK.search(line):
            violations.append(Violation(
                check="MOCK-007",
                message="new Observable returning inline data — must use real HTTP call",
                file_path=rel_path,
                line=lineno,
                severity="error",
            ))
    return violations


def _check_hardcoded_ui_counts(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """MOCK-008: Detect hardcoded count/badge values in component files.

    Scans component, page, view, and layout files for patterns like
    ``notificationCount = '3'`` or ``badgeCount = 5`` that indicate
    hardcoded display data instead of API-driven values.

    Only applies to JS/TS/Vue/Svelte component files. Test files are excluded.
    """
    _ui_extensions = _EXT_JS_ALL | {".vue", ".svelte"}
    if extension not in _ui_extensions:
        return []

    # Skip test files
    if _RE_TEST_FILE.search(rel_path):
        return []

    # Only scan component-related files
    if not _RE_COMPONENT_PATH.search(rel_path):
        return []

    violations: list[Violation] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if _RE_HARDCODED_UI_COUNT.search(line):
            violations.append(Violation(
                check="MOCK-008",
                message="Hardcoded count/badge value in component — display counts must come from API or reactive state",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))
    return violations


def _check_ui_compliance(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """UI-001..004: Detect UI compliance violations in component/style files.

    Checks for hardcoded colors, default Tailwind palettes, generic fonts,
    and arbitrary spacing in UI files. Config/theme files are exempt from
    color checks (they define tokens). Test files are skipped entirely.
    """
    if extension not in _EXT_UI:
        # Also check .component.ts (Angular) and config/theme .ts files
        if extension == ".ts" and (
            rel_path.endswith(".component.ts") or _RE_CONFIG_FILE.search(rel_path)
        ):
            pass  # Allow these .ts files through
        else:
            return []

    # Skip test files
    if _RE_TEST_FILE.search(rel_path):
        return []

    is_config_file = _RE_CONFIG_FILE.search(rel_path)

    violations: list[Violation] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        # UI-001: Hardcoded hex colors (skip config files — they define tokens)
        if not is_config_file:
            if _RE_HARDCODED_HEX_CSS.search(line):
                violations.append(Violation(
                    check="UI-001",
                    message="Hardcoded hex color in style — use design token variable instead",
                    file_path=rel_path,
                    line=lineno,
                    severity="warning",
                ))
            if _RE_HARDCODED_HEX_STYLE.search(line):
                violations.append(Violation(
                    check="UI-001",
                    message="Hardcoded hex color in inline style — use design token variable",
                    file_path=rel_path,
                    line=lineno,
                    severity="warning",
                ))
            # UI-001b: Tailwind arbitrary hex
            if _RE_TAILWIND_ARBITRARY_HEX.search(line):
                violations.append(Violation(
                    check="UI-001b",
                    message="Hardcoded hex in Tailwind arbitrary value — use theme color instead",
                    file_path=rel_path,
                    line=lineno,
                    severity="warning",
                ))

        # UI-002: Default Tailwind colors (always check, even in config)
        if _RE_DEFAULT_TAILWIND_EXTENDED.search(line):
            violations.append(Violation(
                check="UI-002",
                message="Default Tailwind color (indigo/violet/purple) — use project-specific palette",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))

        # UI-003: Generic fonts in config files
        if is_config_file and _RE_GENERIC_FONT_CONFIG.search(line):
            violations.append(Violation(
                check="UI-003",
                message="Generic font (Inter/Roboto/Arial) in config — use distinctive typeface",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))

        # UI-004: Arbitrary spacing (check non-grid values)
        match = _RE_ARBITRARY_SPACING.search(line)
        if match:
            try:
                # group(1) = CSS property value, group(2) = Tailwind class value
                raw = match.group(1) or match.group(2)
                if raw is not None:
                    value = int(raw)
                    # Allow 0 and multiples of 4 (4px grid) and common Tailwind values
                    if value > 0 and value % 4 != 0 and value not in (1, 2, 6, 10, 14):
                        violations.append(Violation(
                            check="UI-004",
                            message=f"Spacing value {value}px not on 4px grid — use grid-aligned value",
                            file_path=rel_path,
                            line=lineno,
                            severity="info",
                        ))
            except (ValueError, IndexError):
                pass

    return violations


def _check_e2e_quality(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """E2E-001..006: Detect quality issues in E2E test files and UI templates.

    E2E-001..004: Only targets files in e2e/, tests/e2e/, playwright/ directories.
    E2E-006: Targets UI template files (tsx, jsx, vue, svelte, html, component.ts)
    for placeholder text outside of comments.
    """
    violations: list[Violation] = []

    # --- E2E-006: Placeholder text in UI components (all template files) ---
    is_template_file = (
        extension in _EXT_TEMPLATE_CONTENT
        or rel_path.endswith(".component.ts")
    )
    if is_template_file and not _RE_E2E_DIR.search(rel_path):
        for lineno, line in enumerate(content.splitlines(), start=1):
            # Skip comment lines — placeholders in comments are fine
            if _RE_COMMENT_LINE.search(line):
                continue
            if _RE_E2E_PLACEHOLDER.search(line):
                violations.append(Violation(
                    check="E2E-006",
                    message="Placeholder text in UI component — implement the actual feature",
                    file_path=rel_path,
                    line=lineno,
                    severity="error",
                ))

    # --- E2E-001..004: Only E2E test directories ---
    if extension not in _EXT_E2E:
        return violations

    if not _RE_E2E_DIR.search(rel_path):
        return violations

    for lineno, line in enumerate(content.splitlines(), start=1):
        # E2E-001: Hardcoded sleep
        if _RE_E2E_SLEEP.search(line):
            violations.append(Violation(
                check="E2E-001",
                message="Hardcoded sleep/timeout in E2E test — use waitFor, waitForResponse, or waitForSelector",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))
        # E2E-002: Hardcoded port
        if _RE_E2E_HARDCODED_PORT.search(line) and not _RE_E2E_PORT_EXEMPT.search(line):
            violations.append(Violation(
                check="E2E-002",
                message="Hardcoded port in E2E test — use configurable BASE_URL or process.env",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))
        # E2E-003: Mock data in E2E
        if _RE_E2E_MOCK_DATA.search(line):
            violations.append(Violation(
                check="E2E-003",
                message="Mock data in E2E test — all calls must hit real server",
                file_path=rel_path,
                line=lineno,
                severity="error",
            ))
        # E2E-004: Empty test body
        if _RE_E2E_EMPTY_TEST.search(line):
            violations.append(Violation(
                check="E2E-004",
                message="Empty E2E test body — every test must have meaningful assertions",
                file_path=rel_path,
                line=lineno,
                severity="error",
            ))
    return violations


def _check_gitignore(
    project_root: Path,
) -> list[Violation]:
    """Check for missing .gitignore or missing critical entries.

    This is a PROJECT-LEVEL check (not per-file). It checks:
    1. Whether .gitignore exists
    2. If so, whether it contains critical entries (node_modules, dist, .env)
    """
    violations: list[Violation] = []
    gitignore_path = project_root / ".gitignore"

    if not gitignore_path.is_file():
        violations.append(Violation(
            check="PROJ-001",
            message="Missing .gitignore file — add one with node_modules, dist, .env entries",
            file_path=".gitignore",
            line=0,
            severity="warning",
        ))
        return violations

    try:
        content = gitignore_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return violations

    critical_entries = ["node_modules", "dist", ".env"]
    for entry in critical_entries:
        if entry not in content:
            violations.append(Violation(
                check="PROJ-001",
                message=f".gitignore missing critical entry: {entry}",
                file_path=".gitignore",
                line=0,
                severity="warning",
            ))

    return violations


def _check_duplicate_functions(
    project_root: Path,
    source_files: list[Path],
) -> list[Violation]:
    """FRONT-016: Detect same function name defined in 2+ non-test files.

    This is a PROJECT-LEVEL check. Builds a function_name → [files] map
    and flags names that appear in 2+ files.
    """
    func_map: dict[str, list[str]] = {}

    for file_path in source_files:
        try:
            rel_path = file_path.relative_to(project_root).as_posix()
        except ValueError:
            rel_path = file_path.name

        if _RE_TEST_FILE.search(rel_path):
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        extension = file_path.suffix
        found_names: set[str] = set()

        if extension in (".ts", ".tsx", ".js", ".jsx"):
            for match in _RE_FUNC_DEF_JS.finditer(content):
                name = match.group(1) or match.group(2)
                if name and len(name) > 2:  # Skip very short names
                    found_names.add(name)
        elif extension == ".py":
            for match in _RE_FUNC_DEF_PY.finditer(content):
                name = match.group(1)
                if name and not name.startswith("_") and len(name) > 2:
                    found_names.add(name)

        for name in found_names:
            func_map.setdefault(name, []).append(rel_path)

    violations: list[Violation] = []
    for name, files in sorted(func_map.items()):
        if len(files) >= 2:
            violations.append(Violation(
                check="FRONT-016",
                message=f"Duplicate function '{name}' defined in {len(files)} files: {', '.join(files[:3])}",
                file_path=files[0],
                line=0,
                severity="warning",
            ))

    return violations


# ---------------------------------------------------------------------------
# V16 Blocker-3: Stub/placeholder detection patterns (STUB-010..014)
# ---------------------------------------------------------------------------

# STUB-010: TODO/FIXME/HACK comments indicating unfinished code
_RE_TODO_STUB = re.compile(
    r"(?://|#|/\*)\s*(?:TODO|FIXME|HACK|XXX)\b.*(?:implement|finish|complete|add|fix|replace)",
    re.IGNORECASE,
)

# STUB-011: "In a real implementation" / "would normally" sloppy comments
_RE_SLOPPY_COMMENT = re.compile(
    r"(?://|#|/\*)\s*(?:in\s+a?\s*real|would\s+normally|placeholder|not\s+yet\s+implemented|"
    r"stub|dummy\s+(?:impl|data|response)|this\s+is\s+a\s+(?:placeholder|stub|mock))",
    re.IGNORECASE,
)

# STUB-012: Functions returning a constant for what should be a calculation
_RE_CONSTANT_RETURN_ZERO = re.compile(
    r"(?:return\s+0\s*;?\s*$|return\s+0\.0\s*;?\s*$)",
)
_RE_CONSTANT_RETURN_TRIVIAL = re.compile(
    r"(?:return\s+(?:true|false|null|undefined|None|\[\s*\]|\{\s*\})\s*;?\s*$)",
)
# Functions/methods that should compute something (heuristic: name suggests calculation)
_RE_CALC_FUNCTION_NAME = re.compile(
    r"(?:def|function|async\s+function)\s+(?:\w*(?:calculat|comput|evaluat|depreciat|amortiz|"
    r"reconcil|match|validat|convert|transform|aggregat|totaliz))\w*",
    re.IGNORECASE,
)

# STUB-013: Empty class body (no methods defined)
_RE_EMPTY_CLASS_TS = re.compile(
    r"(?:export\s+)?class\s+\w+(?:\s+(?:extends|implements)\s+\w+(?:<[^>]+>)?)?\s*\{\s*\}",
)
_RE_EMPTY_CLASS_PY = re.compile(
    r"class\s+\w+(?:\([^)]*\))?\s*:\s*\n\s+(?:pass|\.\.\.)\s*$",
    re.MULTILINE,
)

# STUB-014: Unused function parameter (parameter not referenced in body)
# Only checks for specific domain-critical parameters
_RE_DOMAIN_CRITICAL_PARAMS = re.compile(
    r"(?:exchange_?rate|tolerance|tax_?rate|discount|threshold|precision|rounding)",
    re.IGNORECASE,
)


def _check_todo_stub(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """STUB-010: Detect TODO/FIXME/HACK comments indicating unfinished implementation."""
    if extension not in _EXT_BACKEND:
        return []
    if _RE_TEST_FILE.search(rel_path):
        return []
    violations: list[Violation] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if _RE_TODO_STUB.search(line):
            violations.append(Violation(
                check="STUB-010",
                message="TODO/FIXME/HACK comment indicates unfinished implementation",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))
    return violations


def _check_sloppy_comment(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """STUB-011: Detect 'in a real implementation' / placeholder comments."""
    if extension not in _EXT_BACKEND:
        return []
    if _RE_TEST_FILE.search(rel_path):
        return []
    violations: list[Violation] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if _RE_SLOPPY_COMMENT.search(line):
            violations.append(Violation(
                check="STUB-011",
                message="Placeholder comment detected — implement real logic",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))
    return violations


def _check_constant_return(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """STUB-012: Detect functions returning constant 0/true/false/null for calculations."""
    if extension not in _EXT_BACKEND:
        return []
    if _RE_TEST_FILE.search(rel_path):
        return []
    violations: list[Violation] = []
    lines = content.splitlines()
    in_calc_fn = False
    fn_start_line = 0
    brace_depth = 0

    for lineno, line in enumerate(lines, start=1):
        # Detect entry into a calculation-named function
        if _RE_CALC_FUNCTION_NAME.search(line):
            in_calc_fn = True
            fn_start_line = lineno
            brace_depth = line.count("{") - line.count("}")

        if in_calc_fn:
            brace_depth += line.count("{") - line.count("}")
            stripped = line.strip()
            if _RE_CONSTANT_RETURN_ZERO.search(stripped) or _RE_CONSTANT_RETURN_TRIVIAL.search(stripped):
                violations.append(Violation(
                    check="STUB-012",
                    message=f"Calculation function returns constant value — implement real computation (fn started line {fn_start_line})",
                    file_path=rel_path,
                    line=lineno,
                    severity="warning",
                ))
            # For Python: function ends at next def/class at same indent
            if extension == ".py" and lineno > fn_start_line:
                if re.match(r"^(?:def |class |@)", stripped) and not line.startswith(" " * 4):
                    in_calc_fn = False
            # For TS/JS: function ends when brace depth returns to 0
            elif extension in (".ts", ".js") and brace_depth <= 0 and lineno > fn_start_line:
                in_calc_fn = False

    return violations


def _check_empty_class(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """STUB-013: Detect empty class bodies (no methods or properties)."""
    if extension not in _EXT_BACKEND:
        return []
    if _RE_TEST_FILE.search(rel_path):
        return []
    violations: list[Violation] = []

    if extension in (".ts", ".js", ".tsx", ".jsx"):
        for m in _RE_EMPTY_CLASS_TS.finditer(content):
            lineno = content[:m.start()].count("\n") + 1
            violations.append(Violation(
                check="STUB-013",
                message="Empty class body — implement methods or remove",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))
    elif extension == ".py":
        for m in _RE_EMPTY_CLASS_PY.finditer(content):
            lineno = content[:m.start()].count("\n") + 1
            violations.append(Violation(
                check="STUB-013",
                message="Empty class body (pass/...) — implement methods or remove",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))

    return violations


def _check_unused_domain_param(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """STUB-014: Detect domain-critical parameters that are never used in the function body."""
    if extension not in _EXT_BACKEND:
        return []
    if _RE_TEST_FILE.search(rel_path):
        return []
    violations: list[Violation] = []
    lines = content.splitlines()

    # Find function definitions
    fn_pattern = re.compile(
        r"(?:def|function|async\s+function)\s+(\w+)\s*\(([^)]*)\)",
    )

    for lineno, line in enumerate(lines, start=1):
        m = fn_pattern.search(line)
        if not m:
            continue
        fn_name = m.group(1)
        params_str = m.group(2)

        # Check each domain-critical parameter
        for pm in _RE_DOMAIN_CRITICAL_PARAMS.finditer(params_str):
            param_name = pm.group(0)
            # Get the function body (next 50 lines or until next function)
            body_lines = lines[lineno: min(lineno + 50, len(lines))]
            body = "\n".join(body_lines)

            # Check if param appears in body (case-insensitive for snake_case variants)
            param_variants = [param_name, param_name.replace("_", "")]
            used = any(v.lower() in body.lower() for v in param_variants)

            if not used:
                violations.append(Violation(
                    check="STUB-014",
                    message=f"Domain-critical parameter '{param_name}' in {fn_name}() is never used in body",
                    file_path=rel_path,
                    line=lineno,
                    severity="warning",
                ))

    return violations


def _check_trivial_function_body(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """STUB-015: Detect functions with trivial bodies that should have business logic.

    Catches functions that accept parameters but return only a trivial object
    like ``{ id: uuid() }`` or ``{ id: generate_id() }`` without using any
    of the parameters or performing any business logic.
    """
    if extension not in _EXT_BACKEND:
        return []
    if _RE_TEST_FILE.search(rel_path):
        return []
    violations: list[Violation] = []

    # Match functions that return only { id: ... } or similar trivial objects
    trivial_fn_pat = re.compile(
        r"(?:export\s+)?(?:async\s+)?(?:function|def)\s+(\w+)\s*\([^)]+\)\s*"
        r"(?::\s*\w+\s*)?[{:]",
    )
    trivial_return_pat = re.compile(
        r"return\s*\{\s*id\s*:\s*(?:uuid|crypto\.randomUUID|generate_id|str\(uuid)",
        re.IGNORECASE,
    )

    lines = content.splitlines()
    for lineno, line in enumerate(lines, start=1):
        m = trivial_fn_pat.search(line)
        if not m:
            continue
        fn_name = m.group(1)
        # Check the next 10 lines for trivial return
        body = "\n".join(lines[lineno: min(lineno + 10, len(lines))])
        if trivial_return_pat.search(body):
            # Count real statements (excluding return, comments, whitespace)
            real_stmts = [
                l.strip() for l in body.splitlines()
                if l.strip()
                and not l.strip().startswith(("//", "#", "/*", "*", "return", "}", "pass"))
            ]
            if len(real_stmts) <= 1:
                violations.append(Violation(
                    check="STUB-015",
                    message=f"Function '{fn_name}()' has trivial body — returns only {{id}} without business logic",
                    file_path=rel_path,
                    line=lineno,
                    severity="warning",
                ))

    return violations


def _check_state_change_no_event(
    content: str,
    rel_path: str,
    extension: str,
) -> list[Violation]:
    """STUB-016: Detect state/status changes without event publishing or validation.

    Catches patterns like ``update({status: 'closed'})`` or
    ``self.repo.update(id, {status: ...})`` without any surrounding
    validation, guard check, or event emission.
    """
    if extension not in _EXT_BACKEND:
        return []
    if _RE_TEST_FILE.search(rel_path):
        return []
    violations: list[Violation] = []

    # Pattern: direct status update without event/validation
    # Handles both dict notation {"status": "closed"} and assignment status='closed'
    status_update_pat = re.compile(
        r"(?:update|save|set)\s*\(.*(?:status|state)['\"]?\s*[:=]\s*['\"](\w+)['\"]",
        re.IGNORECASE,
    )
    event_pat = re.compile(
        r"(?:emit|publish|dispatch|send|notify|event|raise|trigger)",
        re.IGNORECASE,
    )
    validation_pat = re.compile(
        r"(?:validate|guard|check|verify|assert|ensure|if\s+.*(?:status|state))",
        re.IGNORECASE,
    )

    lines = content.splitlines()
    for lineno, line in enumerate(lines, start=1):
        m = status_update_pat.search(line)
        if not m:
            continue
        # Check surrounding context (5 lines before + 5 after) for events/validation
        context_start = max(0, lineno - 6)
        context_end = min(len(lines), lineno + 5)
        context = "\n".join(lines[context_start:context_end])

        has_event = bool(event_pat.search(context))
        has_validation = bool(validation_pat.search(context))

        if not has_event and not has_validation:
            violations.append(Violation(
                check="STUB-016",
                message=f"Status change to '{m.group(1)}' without validation or event publishing",
                file_path=rel_path,
                line=lineno,
                severity="warning",
            ))

    return violations


# ---------------------------------------------------------------------------
# All checks registry (order does not matter — output is sorted by severity)
# ---------------------------------------------------------------------------

_ALL_CHECKS = [
    _check_ts_any,
    _check_n_plus_1,
    _check_sql_concat,
    _check_console_log,
    _check_generic_fonts,
    _check_default_tailwind_colors,
    _check_transaction_safety,
    _check_param_validation,
    _check_validation_data_flow,
    _check_mock_data_patterns,
    _check_hardcoded_ui_counts,
    _check_ui_compliance,
    _check_e2e_quality,
    _check_todo_stub,
    _check_sloppy_comment,
    _check_constant_return,
    _check_empty_class,
    _check_unused_domain_param,
    _check_trivial_function_body,
    _check_state_change_no_event,
]

# Union of all file extensions any check cares about (for fast pre-filter)
_ALL_EXTENSIONS: frozenset[str] = (
    _EXT_TYPESCRIPT
    | _EXT_BACKEND
    | _EXT_JS_ALL
    | _EXT_STYLE
    | _EXT_TEMPLATE
    | _EXT_UI
    | _EXT_E2E
    | _EXT_ENTITY
)


# ---------------------------------------------------------------------------
# File traversal helpers
# ---------------------------------------------------------------------------


def _should_skip_dir(name: str) -> bool:
    """Return True if a directory named *name* should be skipped."""
    return name in _SKIP_DIRS


def _path_in_excluded_dir(file_path: Path) -> bool:
    """Return True if *file_path* has any excluded directory in its parts.

    Catches paths like ``.venv/Lib/site-packages/...`` where the parent
    dir was already pruned from ``os.walk`` but the file was discovered
    via ``rglob`` or ``glob`` which do NOT prune directories.
    """
    return any(part in _SKIP_DIRS for part in file_path.parts)


def _should_scan_file(path: Path) -> bool:
    """Return True if *path* is a regular file worth scanning.

    Skips files whose extension is not relevant to any check, and files
    exceeding ``_MAX_FILE_SIZE`` (to avoid scanning generated bundles).
    """
    if path.suffix not in _ALL_EXTENSIONS:
        return False
    try:
        if path.stat().st_size > _MAX_FILE_SIZE:
            return False
    except OSError:
        return False
    return True


def _iter_source_files(project_root: Path) -> list[Path]:
    """Walk *project_root* and return scannable source files.

    Skips directories listed in ``_SKIP_DIRS`` and files that fail the
    ``_should_scan_file`` predicate.  Uses ``os.walk`` for efficient
    directory pruning (avoids descending into ``node_modules`` etc.).
    """
    files: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(project_root):
        # Prune skip directories in-place (prevents os.walk from descending)
        dirnames[:] = [
            d for d in dirnames if not _should_skip_dir(d)
        ]

        for filename in filenames:
            file_path = Path(dirpath) / filename
            if _should_scan_file(file_path):
                files.append(file_path)

    return files


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_spot_checks(project_root: Path) -> list[Violation]:
    """Scan *project_root* for anti-patterns and return violations.

    Walks the project tree (skipping ``node_modules``, ``.git``,
    ``__pycache__``, ``dist``, ``build``, ``.next``, ``venv``), reads
    each relevant source file, and runs all registered checks.

    Also runs project-level checks (gitignore, duplicate functions) that
    operate across files rather than per-file.

    Returns violations sorted by severity (error > warning > info), then
    by file path, then by line number.  The list is capped at
    ``_MAX_VIOLATIONS`` (100) to avoid flooding downstream consumers.
    """
    violations: list[Violation] = []
    source_files = _iter_source_files(project_root)

    # --- Project-level checks ---
    violations.extend(_check_gitignore(project_root))
    violations.extend(_check_duplicate_functions(project_root, source_files))

    # --- Per-file checks ---
    for file_path in source_files:
        # Early exit if we already have enough violations
        if len(violations) >= _MAX_VIOLATIONS:
            break

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel_path = file_path.relative_to(project_root).as_posix()
        extension = file_path.suffix

        for check_fn in _ALL_CHECKS:
            file_violations = check_fn(content, rel_path, extension)
            violations.extend(file_violations)

            # Re-check cap after each check function
            if len(violations) >= _MAX_VIOLATIONS:
                break

    # Trim to cap (a check function may have pushed us over)
    violations = violations[:_MAX_VIOLATIONS]

    # Sort: severity (error first), then file path, then line number
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )

    return violations


def run_mock_data_scan(project_root: Path, scope: ScanScope | None = None) -> list[Violation]:
    """Scan project for mock data patterns in service/client files.

    Unlike :func:`run_spot_checks` which runs ALL checks, this function runs
    ONLY mock data detection checks (MOCK-001..008).  Designed for targeted
    post-milestone scanning in ``cli.py``.

    Returns violations sorted by severity, capped at ``_MAX_VIOLATIONS``.
    """
    violations: list[Violation] = []
    source_files = _iter_source_files(project_root)
    if scope and scope.changed_files:
        scope_set = set(scope.changed_files)
        source_files = [f for f in source_files if f.resolve() in scope_set]

    for file_path in source_files:
        if len(violations) >= _MAX_VIOLATIONS:
            break
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel_path = file_path.relative_to(project_root).as_posix()
        extension = file_path.suffix

        file_violations = _check_mock_data_patterns(content, rel_path, extension)
        file_violations.extend(_check_hardcoded_ui_counts(content, rel_path, extension))
        violations.extend(file_violations)

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )
    return violations


# ---------------------------------------------------------------------------
# STUB-001: Handler completeness scan (v16)
# ---------------------------------------------------------------------------

# Regex patterns to identify event handler functions
_HANDLER_NAME_PATTERNS_PY = re.compile(
    r"^(?:async\s+)?def\s+(handle_\w+|on_\w+|process_\w+|consume_\w+)\s*\(",
    re.MULTILINE,
)
_HANDLER_NAME_PATTERNS_TS = re.compile(
    r"(?:async\s+)?(handle\w+|on\w+|process\w+|consume\w+)\s*\([^)]*\)\s*(?::\s*Promise<[^>]*>)?\s*\{",
    re.MULTILINE,
)
# Patterns that indicate a subscribe call (TypeScript Redis/event subscriber)
_SUBSCRIBE_PATTERN_TS = re.compile(
    r"\.subscribe\s*\(\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)

# Lines that count as "logging only" (no real business action)
_LOG_ONLY_PATTERNS = re.compile(
    r"^\s*(?:"
    r"logger\.\w+\(|"                     # Python: logger.info(, logger.warning(
    r"logging\.\w+\(|"                    # Python: logging.info(
    r"console\.\w+\(|"                    # JS/TS: console.log(
    r"this\.logger\.\w+\(|"              # NestJS: this.logger.log(
    r"self\.logger\.\w+\(|"              # Python class: self.logger.info(
    r"print\(|"                           # Python: print(
    r"pass\s*$|"                          # Python: pass
    r"return\s*;?\s*$|"                  # bare return (with optional semicolon)
    r"return\s+None\s*$|"                # return None
    r"try\s*\{|"                          # try { (control flow wrapper)
    r"catch\s*\([^)]*\)\s*\{|"          # catch (e) {
    r"\}\s*$|"                            # closing brace
    r"#.*$|"                              # Python comment
    r"//.*$|"                             # JS/TS comment
    r"\s*$"                               # empty line
    r")",
    re.MULTILINE,
)

# Lines that indicate real business logic (DB, HTTP, state change)
_BUSINESS_ACTION_PATTERNS = re.compile(
    r"(?:"
    r"await\s+\w+\.(?:execute|add|commit|flush|merge|delete|save|insert|update|remove|create|post|put|patch|get|fetch)|"
    r"\.(?:save|create|insert|update|delete|remove|findOne|find|execute)\s*\(|"
    r"await\s+(?:fetch|axios|httpx?|requests?)\.|"
    r"await\s+self\.\w+_(?:service|repository|client|repo)\.|"
    r"await\s+this\.\w+(?:Service|Repository|Client)\.|"
    r"\.publishEvent\s*\(|"
    r"publish_event\s*\(|"
    r"\.emit\s*\(|"
    r"SELECT\s|INSERT\s|UPDATE\s|DELETE\s|"
    r"session\.\w+\(|"
    r"db\.\w+\(|"
    r"transaction\.|"
    r"\.status\s*=|"
    r"raise\s+\w+|"
    r"throw\s+new\s+\w+"
    r")",
    re.IGNORECASE,
)


def _extract_function_body_lines(content: str, match_start: int, is_python: bool) -> list[str]:
    """Extract the body lines of a function starting at *match_start*.

    For Python, uses indentation to detect end of function.
    For TypeScript, uses brace counting.
    Returns the body lines (excluding the def/function signature line).
    """
    lines = content[match_start:].split("\n")
    if not lines:
        return []

    body_lines: list[str] = []

    if is_python:
        # Find indentation of the def line
        sig_line = lines[0]
        sig_indent = len(sig_line) - len(sig_line.lstrip())
        for line in lines[1:]:
            stripped = line.strip()
            if not stripped:
                body_lines.append(line)
                continue
            line_indent = len(line) - len(line.lstrip())
            if line_indent <= sig_indent:
                break  # Back to same or lower indentation — end of function
            body_lines.append(line)
            if len(body_lines) > 50:
                break  # Safety limit
    else:
        # TypeScript: count braces from the opening {
        brace_depth = 0
        found_open = False
        skipped_sig = False
        for line in lines:
            for ch in line:
                if ch == "{":
                    brace_depth += 1
                    found_open = True
                elif ch == "}":
                    brace_depth -= 1
                    if found_open and brace_depth == 0:
                        return body_lines
            if found_open and brace_depth > 0:
                # Skip the signature line (the first line that opened the brace)
                if not skipped_sig:
                    skipped_sig = True
                    continue
                body_lines.append(line)
            if len(body_lines) > 50:
                break  # Safety limit

    return body_lines


def _is_stub_handler(body_lines: list[str]) -> bool:
    """Return True if the function body contains only logging and no business logic."""
    if not body_lines:
        return True  # Empty function body = stub

    # --- Early-return detection (M12 fix) ---
    # If the body has a bare `return;` early on preceded only by logging,
    # everything after it is dead code.  Truncate to effective lines.
    effective_lines = _trim_dead_code_after_early_return(body_lines)

    non_trivial_lines = [
        line for line in effective_lines
        if line.strip() and not _LOG_ONLY_PATTERNS.match(line)
    ]

    # If there are non-trivial lines, check if any contain business actions
    if non_trivial_lines:
        full_body = "\n".join(effective_lines)
        if _BUSINESS_ACTION_PATTERNS.search(full_body):
            return False  # Has real business logic
        # Has non-log lines but no recognized business actions —
        # could be variable assignment to extract payload fields.
        # Only flag as stub if ALL non-trivial lines are payload extraction.
        payload_only = all(
            re.match(r"^\s*(?:const|let|var|\w+)\s*=\s*(?:payload|message|data|event|envelope)", line.strip())
            or re.match(r"^\s*\w+\s*=\s*\w+\.(?:get|payload|data)\b", line.strip())
            for line in non_trivial_lines
        )
        return payload_only

    return True  # Only logging/comments/empty lines


# Bare return at the top level of a handler body (not inside if/else)
_BARE_RETURN_RE = re.compile(r"^\s*return\s*;?\s*$")

# Lines allowed before an early return that still count as "stub"
_PRE_RETURN_TRIVIAL_RE = re.compile(
    r"^\s*(?:"
    r"try\s*\{|"                             # try {
    r"catch\s*\([^)]*\)\s*\{|"              # catch (e) {
    r"\}|"                                   # closing brace
    r"logger\.\w+\(|"                        # Python logger
    r"logging\.\w+\(|"                       # Python logging
    r"console\.\w+\(|"                       # JS/TS console
    r"this\.logger\.\w+\(|"                 # NestJS logger
    r"self\.logger\.\w+\(|"                 # Python class logger
    r"print\(|"                              # print()
    r"#.*$|"                                 # Python comment
    r"//.*$|"                                # JS/TS comment
    r"\s*$"                                  # empty line
    r")"
)


def _trim_dead_code_after_early_return(body_lines: list[str]) -> list[str]:
    """Trim body at the first bare ``return`` preceded only by logging/trivial lines.

    If the handler body looks like:
        this.logger.info('event received', payload);
        return;
        // ... unreachable business logic below ...

    this function returns only the lines up to and including ``return``.
    If no early-return pattern is detected, returns the original body unchanged.
    """
    for i, line in enumerate(body_lines):
        stripped = line.strip()
        if not _BARE_RETURN_RE.match(stripped):
            continue
        # Found a bare return — check if ALL preceding lines are trivial/logging
        preceding = body_lines[:i]
        all_trivial = all(
            not ln.strip() or _PRE_RETURN_TRIVIAL_RE.match(ln.strip())
            for ln in preceding
        )
        if all_trivial:
            return body_lines[: i + 1]  # Truncate at the return
    return body_lines


def run_handler_completeness_scan(
    project_root: Path,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Detect event handler functions that are log-only stubs.

    Scans all Python and TypeScript files for functions matching handler
    patterns (handle_*, on_*, process_*, consume_*) and checks if their body
    contains only logging statements and no real business actions.

    Returns violations sorted by severity, capped at ``_MAX_VIOLATIONS``.
    """
    violations: list[Violation] = []
    source_files = _iter_source_files(project_root)
    if scope and scope.mode == "changed_only":
        if not scope.changed_files:
            return []  # Nothing changed — skip scan entirely
        scope_set = set(scope.changed_files)
        source_files = [f for f in source_files if f.resolve() in scope_set]

    for file_path in source_files:
        if len(violations) >= _MAX_VIOLATIONS:
            break

        # Only scan handler-like files (including entry points that may
        # contain inline event subscriptions — main.py, app.py)
        name_lower = file_path.name.lower()
        is_handler_file = any(kw in name_lower for kw in (
            "handler", "subscriber", "consumer", "listener", "event",
        )) or name_lower in ("main.py", "app.py")
        if not is_handler_file:
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if len(content) > _MAX_FILE_SIZE:
            continue

        rel_path = file_path.relative_to(project_root).as_posix()
        is_python = file_path.suffix == ".py"
        is_ts = file_path.suffix in (".ts", ".js")

        # Find handler functions
        if is_python:
            matches = list(_HANDLER_NAME_PATTERNS_PY.finditer(content))
        elif is_ts:
            matches = list(_HANDLER_NAME_PATTERNS_TS.finditer(content))
            # Also check for inline subscribe callbacks
            matches.extend(_SUBSCRIBE_PATTERN_TS.finditer(content))
        else:
            continue

        for match in matches:
            body_lines = _extract_function_body_lines(content, match.start(), is_python)
            if _is_stub_handler(body_lines):
                func_name = match.group(1) if match.lastindex else match.group(0)[:60]
                line_no = content[:match.start()].count("\n") + 1
                violations.append(Violation(
                    check="STUB-001",
                    message=(
                        f"Event handler '{func_name}' appears to be a log-only stub. "
                        f"It must perform a real business action (DB write, HTTP call, "
                        f"state transition) — not just log the event."
                    ),
                    file_path=rel_path,
                    line=line_no,
                    severity="warning",
                ))

    # Second pass: scan service/module files for subscribe callbacks with
    # log-only bodies.  The first pass above only checks handler-named files,
    # but NestJS services often use `.subscribe('event', async (payload) => {})`
    # inline in files named *.service.ts, *.module.ts, etc.
    _subscribe_callback_re = re.compile(
        r"\.subscribe\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(?:async\s+)?\(?(\w*)\)?\s*=>\s*\{",
        re.MULTILINE,
    )
    for file_path in source_files:
        if len(violations) >= _MAX_VIOLATIONS:
            break
        name_lower = file_path.name.lower()
        # Only scan service/module files NOT already covered by the first pass
        is_handler_file = any(kw in name_lower for kw in (
            "handler", "subscriber", "consumer", "listener", "event",
        )) or name_lower in ("main.py", "app.py")
        if is_handler_file:
            continue  # Already scanned above
        # Target service, module, controller files
        if not any(kw in name_lower for kw in (
            "service", "module", "controller", "gateway", "resolver",
        )):
            continue
        if file_path.suffix not in (".ts", ".js"):
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(content) > _MAX_FILE_SIZE:
            continue

        rel_path = file_path.relative_to(project_root).as_posix()
        for match in _subscribe_callback_re.finditer(content):
            if len(violations) >= _MAX_VIOLATIONS:
                break
            # Extract callback body using brace counting (TypeScript)
            body_lines = _extract_function_body_lines(content, match.start(), False)
            if _is_stub_handler(body_lines):
                event_name = match.group(1)
                line_no = content[:match.start()].count("\n") + 1
                violations.append(Violation(
                    check="STUB-001",
                    message=(
                        f"Subscribe callback for '{event_name}' appears to be a "
                        f"log-only stub. It must perform a real business action "
                        f"(DB write, HTTP call, state transition) — not just "
                        f"log the event."
                    ),
                    file_path=rel_path,
                    line=line_no,
                    severity="warning",
                ))

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )
    return violations


# ---------------------------------------------------------------------------
# ENTITY-001..003: Entity coverage scan (v16)
# ---------------------------------------------------------------------------

# Patterns to find ORM model/entity class definitions
_MODEL_CLASS_PY = re.compile(
    r"class\s+(\w+)\s*\([^)]*(?:Base|Model|DeclarativeBase|SQLModel)\b",
    re.MULTILINE,
)
_MODEL_CLASS_TS = re.compile(
    r"@Entity\s*\(\s*\)\s*(?:export\s+)?class\s+(\w+)",
    re.MULTILINE,
)
# Fallback: any class with common ORM decorators
_MODEL_CLASS_TS_ALT = re.compile(
    r"(?:export\s+)?class\s+(\w+)(?:Entity|Model)\b",
    re.MULTILINE,
)

# Patterns to find route/endpoint definitions
_ROUTE_PY = re.compile(
    r"@(?:router|app)\.\s*(?:get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE | re.MULTILINE,
)
_ROUTE_TS = re.compile(
    r"@(?:Get|Post|Put|Patch|Delete|Controller)\s*\(\s*['\"]?([^'\")\s]*)",
    re.MULTILINE,
)

# Patterns to find test files referencing an entity
_TEST_FILE_PATTERNS = ("test_*.py", "*_test.py", "*.spec.ts", "*.test.ts", "*.test.js")


def _normalize_entity_name(name: str) -> str:
    """Normalize entity name for fuzzy matching (lowercase, no underscores/hyphens)."""
    return re.sub(r"[_\-\s]", "", name.lower())


def _find_model_definitions(project_root: Path) -> dict[str, str]:
    """Find all ORM model/entity class definitions in the project.

    Returns a dict mapping normalized entity name to the file path where it's defined.
    """
    models: dict[str, str] = {}

    for file_path in _iter_source_files(project_root):
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel_path = file_path.relative_to(project_root).as_posix()

        if file_path.suffix == ".py":
            for match in _MODEL_CLASS_PY.finditer(content):
                models[_normalize_entity_name(match.group(1))] = rel_path
        elif file_path.suffix in (".ts", ".js"):
            for match in _MODEL_CLASS_TS.finditer(content):
                models[_normalize_entity_name(match.group(1))] = rel_path
            for match in _MODEL_CLASS_TS_ALT.finditer(content):
                models[_normalize_entity_name(match.group(1))] = rel_path

    return models


def _find_route_entities(project_root: Path) -> set[str]:
    """Find entity names referenced in route/endpoint definitions.

    Returns normalized entity names that appear in route paths.
    """
    route_entities: set[str] = set()

    for file_path in _iter_source_files(project_root):
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if file_path.suffix == ".py":
            for match in _ROUTE_PY.finditer(content):
                # Extract entity name from path like /api/invoices/{id}
                parts = match.group(1).strip("/").split("/")
                for part in parts:
                    if part and not part.startswith("{") and not part.startswith(":"):
                        route_entities.add(_normalize_entity_name(part))
        elif file_path.suffix in (".ts", ".js"):
            for match in _ROUTE_TS.finditer(content):
                path = match.group(1).strip("/")
                if path:
                    parts = path.split("/")
                    for part in parts:
                        if part and not part.startswith(":"):
                            route_entities.add(_normalize_entity_name(part))

    return route_entities


def _find_test_entities(project_root: Path) -> set[str]:
    """Find entity names referenced in test files.

    Returns normalized entity names found in test file names and content.
    """
    test_entities: set[str] = set()

    for pattern in _TEST_FILE_PATTERNS:
        for test_file in project_root.rglob(pattern):
            if any(_should_skip_dir(part) for part in test_file.parts):
                continue
            # Extract entity name from test file name
            stem = test_file.stem.replace("test_", "").replace("_test", "").replace(".spec", "").replace(".test", "")
            test_entities.add(_normalize_entity_name(stem))

    return test_entities


def run_entity_coverage_scan(
    project_root: Path,
    parsed_entities: list[dict] | None = None,
) -> list[Violation]:
    """Verify PRD entities have corresponding models, endpoints, and tests.

    When *parsed_entities* is provided (from PRD pre-parsing), checks each entity
    against the codebase for:
    - ENTITY-001: Entity has no ORM model/class definition
    - ENTITY-002: Entity has no CRUD route handlers
    - ENTITY-003: Entity has no test coverage

    When *parsed_entities* is None, scans for models without routes or tests
    (a lightweight completeness check without PRD input).

    Returns violations sorted by severity, capped at ``_MAX_VIOLATIONS``.
    """
    violations: list[Violation] = []

    if not parsed_entities:
        return violations  # No PRD entities to check — skip

    models = _find_model_definitions(project_root)
    route_entities = _find_route_entities(project_root)
    test_entities = _find_test_entities(project_root)

    for entity in parsed_entities:
        # A2 fix: handle both dict entities and plain string entity names
        if isinstance(entity, str):
            entity_name = entity
        else:
            entity_name = entity.get("name", "") if isinstance(entity, dict) else str(entity)
        if not entity_name:
            continue
        norm_name = _normalize_entity_name(entity_name)

        # ENTITY-001: Missing model
        if norm_name not in models:
            violations.append(Violation(
                check="ENTITY-001",
                message=f"PRD entity '{entity_name}' has no ORM model/class definition in the codebase.",
                file_path="(project-wide)",
                line=0,
                severity="warning",
            ))

        # ENTITY-002: Missing routes
        # Check if any route path contains this entity name (singular or plural)
        has_route = (
            norm_name in route_entities
            or norm_name + "s" in route_entities
            or norm_name + "es" in route_entities
            or norm_name.rstrip("s") in route_entities
        )
        if not has_route:
            violations.append(Violation(
                check="ENTITY-002",
                message=f"PRD entity '{entity_name}' has no CRUD endpoints in route definitions.",
                file_path="(project-wide)",
                line=0,
                severity="info",
            ))

        # ENTITY-003: Missing tests
        has_test = (
            norm_name in test_entities
            or norm_name + "s" in test_entities
            or norm_name.rstrip("s") in test_entities
        )
        if not has_test:
            violations.append(Violation(
                check="ENTITY-003",
                message=f"PRD entity '{entity_name}' has no test file coverage.",
                file_path="(project-wide)",
                line=0,
                severity="info",
            ))

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.check, v.message)
    )
    return violations


def run_ui_compliance_scan(project_root: Path, scope: ScanScope | None = None) -> list[Violation]:
    """Scan project for UI compliance violations in component/style files.

    Unlike :func:`run_spot_checks` which runs ALL checks, this function runs
    ONLY UI compliance checks (UI-001..004). Designed for targeted
    post-milestone scanning in ``cli.py``.

    Returns violations sorted by severity, capped at ``_MAX_VIOLATIONS``.
    """
    violations: list[Violation] = []
    source_files = _iter_source_files(project_root)
    if scope and scope.changed_files:
        scope_set = set(scope.changed_files)
        source_files = [f for f in source_files if f.resolve() in scope_set]

    for file_path in source_files:
        if len(violations) >= _MAX_VIOLATIONS:
            break
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel_path = file_path.relative_to(project_root).as_posix()
        extension = file_path.suffix

        file_violations = _check_ui_compliance(content, rel_path, extension)
        violations.extend(file_violations)

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )
    return violations


def run_e2e_quality_scan(project_root: Path, scope: ScanScope | None = None) -> list[Violation]:
    """Scan project for E2E test quality issues.

    Runs E2E-001..006 checks on files in e2e/ and playwright/ directories
    and template files. Also runs:
    - E2E-005 (inverted): warns if app has auth but no auth E2E test found
    - E2E-007: scans E2E_RESULTS.md for role access failures (403/Forbidden)
    Returns violations sorted by severity, capped at _MAX_VIOLATIONS.
    """
    violations: list[Violation] = []
    all_source_files = _iter_source_files(project_root)
    # Scope filtering for per-file checks (E2E-001..004)
    scoped_files = all_source_files
    _scope_active = False
    if scope and scope.changed_files:
        scope_set = set(scope.changed_files)
        scoped_files = [f for f in all_source_files if f.resolve() in scope_set]
        _scope_active = True

    # Track whether any E2E test file contains auth tests (for E2E-005)
    # Use FULL file list for aggregate check to avoid false positives (H1 fix)
    has_auth_e2e_test = False
    has_e2e_tests = False

    # Per-file E2E quality checks on scoped files only
    for file_path in scoped_files:
        if len(violations) >= _MAX_VIOLATIONS:
            break
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel_path = file_path.relative_to(project_root).as_posix()
        extension = file_path.suffix

        file_violations = _check_e2e_quality(content, rel_path, extension)
        violations.extend(file_violations)

        # Track auth test presence for E2E-005 inverted check
        if extension in _EXT_E2E and _RE_E2E_DIR.search(rel_path):
            has_e2e_tests = True
            if _RE_E2E_AUTH_TEST.search(content):
                has_auth_e2e_test = True

    # When scope is active, scan ALL e2e files for auth test presence
    # to avoid false-positive E2E-005 (H1 fix: unchanged auth test files
    # must still be visible for the aggregate check)
    if _scope_active and not has_auth_e2e_test:
        for file_path in all_source_files:
            try:
                rel_path = file_path.relative_to(project_root).as_posix()
                extension = file_path.suffix
                if extension in _EXT_E2E and _RE_E2E_DIR.search(rel_path):
                    has_e2e_tests = True
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    if _RE_E2E_AUTH_TEST.search(content):
                        has_auth_e2e_test = True
                        break
            except OSError:
                continue

    # --- E2E-005: Inverted auth test check ---
    # If app has auth dependencies but no auth E2E test, emit warning
    if has_e2e_tests and not has_auth_e2e_test:
        # Check if project has auth (look for common auth packages)
        _auth_indicators = (
            "passport", "jsonwebtoken", "jwt", "bcrypt", "@nestjs/jwt",
            "flask-login", "django.contrib.auth", "fastapi-users",
            "next-auth", "@auth/", "authjs", "firebase-auth",
        )
        pkg_json = project_root / "package.json"
        req_txt = project_root / "requirements.txt"
        has_auth = False
        for dep_file in (pkg_json, req_txt):
            if dep_file.is_file():
                try:
                    dep_content = dep_file.read_text(encoding="utf-8", errors="replace").lower()
                    if any(ind in dep_content for ind in _auth_indicators):
                        has_auth = True
                        break
                except OSError:
                    pass
        if has_auth:
            violations.append(Violation(
                check="E2E-005",
                message="No auth E2E test found — app has auth dependencies but no login/auth flow test in e2e/ directory",
                file_path="(project)",
                line=0,
                severity="warning",
            ))

    # --- E2E-007: Role access failure in E2E results ---
    results_path = project_root / ".agent-team" / "E2E_RESULTS.md"
    if results_path.is_file():
        try:
            results_content = results_path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(results_content.splitlines(), start=1):
                if _RE_E2E_ROLE_FAILURE.search(line):
                    violations.append(Violation(
                        check="E2E-007",
                        message="Role access failure detected in E2E results — check backend auth middleware/guards",
                        file_path=".agent-team/E2E_RESULTS.md",
                        line=lineno,
                        severity="error",
                    ))
        except OSError:
            pass

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )
    return violations


# ---------------------------------------------------------------------------
# Post-build integrity scans: Deployment, Asset, PRD reconciliation
# ---------------------------------------------------------------------------

# --- Deployment integrity patterns ---

_RE_APP_LISTEN_PORT = re.compile(
    r'\.listen\s*\(\s*(\d{2,5})'
    r'|uvicorn\.run.*port\s*=\s*(\d+)'
    r'|\.set\s*\(\s*[\'"]port[\'"]\s*,\s*(\d+)',
    re.IGNORECASE,
)
_RE_ENV_VAR_NODE = re.compile(r'process\.env\.([A-Z_][A-Z0-9_]*)')
_RE_ENV_VAR_PY = re.compile(
    r'os\.environ\s*\[\s*[\'"]([A-Z_][A-Z0-9_]*)[\'"]\s*\]'
    r'|os\.getenv\s*\(\s*[\'"]([A-Z_][A-Z0-9_]*)[\'"]'
    r'|os\.environ\.get\s*\(\s*[\'"]([A-Z_][A-Z0-9_]*)[\'"]'
)
_RE_ENV_WITH_DEFAULT = re.compile(
    r'process\.env\.\w+\s*(?:\|\||[?]{2})'
    r'|os\.getenv\s*\([^)]+,[^)]+\)'
    r'|os\.environ\.get\s*\([^)]+,[^)]+\)',
)
_BUILTIN_ENV_VARS: frozenset[str] = frozenset({
    "NODE_ENV", "PATH", "HOME", "USER", "SHELL", "TERM", "PWD",
    "HOSTNAME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP",
    "CI", "DEBUG", "VERBOSE", "LOG_LEVEL",
    # AI/LLM provider API keys — always host-provided secrets, never in docker-compose
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CLAUDE_API_KEY",
    "GOOGLE_API_KEY", "AZURE_OPENAI_API_KEY", "TOGETHER_API_KEY",
    "GROQ_API_KEY", "MISTRAL_API_KEY", "COHERE_API_KEY",
    "HUGGING_FACE_TOKEN", "HF_TOKEN",
})
_RE_CORS_ORIGIN = re.compile(
    r'cors\s*\(\s*\{[^}]*origin\s*:\s*[\'"]([^\'"\s]+)[\'"]'
    r'|CORS_ALLOWED_ORIGINS?\s*=\s*[\'"]([^\'"\s]+)[\'"]'
    r'|allow_origins\s*=\s*\[\s*[\'"]([^\'"\s]+)[\'"]'
    r'|enableCors\s*\(\s*\{[^}]*origin\s*:\s*[\'"]([^\'"\s]+)[\'"]',
    re.IGNORECASE | re.DOTALL,
)
_RE_DB_CONN_HOST = re.compile(
    r'mongodb://(?:\w+:?\w*@)?(\w[\w.-]*):'
    r'|postgres(?:ql)?://(?:\w+:?\w*@)?(\w[\w.-]*):'
    r'|mysql://(?:\w+:?\w*@)?(\w[\w.-]*):'
    r'|redis://(?:\w+:?\w*@)?(\w[\w.-]*):'
    r'|host\s*[:=]\s*[\'"](\w[\w.-]*)[\'"]',
    re.IGNORECASE,
)

# --- Asset integrity patterns ---

_RE_ASSET_SRC = re.compile(r'src\s*=\s*[\'"]([^\'"]+)[\'"]')
_RE_ASSET_HREF = re.compile(r'href\s*=\s*[\'"]([^\'"]+)[\'"]')
_RE_ASSET_CSS_URL = re.compile(r'url\(\s*[\'"]?([^)\'"\s]+)[\'"]?\s*\)')
_RE_ASSET_REQUIRE = re.compile(r'require\(\s*[\'"]([^\'"]+)[\'"]')
_RE_ASSET_IMPORT = re.compile(r'from\s+[\'"]([^\'"]+)[\'"]')

_ASSET_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pdf", ".mp4", ".mp3", ".wav", ".ogg", ".webm",
})
_EXT_ASSET_SCAN: frozenset[str] = frozenset({
    ".tsx", ".jsx", ".vue", ".svelte", ".html", ".css", ".scss",
    ".ts", ".js", ".ejs", ".hbs", ".pug",
})


def _parse_docker_compose(project_root: Path) -> dict | None:
    """Parse docker-compose.yml/yaml, returning parsed dict or None."""
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        dc_path = project_root / name
        if dc_path.is_file():
            try:
                import yaml
                result = yaml.safe_load(dc_path.read_text(encoding="utf-8", errors="replace"))
                return result if isinstance(result, dict) else None
            except Exception:
                return None
    return None


def _parse_env_file(path: Path) -> set[str]:
    """Parse a .env file and return set of defined variable names."""
    env_vars: set[str] = set()
    if not path.is_file():
        return env_vars
    try:
        content = path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip common 'export' prefix: export VAR=value (space or tab)
            if line.startswith(("export ", "export\t")):
                line = line.split(None, 1)[1] if len(line.split(None, 1)) > 1 else ""
            if "=" in line:
                key = line.split("=", 1)[0].strip()
                if key:
                    env_vars.add(key)
    except OSError:
        pass
    return env_vars


def _extract_docker_ports(dc: dict) -> dict[str, list[tuple[int, int]]]:
    """Extract port mappings from docker-compose services."""
    result: dict[str, list[tuple[int, int]]] = {}
    services = dc.get("services") or {}
    for svc_name, svc_config in services.items():
        if not isinstance(svc_config, dict):
            continue
        ports = svc_config.get("ports") or []
        mapped: list[tuple[int, int]] = []
        for p in ports:
            p_str = str(p).split("/")[0]  # strip protocol
            parts = p_str.split(":")
            try:
                if len(parts) == 2:
                    mapped.append((int(parts[0]), int(parts[1])))
                elif len(parts) == 3:
                    mapped.append((int(parts[1]), int(parts[2])))
                elif len(parts) == 1:
                    port = int(parts[0])
                    mapped.append((port, port))
            except (ValueError, IndexError):
                continue
        if mapped:
            result[svc_name] = mapped
    return result


def _extract_docker_env_vars(dc: dict) -> set[str]:
    """Extract all environment variable names from docker-compose services."""
    env_vars: set[str] = set()
    services = dc.get("services") or {}
    for _svc, svc_config in services.items():
        if not isinstance(svc_config, dict):
            continue
        env = svc_config.get("environment")
        if isinstance(env, dict):
            env_vars.update(env.keys())
        elif isinstance(env, list):
            for item in env:
                s = str(item)
                if "=" in s:
                    env_vars.add(s.split("=", 1)[0].strip())
                else:
                    env_vars.add(s.strip())
    return env_vars


def _extract_docker_service_names(dc: dict) -> set[str]:
    """Extract all service names from docker-compose."""
    return set((dc.get("services") or {}).keys())


def run_deployment_scan(project_root: Path) -> list[Violation]:
    """Scan for deployment config inconsistencies (DEPLOY-001..004).

    Only runs if docker-compose.yml/yaml exists. Returns warnings.
    """
    dc = _parse_docker_compose(project_root)
    if dc is None:
        return []

    violations: list[Violation] = []
    docker_ports = _extract_docker_ports(dc)
    docker_env = _extract_docker_env_vars(dc)
    docker_services = _extract_docker_service_names(dc)

    # Collect .env file vars
    for env_name in (
        ".env", ".env.example", ".env.local", ".env.development",
        ".env.production", ".env.staging", ".env.test",
    ):
        docker_env.update(_parse_env_file(project_root / env_name))

    container_ports: set[int] = set()
    for port_list in docker_ports.values():
        for _hp, cp in port_list:
            container_ports.add(cp)

    source_files = _iter_source_files(project_root)
    app_listen_ports: list[tuple[str, int, int]] = []
    cors_origins: list[tuple[str, int, str]] = []
    db_hosts: list[tuple[str, int, str]] = []
    env_usages: list[tuple[str, int, str]] = []

    for file_path in source_files:
        if len(violations) >= _MAX_VIOLATIONS:
            break
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel_path = file_path.relative_to(project_root).as_posix()

        for lineno, line in enumerate(content.splitlines(), start=1):
            m = _RE_APP_LISTEN_PORT.search(line)
            if m:
                port_str = next((g for g in m.groups() if g), None)
                if port_str:
                    try:
                        app_listen_ports.append((rel_path, lineno, int(port_str)))
                    except ValueError:
                        pass

            m = _RE_CORS_ORIGIN.search(line)
            if m:
                origin = next((g for g in m.groups() if g), None)
                if origin:
                    cors_origins.append((rel_path, lineno, origin))

            m = _RE_DB_CONN_HOST.search(line)
            if m:
                host = next((g for g in m.groups() if g), None)
                if host and host not in ("localhost", "127.0.0.1", "0.0.0.0"):
                    db_hosts.append((rel_path, lineno, host))

            for env_m in _RE_ENV_VAR_NODE.finditer(line):
                if not _RE_ENV_WITH_DEFAULT.search(line):
                    env_usages.append((rel_path, lineno, env_m.group(1)))
            for env_m in _RE_ENV_VAR_PY.finditer(line):
                var = next((g for g in env_m.groups() if g), None)
                if var and not _RE_ENV_WITH_DEFAULT.search(line):
                    env_usages.append((rel_path, lineno, var))

    # DEPLOY-001: Port mismatch
    for rp, ln, port in app_listen_ports:
        if container_ports and port not in container_ports:
            violations.append(Violation(
                check="DEPLOY-001",
                message=f"Port mismatch: app listens on {port} but docker-compose container ports are {sorted(container_ports)}",
                file_path=rp, line=ln, severity="warning",
            ))

    # DEPLOY-002: Env var not defined
    all_defined = docker_env | _BUILTIN_ENV_VARS
    seen: set[str] = set()
    for rp, ln, var in env_usages:
        if var not in all_defined and var not in seen:
            seen.add(var)
            violations.append(Violation(
                check="DEPLOY-002",
                message=f"Environment variable {var} used but not defined in docker-compose or .env",
                file_path=rp, line=ln, severity="warning",
            ))

    # DEPLOY-003: CORS origin check
    for rp, ln, origin in cors_origins:
        if origin.startswith("http") and "localhost" not in origin and "*" not in origin:
            violations.append(Violation(
                check="DEPLOY-003",
                message=f"CORS origin '{origin}' — verify this matches the actual frontend deployment URL",
                file_path=rp, line=ln, severity="warning",
            ))

    # DEPLOY-004: Service name mismatch
    for rp, ln, host in db_hosts:
        if docker_services and host not in docker_services:
            violations.append(Violation(
                check="DEPLOY-004",
                message=f"Service name '{host}' in connection string not found in docker-compose services {sorted(docker_services)}",
                file_path=rp, line=ln, severity="warning",
            ))

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line))
    return violations


def _is_static_asset_ref(ref: str) -> bool:
    """Check if a reference points to a static asset file."""
    if not ref or ref.startswith(("http://", "https://", "//", "data:", "#", "mailto:")):
        return False
    if any(c in ref for c in ("${", "{%", "{{", "}}")):
        return False
    if ref.startswith(("@/", "~/", "~")):
        return False
    # Strip query string and hash fragment before checking extension
    clean = ref.split("?")[0].split("#")[0]
    return Path(clean).suffix.lower() in _ASSET_EXTENSIONS


def _resolve_asset(ref: str, file_dir: Path, project_root: Path) -> bool:
    """Try to resolve an asset reference to an existing file."""
    ref = ref.split("?")[0].split("#")[0]
    clean = ref.lstrip("/")
    candidates = [
        file_dir / ref,
        project_root / clean,
        project_root / "public" / clean,
        project_root / "src" / clean,
        project_root / "assets" / clean,
        project_root / "static" / clean,
        project_root / "src" / "assets" / clean,
    ]
    for c in candidates:
        try:
            if c.is_file():
                return True
        except (OSError, ValueError):
            continue
    return False


def run_asset_scan(project_root: Path, scope: ScanScope | None = None) -> list[Violation]:
    """Scan for broken static asset references (ASSET-001..003).

    Walks template/component files and checks that src, href, url(),
    require, and import references to static assets exist on disk.
    """
    violations: list[Violation] = []
    scope_set = set(f.resolve() for f in scope.changed_files) if scope and scope.changed_files else None

    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        for filename in filenames:
            if len(violations) >= _MAX_VIOLATIONS:
                break
            file_path = Path(dirpath) / filename
            if scope_set and file_path.resolve() not in scope_set:
                continue
            if file_path.suffix.lower() not in _EXT_ASSET_SCAN:
                continue
            try:
                if file_path.stat().st_size > _MAX_FILE_SIZE:
                    continue
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            rel_path = file_path.relative_to(project_root).as_posix()
            file_dir = file_path.parent
            ext = file_path.suffix.lower()

            for lineno, line in enumerate(content.splitlines(), start=1):
                # ASSET-001: src/href
                for regex in (_RE_ASSET_SRC, _RE_ASSET_HREF):
                    for m in regex.finditer(line):
                        ref = m.group(1)
                        if _is_static_asset_ref(ref) and not _resolve_asset(ref, file_dir, project_root):
                            violations.append(Violation(
                                check="ASSET-001",
                                message=f"Asset reference '{ref}' — file not found on disk",
                                file_path=rel_path, line=lineno, severity="warning",
                            ))
                # ASSET-002: CSS url()
                if ext in (".css", ".scss"):
                    for m in _RE_ASSET_CSS_URL.finditer(line):
                        ref = m.group(1)
                        if _is_static_asset_ref(ref) and not _resolve_asset(ref, file_dir, project_root):
                            violations.append(Violation(
                                check="ASSET-002",
                                message=f"CSS url() reference '{ref}' — file not found on disk",
                                file_path=rel_path, line=lineno, severity="warning",
                            ))
                # ASSET-003: require/import
                for regex in (_RE_ASSET_REQUIRE, _RE_ASSET_IMPORT):
                    for m in regex.finditer(line):
                        ref = m.group(1)
                        if _is_static_asset_ref(ref) and not _resolve_asset(ref, file_dir, project_root):
                            violations.append(Violation(
                                check="ASSET-003",
                                message=f"Asset import '{ref}' — file not found on disk",
                                file_path=rel_path, line=lineno, severity="warning",
                            ))

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line))
    return violations


def parse_prd_reconciliation(report_path: Path) -> list[Violation]:
    """Parse PRD_RECONCILIATION.md and return PRD-001 violations for mismatches."""
    if not report_path.is_file():
        return []
    try:
        content = report_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    violations: list[Violation] = []
    in_mismatch = False

    _re_section = re.compile(r'^#{2,3}\s')
    for lineno, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("### MISMATCH") or stripped.startswith("## MISMATCH"):
            in_mismatch = True
            continue
        if _re_section.match(stripped) and "MISMATCH" not in stripped:
            in_mismatch = False
            continue
        if in_mismatch and stripped.startswith("- "):
            violations.append(Violation(
                check="PRD-001",
                message=f"PRD reconciliation mismatch: {stripped[2:].strip()}",
                file_path=str(report_path.name),
                line=lineno,
                severity="warning",
            ))

    return violations[:_MAX_VIOLATIONS]


# ---------------------------------------------------------------------------
# Database integrity scans: Dual ORM, Default Values, Relationships
# ---------------------------------------------------------------------------


def _detect_data_access_methods(
    project_root: Path,
    source_files: list[Path],
) -> tuple[bool, bool]:
    """Detect whether the project uses ORM(s) and raw SQL queries.

    Returns (has_orm, has_raw_sql).
    """
    has_orm = False
    has_raw = False

    # Check project dependency files for ORM and raw query indicators
    for dep_name in ("package.json",):
        dep_path = project_root / dep_name
        if dep_path.is_file():
            try:
                content = dep_path.read_text(encoding="utf-8", errors="replace").lower()
                # ORM indicators
                if any(kw in content for kw in ("prisma", "typeorm", "sequelize", "mongoose")):
                    has_orm = True
                # Raw query indicators
                if any(kw in content for kw in ("knex", '"pg"', '"mysql2"')):
                    has_raw = True
            except OSError:
                pass

    for dep_name in ("requirements.txt",):
        dep_path = project_root / dep_name
        if dep_path.is_file():
            try:
                content = dep_path.read_text(encoding="utf-8", errors="replace").lower()
                if any(kw in content for kw in ("sqlalchemy", "django")):
                    has_orm = True
                if any(kw in content for kw in ("psycopg", "pymysql", "pymongo")):
                    has_raw = True
            except OSError:
                pass

    # Check .csproj files for NuGet packages
    for f in source_files:
        if f.suffix == ".csproj":
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                if "Microsoft.EntityFrameworkCore" in content:
                    has_orm = True
                if "Dapper" in content:
                    has_raw = True
            except OSError:
                pass

    # Scan source files for code-level indicators
    for f in source_files:
        if f.suffix not in _EXT_ENTITY:
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        ext = f.suffix
        if ext == ".cs":
            if "DbContext" in content or "[Table]" in content or "[Column]" in content:
                has_orm = True
            if any(kw in content for kw in ("SqlConnection", "QueryAsync", "ExecuteAsync")):
                has_raw = True
        elif ext in (".ts", ".js"):
            # Only flag as raw SQL if keyword appears outside comments
            for line in content.splitlines():
                stripped = line.lstrip()
                if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
                    continue
                if _RE_DB_SQL_STRING.search(line):
                    has_raw = True
                    break
        elif ext == ".py":
            if "Base.metadata" in content or "models.Model" in content:
                has_orm = True
            if "cursor.execute" in content:
                has_raw = True

    return (has_orm, has_raw)


def _find_entity_files(
    project_root: Path,
    source_files: list[Path],
) -> list[Path]:
    """Return source files that appear to be ORM entity/model definitions."""
    entity_files: list[Path] = []
    for f in source_files:
        if f.suffix not in _EXT_ENTITY:
            continue
        try:
            rel = f.relative_to(project_root).as_posix()
        except ValueError:
            rel = f.name

        # Check by directory name
        if _RE_ENTITY_DIR.search(rel):
            entity_files.append(f)
            continue

        # Check by content indicators
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if f.suffix == ".cs":
            if _RE_ENTITY_INDICATOR_CS.search(content):
                entity_files.append(f)
        elif f.suffix in (".ts", ".js"):
            if _RE_ENTITY_INDICATOR_TS.search(content):
                entity_files.append(f)
        elif f.suffix == ".py":
            if _RE_ENTITY_INDICATOR_PY.search(content):
                entity_files.append(f)

    return entity_files


def run_dual_orm_scan(project_root: Path, scope: ScanScope | None = None) -> list[Violation]:
    """Detect type mismatches between ORM models and raw SQL queries.

    Only runs if 2+ data access methods are detected (ORM + raw queries).
    Skips gracefully if only one access method found.

    Pattern IDs: DB-001 (enum mismatch), DB-002 (boolean mismatch), DB-003 (datetime mismatch)
    """
    violations: list[Violation] = []

    # Also scan .csproj files for detection
    all_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        for filename in filenames:
            fp = Path(dirpath) / filename
            if fp.suffix in _EXT_ENTITY or fp.suffix == ".csproj":
                all_files.append(fp)

    source_files = _iter_source_files(project_root)
    # H2 fix: detect data access methods with FULL file list (not scoped)
    # so that dual-ORM pattern is correctly identified even when only
    # entity files were changed but raw SQL files were not
    has_orm, has_raw = _detect_data_access_methods(project_root, all_files)

    if not (has_orm and has_raw):
        return []

    # Collect ORM property types from entity files (full list for context)
    entity_files = _find_entity_files(project_root, source_files)
    # Map: property_name_lower -> set of types ("bool", "enum", "string", "datetime")
    orm_prop_types: dict[str, set[str]] = {}

    for ef in entity_files:
        try:
            content = ef.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel_path = ef.relative_to(project_root).as_posix()

        if ef.suffix == ".cs":
            for m in _RE_DB_CSHARP_BOOL_PROP.finditer(content):
                prop_name = m.group(1).lower()
                orm_prop_types.setdefault(prop_name, set()).add("bool")
            for m in _RE_DB_CSHARP_DATETIME_PROP.finditer(content):
                prop_name = m.group(1).lower()
                orm_prop_types.setdefault(prop_name, set()).add("datetime")
            for m in _RE_DB_CSHARP_ENUM_PROP.finditer(content):
                type_name = m.group(1)
                prop_name = m.group(2).lower()
                # Skip common non-enum types using shared frozenset
                if type_name in _CSHARP_NON_ENUM_TYPES:
                    continue
                # Skip types with non-enum suffixes (Dto, Service, Controller, etc.)
                if type_name.endswith(_CSHARP_NON_ENUM_SUFFIXES):
                    continue
                # Skip if type name looks like a known entity (present in entity_info)
                orm_prop_types.setdefault(prop_name, set()).add("enum")

    # H2 fix: apply scope filter to violation-reporting phase only
    # (detection + ORM property collection above used full file lists)
    scoped_source_files = source_files
    if scope and scope.changed_files:
        scope_set = set(f.resolve() for f in scope.changed_files)
        scoped_source_files = [f for f in source_files if f.resolve() in scope_set]

    # Scan raw SQL in source files for type comparison mismatches
    for f in scoped_source_files:
        if f.suffix not in _EXT_ENTITY:
            continue
        if len(violations) >= _MAX_VIOLATIONS:
            break
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if not _RE_DB_SQL_STRING.search(content):
            continue

        rel_path = f.relative_to(project_root).as_posix()

        for lineno, line in enumerate(content.splitlines(), start=1):
            if not _RE_DB_SQL_STRING.search(line):
                continue

            line_lower = line.lower()

            # DB-001: Enum column compared as integer or string in raw SQL
            if _RE_DB_SQL_ENUM_INT_CMP.search(line) or _RE_DB_SQL_ENUM_STR_CMP.search(line):
                for prop, types in orm_prop_types.items():
                    if "enum" in types and re.search(rf'\b{re.escape(prop)}\b', line_lower):
                        violations.append(Violation(
                            check="DB-001",
                            message=f"Possible enum type mismatch: ORM defines '{prop}' as enum but raw SQL compares as literal value",
                            file_path=rel_path,
                            line=lineno,
                            severity="error",
                        ))
                        break

            # DB-002: Boolean column compared as 0/1 in raw SQL
            if _RE_DB_SQL_BOOL_INT.search(line):
                for prop, types in orm_prop_types.items():
                    if "bool" in types and re.search(rf'\b{re.escape(prop)}\b', line_lower):
                        violations.append(Violation(
                            check="DB-002",
                            message=f"Possible boolean type mismatch: ORM defines '{prop}' as bool but raw SQL compares as 0/1",
                            file_path=rel_path,
                            line=lineno,
                            severity="error",
                        ))
                        break

            # DB-003: DateTime column with hardcoded format in raw SQL
            if _RE_DB_SQL_DATETIME_FORMAT.search(line):
                for prop, types in orm_prop_types.items():
                    if "datetime" in types and re.search(rf'\b{re.escape(prop)}\b', line_lower):
                        violations.append(Violation(
                            check="DB-003",
                            message=f"Possible datetime format mismatch: ORM defines '{prop}' as DateTime but raw SQL uses hardcoded date literal",
                            file_path=rel_path,
                            line=lineno,
                            severity="error",
                        ))
                        break

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line))
    return violations


def run_default_value_scan(project_root: Path, scope: ScanScope | None = None) -> list[Violation]:
    """Detect missing defaults and unsafe nullable access in entity models.

    Scans ORM entity/model files for boolean/enum properties without defaults
    and nullable properties used without null guards.

    Pattern IDs: DB-004 (missing default), DB-005 (nullable without null check)
    """
    violations: list[Violation] = []
    source_files = _iter_source_files(project_root)
    entity_files = _find_entity_files(project_root, source_files)
    if scope and scope.changed_files:
        scope_set = set(scope.changed_files)
        entity_files = [f for f in entity_files if f.resolve() in scope_set]

    for ef in entity_files:
        if len(violations) >= _MAX_VIOLATIONS:
            break
        try:
            content = ef.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel_path = ef.relative_to(project_root).as_posix()
        ext = ef.suffix

        if ext == ".cs":
            # DB-004: C# bool without default
            for m in _RE_DB_CSHARP_BOOL_NO_DEFAULT.finditer(content):
                prop_name = m.group(1)
                lineno = content[:m.start()].count("\n") + 1
                violations.append(Violation(
                    check="DB-004",
                    message=f"Boolean property '{prop_name}' has no explicit default — add '= false;' or '= true;'",
                    file_path=rel_path,
                    line=lineno,
                    severity="warning",
                ))

            # DB-004: C# enum without default (L2 fix)
            for m in _RE_DB_CSHARP_ENUM_NO_DEFAULT.finditer(content):
                type_name = m.group(1)
                prop_name = m.group(2)
                # Only flag actual enum types — skip primitives and known non-enums
                if type_name in _CSHARP_NON_ENUM_TYPES:
                    continue
                # Skip types with non-enum suffixes (Dto, Service, Controller, etc.)
                if type_name.endswith(_CSHARP_NON_ENUM_SUFFIXES):
                    continue
                # Skip if it looks like a navigation property (type matches a known entity pattern)
                if type_name.endswith(("Id", "[]")):
                    continue
                lineno = content[:m.start()].count("\n") + 1
                violations.append(Violation(
                    check="DB-004",
                    message=f"Enum property '{prop_name}' (type '{type_name}') has no explicit default — add '= {type_name}.DefaultValue;'",
                    file_path=rel_path,
                    line=lineno,
                    severity="warning",
                ))

            # DB-005: C# nullable property without null check
            nullable_props: list[tuple[str, str]] = []  # (type, name)
            for m in _RE_DB_CSHARP_NULLABLE_PROP.finditer(content):
                nullable_props.append((m.group(1), m.group(2)))

            # Search other source files for unsafe access of nullable props
            if nullable_props:
                for sf in source_files:
                    if sf == ef:
                        continue
                    if len(violations) >= _MAX_VIOLATIONS:
                        break
                    try:
                        sf_content = sf.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    sf_rel = sf.relative_to(project_root).as_posix()

                    for _ntype, nname in nullable_props:
                        # Look for .PropName.Method() without ?.
                        pattern = re.compile(
                            rf'\.{re.escape(nname)}\.(?!\s*\?)(\w+)',
                        )
                        for sm in pattern.finditer(sf_content):
                            # Check if there's a null check in the surrounding context
                            pos = sm.start()
                            context_start = max(0, sf_content.rfind("\n", 0, max(0, pos - 500)))
                            context = sf_content[context_start:pos]
                            if f"{nname} != null" not in context and f"{nname} is not null" not in context and f"?.{nname}" not in sf_content[max(0, pos - 50):pos]:
                                slineno = sf_content[:pos].count("\n") + 1
                                violations.append(Violation(
                                    check="DB-005",
                                    message=f"Nullable property '{nname}' accessed without null check — use '?.' or null guard",
                                    file_path=sf_rel,
                                    line=slineno,
                                    severity="error",
                                ))

        elif ext == ".py":
            # DB-004: Django BooleanField without default
            for m in _RE_DB_DJANGO_BOOL_NO_DEFAULT.finditer(content):
                lineno = content[:m.start()].count("\n") + 1
                violations.append(Violation(
                    check="DB-004",
                    message="BooleanField() without default= parameter — add default=True or default=False",
                    file_path=rel_path,
                    line=lineno,
                    severity="warning",
                ))

            # DB-004: SQLAlchemy Column(Boolean) without default
            for m in _RE_DB_SQLALCHEMY_NO_DEFAULT.finditer(content):
                matched_text = m.group(0)
                if "default" not in matched_text and "server_default" not in matched_text:
                    lineno = content[:m.start()].count("\n") + 1
                    violations.append(Violation(
                        check="DB-004",
                        message="Column(Boolean/Enum) without default — add default= or server_default=",
                        file_path=rel_path,
                        line=lineno,
                        severity="warning",
                    ))

            # DB-005: Python Optional[] property accessed without null guard
            optional_props: list[str] = []
            for opt_m in re.finditer(r'(\w+)\s*:\s*Optional\[', content):
                optional_props.append(opt_m.group(1))
            if optional_props:
                for sf in source_files:
                    if sf == ef or sf.suffix != ".py":
                        continue
                    if len(violations) >= _MAX_VIOLATIONS:
                        break
                    try:
                        sf_content = sf.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    sf_rel = sf.relative_to(project_root).as_posix()
                    for oname in optional_props:
                        pattern = re.compile(rf'\.{re.escape(oname)}\.(\w+)')
                        for om in pattern.finditer(sf_content):
                            pos = om.start()
                            context_start = max(0, sf_content.rfind("\n", 0, max(0, pos - 500)))
                            context = sf_content[context_start:pos]
                            if (f"if {oname}" not in context
                                    and f"if self.{oname}" not in context
                                    and f"{oname} is not None" not in context
                                    and f"{oname} is None" not in context):
                                slineno = sf_content[:pos].count("\n") + 1
                                violations.append(Violation(
                                    check="DB-005",
                                    message=f"Optional property '{oname}' accessed without null guard — check 'if {oname} is not None' first",
                                    file_path=sf_rel,
                                    line=slineno,
                                    severity="error",
                                ))

        elif ext in (".ts", ".js"):
            # DB-005: TypeScript nullable property accessed without optional chaining
            # Find nullable types: prop?: Type  or  prop: Type | null  or  prop: Type | undefined
            ts_nullable_props: list[str] = []
            for ts_m in re.finditer(r'(\w+)\s*\?\s*:', content):
                ts_nullable_props.append(ts_m.group(1))
            for ts_m in re.finditer(r'(\w+)\s*:\s*\w+\s*\|\s*(?:null|undefined)', content):
                prop = ts_m.group(1)
                if prop not in ts_nullable_props:
                    ts_nullable_props.append(prop)
            if ts_nullable_props:
                for sf in source_files:
                    if sf == ef or sf.suffix not in (".ts", ".js"):
                        continue
                    if len(violations) >= _MAX_VIOLATIONS:
                        break
                    try:
                        sf_content = sf.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    sf_rel = sf.relative_to(project_root).as_posix()
                    for tname in ts_nullable_props:
                        # Look for .propName.method() without ?.propName
                        pattern = re.compile(rf'\.{re.escape(tname)}\.(?!\s*\?)(\w+)')
                        for tm in pattern.finditer(sf_content):
                            pos = tm.start()
                            # v10: Skip Prisma client delegate accesses
                            # prisma.model.method() is NOT a nullable access —
                            # Prisma client delegates are always defined
                            _pre_word = sf_content[max(0, pos - 30):pos].rstrip()
                            if re.search(r'\bprisma\s*$', _pre_word):
                                continue
                            # Check for optional chaining in nearby context
                            pre = sf_content[max(0, pos - 50):pos]
                            context_start = max(0, sf_content.rfind("\n", 0, max(0, pos - 500)))
                            context = sf_content[context_start:pos]
                            if (f"?.{tname}" not in pre
                                    and f"{tname} !== null" not in context
                                    and f"{tname} !== undefined" not in context
                                    and f"{tname} != null" not in context):
                                slineno = sf_content[:pos].count("\n") + 1
                                violations.append(Violation(
                                    check="DB-005",
                                    message=f"Nullable property '{tname}' accessed without optional chaining — use '?.{tname}' or add null guard",
                                    file_path=sf_rel,
                                    line=slineno,
                                    severity="error",
                                ))

    # Also scan .prisma files for DB-004
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        for filename in filenames:
            if not filename.endswith(".prisma"):
                continue
            fp = Path(dirpath) / filename
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel_path = fp.relative_to(project_root).as_posix()

            for m in _RE_DB_PRISMA_NO_DEFAULT.finditer(content):
                field_name = m.group(1)
                # Check if the next line has @default
                end_pos = m.end()
                next_line_end = content.find("\n", end_pos + 1)
                if next_line_end == -1:
                    next_line_end = len(content)
                next_line = content[end_pos:next_line_end]
                if "@default" not in next_line:
                    lineno = content[:m.start()].count("\n") + 1
                    violations.append(Violation(
                        check="DB-004",
                        message=f"Prisma field '{field_name}' without @default — add @default(false) or similar",
                        file_path=rel_path,
                        line=lineno,
                        severity="warning",
                    ))

            # M1: Prisma enum fields without @default (user-defined types, not builtins)
            for m in _RE_DB_PRISMA_ENUM_NO_DEFAULT.finditer(content):
                field_name = m.group(1)
                type_name = m.group(2)
                # Skip Prisma built-in types (already handled above)
                if type_name in _PRISMA_BUILTIN_TYPES:
                    continue
                end_pos = m.end()
                next_line_end = content.find("\n", end_pos + 1)
                if next_line_end == -1:
                    next_line_end = len(content)
                next_line = content[end_pos:next_line_end]
                if "@default" not in next_line:
                    lineno = content[:m.start()].count("\n") + 1
                    violations.append(Violation(
                        check="DB-004",
                        message=f"Prisma enum field '{field_name}' (type '{type_name}') without @default — add @default(VALUE)",
                        file_path=rel_path,
                        line=lineno,
                        severity="warning",
                    ))

            # L2: Prisma String fields with status-like names without @default
            for m in _RE_DB_PRISMA_STRING_STATUS_NO_DEFAULT.finditer(content):
                field_name = m.group(1)
                end_pos = m.end()
                next_line_end = content.find("\n", end_pos + 1)
                if next_line_end == -1:
                    next_line_end = len(content)
                next_line = content[end_pos:next_line_end]
                if "@default" not in next_line:
                    lineno = content[:m.start()].count("\n") + 1
                    violations.append(Violation(
                        check="DB-004",
                        message=f"Prisma status field '{field_name}' (String) without @default — add @default(\"Draft\") or similar",
                        file_path=rel_path,
                        line=lineno,
                        severity="warning",
                    ))

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line))
    return violations


def run_relationship_scan(project_root: Path, scope: ScanScope | None = None) -> list[Violation]:
    """Detect incomplete ORM relationship configurations.

    Finds FK columns without navigation properties, navigation properties
    without inverse relationships, and FKs with no relationship config at all.

    Pattern IDs: DB-006 (FK no nav), DB-007 (nav no inverse), DB-008 (FK no config)
    """
    violations: list[Violation] = []
    source_files = _iter_source_files(project_root)
    entity_files = _find_entity_files(project_root, source_files)

    if not entity_files:
        return []

    # M1 fix: determine scoped entity files for violation REPORTING only.
    # entity_info is collected from ALL entity files for full cross-file
    # relationship context (unchanged entity B's nav props must be visible
    # when checking changed entity A's FK references).
    _scoped_entity_rel_paths: set[str] | None = None
    if scope and scope.changed_files:
        scope_set = set(scope.changed_files)
        _scoped_entity_rel_paths = set()
        for f in entity_files:
            if f.resolve() in scope_set:
                _scoped_entity_rel_paths.add(f.relative_to(project_root).as_posix())

    # Collect all entity info: FK props, nav props, config calls
    # entity_name -> {fk_props: [(name, line, file)], nav_props: [(type, name, line, file)]}
    entity_info: dict[str, dict] = {}

    # Also scan configuration files for HasMany/HasOne
    config_references: set[str] = set()  # property names referenced in config

    for ef in entity_files:
        try:
            content = ef.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel_path = ef.relative_to(project_root).as_posix()
        ext = ef.suffix

        if ext == ".cs":
            # Extract class name
            class_match = re.search(r'class\s+(\w+)', content)
            if not class_match:
                continue
            class_name = class_match.group(1)

            entity_data = entity_info.setdefault(class_name, {
                "fk_props": [], "nav_props": [],
            })

            # Find FK properties
            for m in _RE_DB_CSHARP_FK_PROP.finditer(content):
                prop_name = m.group(1)
                # Skip the primary key 'Id'
                if prop_name == "Id":
                    continue
                lineno = content[:m.start()].count("\n") + 1
                entity_data["fk_props"].append((prop_name, lineno, rel_path))

            # Find navigation properties
            for m in _RE_DB_CSHARP_NAV_PROP.finditer(content):
                if m.group(1) is not None:
                    # Collection type: ICollection<T>, List<T>, etc.
                    type_name = m.group(1)
                    prop_name = m.group(2)
                else:
                    # Plain type: public virtual Entity Prop {
                    type_name = m.group(3)
                    prop_name = m.group(4)
                # Skip primitive types using shared frozenset + extras
                if type_name in _CSHARP_NON_ENUM_TYPES or type_name in ("Status", "byte[]"):
                    continue
                # Skip types with non-enum suffixes (likely not navigation targets)
                if type_name.endswith(_CSHARP_NON_ENUM_SUFFIXES):
                    continue
                lineno = content[:m.start()].count("\n") + 1
                entity_data["nav_props"].append((type_name, prop_name, lineno, rel_path))

            # Scan for HasMany/HasOne configuration
            for m in _RE_DB_CSHARP_HAS_MANY.finditer(content):
                config_references.add(m.group(1))

        elif ext in (".ts", ".js"):
            # TypeORM: extract class name and relation details
            class_match = re.search(r'class\s+(\w+)', content)
            if not class_match:
                continue
            class_name = class_match.group(1)

            entity_data = entity_info.setdefault(class_name, {
                "fk_props": [], "nav_props": [],
            })

            # TypeORM @JoinColumn → FK-like reference
            for m in _RE_DB_TYPEORM_JOIN_COLUMN.finditer(content):
                col_name = m.group(1)
                lineno = content[:m.start()].count("\n") + 1
                entity_data["fk_props"].append((col_name, lineno, rel_path))

            # TypeORM relation decorators → navigation properties
            for m in _RE_DB_TYPEORM_RELATION_DETAIL.finditer(content):
                rel_type = m.group(1)  # ManyToOne, OneToMany, etc.
                target_entity = m.group(2)
                lineno = content[:m.start()].count("\n") + 1
                # Find the property name: skip decorator args until closing paren,
                # then look for the property declaration on the same/next line
                after = content[m.end():]
                # Skip past any remaining decorator arguments and closing parens
                paren_match = re.search(r'\)\s*\n?\s*(\w+)\s*[;:?!]', after)
                if paren_match:
                    prop_name = paren_match.group(1)
                else:
                    # Fallback: first word before ; or : in next 200 chars
                    prop_match = re.search(r'(\w+)\s*[;:]', after[:200])
                    prop_name = prop_match.group(1) if prop_match else target_entity.lower()
                entity_data["nav_props"].append((target_entity, prop_name, lineno, rel_path))
                config_references.add(prop_name)

        elif ext == ".py":
            # Django/SQLAlchemy: extract class and FK/relationship details
            class_match = re.search(r'class\s+(\w+)', content)
            if not class_match:
                continue
            class_name = class_match.group(1)

            entity_data = entity_info.setdefault(class_name, {
                "fk_props": [], "nav_props": [],
            })

            # Django FK fields
            for m in _RE_DB_DJANGO_FK_DETAIL.finditer(content):
                field_name = m.group(1)
                target_model = m.group(2)
                lineno = content[:m.start()].count("\n") + 1
                entity_data["fk_props"].append((field_name, lineno, rel_path))
                # Django FK implicitly creates navigation
                entity_data["nav_props"].append((target_model, field_name, lineno, rel_path))

            # SQLAlchemy FK columns
            for m in _RE_DB_SQLALCHEMY_FK_COLUMN.finditer(content):
                col_name = m.group(1)
                target_table = m.group(2)
                lineno = content[:m.start()].count("\n") + 1
                entity_data["fk_props"].append((col_name, lineno, rel_path))

            # SQLAlchemy relationship() calls → navigation
            for m in _RE_DB_SQLALCHEMY_RELATIONSHIP_DETAIL.finditer(content):
                prop_name = m.group(1)
                target_model = m.group(2)
                lineno = content[:m.start()].count("\n") + 1
                entity_data["nav_props"].append((target_model, prop_name, lineno, rel_path))
                config_references.add(prop_name)

    # Also scan all source files for entity configuration classes
    for sf in source_files:
        if sf.suffix != ".cs":
            continue
        try:
            content = sf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _RE_DB_CSHARP_HAS_MANY.finditer(content):
            config_references.add(m.group(1))

    # Build a set of all known entity names for inverse lookup
    all_entity_names = set(entity_info.keys())

    # Check entities for missing navigation, inverse, and config
    for entity_name, data in entity_info.items():
        if len(violations) >= _MAX_VIOLATIONS:
            break

        fk_props = data["fk_props"]
        nav_props = data["nav_props"]
        nav_type_names = {t for t, _n, _l, _f in nav_props}
        nav_prop_names = {n for _t, n, _l, _f in nav_props}

        for fk_name, fk_line, fk_file in fk_props:
            if len(violations) >= _MAX_VIOLATIONS:
                break

            # M1 fix: only report violations for scoped files
            if _scoped_entity_rel_paths is not None and fk_file not in _scoped_entity_rel_paths:
                continue

            # Derive expected nav property name: "TenderId" -> "Tender"
            expected_nav = fk_name[:-2] if fk_name.endswith("Id") else None
            if not expected_nav:
                continue

            has_nav = expected_nav in nav_prop_names or expected_nav in nav_type_names
            has_config = fk_name in config_references or expected_nav in config_references

            if not has_nav and not has_config:
                # DB-008: FK with no navigation AND no config
                violations.append(Violation(
                    check="DB-008",
                    message=f"FK '{fk_name}' has no navigation property and no relationship configuration",
                    file_path=fk_file,
                    line=fk_line,
                    severity="error",
                ))
            elif not has_nav:
                # DB-006: FK without navigation property
                violations.append(Violation(
                    check="DB-006",
                    message=f"FK '{fk_name}' has no navigation property '{expected_nav}' — eager loading will return null",
                    file_path=fk_file,
                    line=fk_line,
                    severity="warning",
                ))

        # DB-007: Navigation property without inverse on related entity (C2 fix)
        for nav_type, nav_name, nav_line, nav_file in nav_props:
            if len(violations) >= _MAX_VIOLATIONS:
                break
            # M1 fix: only report violations for scoped files
            if _scoped_entity_rel_paths is not None and nav_file not in _scoped_entity_rel_paths:
                continue
            # Only check if the related type is a known entity
            if nav_type not in all_entity_names:
                continue
            related_data = entity_info.get(nav_type)
            if not related_data:
                continue
            # Check if related entity has an inverse navigation back to this entity
            related_nav_types = {t for t, _n, _l, _f in related_data["nav_props"]}
            if entity_name not in related_nav_types:
                violations.append(Violation(
                    check="DB-007",
                    message=f"Navigation property '{nav_name}' (type '{nav_type}') has no inverse on '{nav_type}' — add ICollection<{entity_name}> or reference back",
                    file_path=nav_file,
                    line=nav_line,
                    severity="info",
                ))

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line))
    return violations


# ---------------------------------------------------------------------------
# API Contract Verification — run_api_contract_scan()
# ---------------------------------------------------------------------------

_RE_SVC_ROW_START = re.compile(r'^\|\s*SVC-\d+\s*\|', re.MULTILINE)

_RE_FIELD_SCHEMA = re.compile(r'\{[^}]+\}')  # kept for backward compat


def _find_balanced_braces(text: str, start: int = 0) -> str | None:
    """Find the first balanced {...} block in *text* starting from *start*.

    Tracks brace depth so nested objects like ``{a, b: {x, y}, c}`` are
    captured in full.  Returns the matched substring **including** the outer
    braces, or ``None`` if no balanced block is found.
    """
    open_pos = text.find('{', start)
    if open_pos == -1:
        return None
    depth = 0
    for i in range(open_pos, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[open_pos:i + 1]
    return None  # unbalanced


@dataclass
class SvcContract:
    """Parsed SVC-xxx table row from REQUIREMENTS.md."""
    svc_id: str
    frontend_service_method: str
    backend_endpoint: str
    http_method: str
    request_dto: str
    response_dto: str
    request_fields: dict[str, str]   # field_name -> type_hint
    response_fields: dict[str, str]  # field_name -> type_hint


def _parse_field_schema(schema_text: str) -> dict[str, str]:
    """Parse a field schema like '{ id: number, title: string }' into a dict.

    Returns field_name -> type_hint mapping. Returns empty dict if the text
    is just a class name (no braces) or unparseable.
    """
    balanced = _find_balanced_braces(schema_text)
    if not balanced:
        return {}
    inner = balanced[1:-1].strip()  # strip outer braces
    if not inner:
        return {}

    fields: dict[str, str] = {}
    # Split on commas that are NOT inside nested braces or angle brackets
    depth = 0
    current = ""
    for char in inner:
        if char in ('{', '<', '('):
            depth += 1
            current += char
        elif char in ('}', '>', ')'):
            depth -= 1
            current += char
        elif char == ',' and depth == 0:
            _parse_single_field(current.strip(), fields)
            current = ""
        else:
            current += char
    if current.strip():
        _parse_single_field(current.strip(), fields)

    return fields


def _parse_single_field(field_text: str, fields: dict[str, str]) -> None:
    """Parse 'fieldName: type' or bare 'fieldName' into the fields dict."""
    if ':' in field_text:
        parts = field_text.split(':', 1)
        name = parts[0].strip().strip('"').strip("'").rstrip('?')
        type_hint = parts[1].strip()
        if name and type_hint:
            fields[name] = type_hint
        return
    # Bare identifier without type (e.g. shorthand "{id, email, fullName}")
    bare = field_text.strip().strip('"').strip("'").rstrip('?')
    if bare and re.match(r'^[a-zA-Z_]\w*$', bare):
        fields[bare] = ""


def _parse_svc_table(requirements_text: str) -> list[SvcContract]:
    """Parse all SVC-xxx table rows from REQUIREMENTS.md content.

    Supports both 5-column tables (``| ID | Endpoint | Method | Request | Response |``)
    and 6-column tables (``| ID | Frontend Svc | Endpoint | Method | Request | Response |``).
    """
    contracts: list[SvcContract] = []
    for line in requirements_text.splitlines():
        stripped = line.strip()
        if not _RE_SVC_ROW_START.match(stripped):
            continue

        # Split on pipe, trim whitespace, drop empty outer cells
        cells = [c.strip() for c in stripped.split('|')]
        cells = [c for c in cells if c]  # remove "" from leading/trailing |

        if len(cells) < 5:
            continue  # malformed row

        svc_id = cells[0].strip()
        if not svc_id.startswith("SVC-"):
            continue

        if len(cells) >= 6:
            # 6-column: ID | Frontend Svc | Endpoint | Method | Request | Response
            frontend_sm = cells[1]
            backend_ep = cells[2]
            http_method = cells[3]
            request_dto = cells[4]
            response_dto = cells[5]
        else:
            # 5-column: ID | Endpoint | Method | Request | Response
            frontend_sm = ""
            backend_ep = cells[1]
            http_method = cells[2]
            request_dto = cells[3]
            response_dto = cells[4]

        request_fields = _parse_field_schema(request_dto)
        response_fields = _parse_field_schema(response_dto)

        contracts.append(SvcContract(
            svc_id=svc_id,
            frontend_service_method=frontend_sm,
            backend_endpoint=backend_ep,
            http_method=http_method,
            request_dto=request_dto,
            response_dto=response_dto,
            request_fields=request_fields,
            response_fields=response_fields,
        ))
    return contracts


def _to_pascal_case(camel_name: str) -> str:
    """Convert camelCase field name to PascalCase (for C# property matching).

    Examples: 'tenderTitle' -> 'TenderTitle', 'id' -> 'Id'
    """
    if not camel_name:
        return camel_name
    return camel_name[0].upper() + camel_name[1:]


def _extract_identifiers_from_file(content: str) -> set[str]:
    """Extract all word-boundary identifiers from a source file.

    Returns a set of all tokens that look like identifiers (letters, digits, underscore).
    This is intentionally broad — the caller filters against known field names.
    """
    return set(re.findall(r'\b[a-zA-Z_]\w*\b', content))


def _find_files_by_pattern(
    project_root: Path,
    pattern: str,
    scope: "ScanScope | None" = None,
) -> list[Path]:
    """Find source files whose relative path matches the given regex pattern."""
    compiled = re.compile(pattern, re.IGNORECASE)
    matched: list[Path] = []
    source_files = _iter_source_files(project_root)
    if scope and scope.changed_files:
        scope_set = set(scope.changed_files)
        source_files = [f for f in source_files if f.resolve() in scope_set]
    for f in source_files:
        rel = f.relative_to(project_root).as_posix()
        if compiled.search(rel):
            matched.append(f)
    return matched


def _check_backend_fields(
    contract: SvcContract,
    project_root: Path,
    violations: list[Violation],
) -> None:
    """Check that backend DTO files contain all fields from the contract schema."""
    if not contract.response_fields:
        return

    # Find backend files (controllers, DTOs, models, handlers)
    backend_patterns = [
        r'(?:controllers?|handlers?|endpoints?)',
        r'(?:dto|dtos|models?|entities|viewmodels?|responses?)',
    ]
    backend_files: list[Path] = []
    for pat in backend_patterns:
        backend_files.extend(_find_files_by_pattern(project_root, pat))

    if not backend_files:
        return

    # Collect all identifiers from backend files
    all_backend_ids: set[str] = set()
    for bf in backend_files:
        try:
            content = bf.read_text(encoding="utf-8", errors="replace")
            if len(content) > _MAX_FILE_SIZE:
                continue
            all_backend_ids.update(_extract_identifiers_from_file(content))
        except OSError:
            continue

    if not all_backend_ids:
        return

    for field_name, type_hint in contract.response_fields.items():
        pascal_name = _to_pascal_case(field_name)
        # Accept either camelCase or PascalCase in backend code
        if field_name not in all_backend_ids and pascal_name not in all_backend_ids:
            violations.append(Violation(
                check="API-001",
                message=(
                    f"{contract.svc_id}: Backend missing field '{field_name}' "
                    f"(PascalCase: '{pascal_name}') from response schema. "
                    f"Expected type: {type_hint}"
                ),
                file_path="REQUIREMENTS.md",
                line=0,
                severity="error",
            ))


def _check_frontend_fields(
    contract: SvcContract,
    project_root: Path,
    violations: list[Violation],
) -> None:
    """Check that frontend model/service files use exact field names from the contract.

    Prioritises type-definition files (models, interfaces, types, dto) over
    general usage files (services, clients).  When type-def files exist, a
    field must appear in at least one of them; its presence only in a service
    or component file is not enough.  This catches interface definition
    mismatches even when services still reference the old name.
    """
    if not contract.response_fields:
        return

    # --- Phase 1: type-definition files (models, interfaces, types, dto) ---
    type_def_patterns = [r'(?:models?|interfaces?|types?|dto)']
    type_def_files: list[Path] = []
    for pat in type_def_patterns:
        type_def_files.extend(_find_files_by_pattern(project_root, pat))

    type_def_ids: set[str] = set()
    for ff in type_def_files:
        try:
            content = ff.read_text(encoding="utf-8", errors="replace")
            if len(content) > _MAX_FILE_SIZE:
                continue
            type_def_ids.update(_extract_identifiers_from_file(content))
        except OSError:
            continue

    # --- Phase 2: fallback to all frontend files if no type-defs found ---
    check_ids: set[str]
    if type_def_ids:
        check_ids = type_def_ids
    else:
        usage_patterns = [r'(?:services?|clients?|api)']
        usage_files: list[Path] = []
        for pat in usage_patterns:
            usage_files.extend(_find_files_by_pattern(project_root, pat))
        if not usage_files:
            return
        check_ids = set()
        for ff in usage_files:
            try:
                content = ff.read_text(encoding="utf-8", errors="replace")
                if len(content) > _MAX_FILE_SIZE:
                    continue
                check_ids.update(_extract_identifiers_from_file(content))
            except OSError:
                continue
        if not check_ids:
            return

    for field_name, type_hint in contract.response_fields.items():
        # Frontend must use the exact camelCase name from the schema
        if field_name not in check_ids:
            violations.append(Violation(
                check="API-002",
                message=(
                    f"{contract.svc_id}: Frontend missing field '{field_name}' "
                    f"from response schema. Expected type: {type_hint}. "
                    f"The frontend model/interface must use this exact field name."
                ),
                file_path="REQUIREMENTS.md",
                line=0,
                severity="error",
            ))


_TYPE_COMPAT_MAP: dict[str, set[str]] = {
    "number": {"number", "int", "long", "float", "double", "decimal", "integer", "bigint"},
    "string": {"string", "str", "datetime", "date", "guid", "uuid", "iso8601"},
    "boolean": {"boolean", "bool"},
}


def _check_type_compatibility(
    contract: SvcContract,
    project_root: Path,
    violations: list[Violation],
) -> None:
    """Check that field types in backend/frontend are compatible with the contract."""
    if not contract.response_fields:
        return

    for field_name, type_hint in contract.response_fields.items():
        normalized = type_hint.lower().strip().strip('"').strip("'")
        # Skip bare identifiers (no type provided) and complex types
        if not normalized:
            continue
        if any(c in normalized for c in ('{', '<', '[', '|', 'array', 'list')):
            continue

        # Check if the type looks like it could be mismatched
        is_known = False
        for _base_type, compat_set in _TYPE_COMPAT_MAP.items():
            if normalized in compat_set:
                is_known = True
                break

        if not is_known and normalized not in ("enum", "object", "any", "-"):
            violations.append(Violation(
                check="API-003",
                message=(
                    f"{contract.svc_id}: Field '{field_name}' has unusual type "
                    f"'{type_hint}' — verify backend/frontend type compatibility."
                ),
                file_path="REQUIREMENTS.md",
                line=0,
                severity="warning",
            ))


def _check_enum_serialization(project_root: Path, scope: ScanScope | None = None) -> list[Violation]:
    """ENUM-004: Check .NET projects for global JsonStringEnumConverter.

    ASP.NET serializes enums as integers by default. Without a global
    JsonStringEnumConverter, every enum field sent to the frontend will
    be an integer while the frontend expects a string.
    """
    # 1. Detect .NET — check for .csproj files (filter out excluded dirs)
    csproj_files = [
        f for f in project_root.rglob("*.csproj")
        if not _path_in_excluded_dir(f.relative_to(project_root))
    ]
    if not csproj_files:
        return []  # Not a .NET project — skip entirely

    # 2. Check for global JsonStringEnumConverter in startup files
    for startup_name in ("Program.cs", "Startup.cs"):
        for startup_file in project_root.rglob(startup_name):
            if _path_in_excluded_dir(startup_file.relative_to(project_root)):
                continue
            try:
                content = startup_file.read_text(errors="ignore")
                if "JsonStringEnumConverter" in content:
                    return []  # Globally configured — all enums serialize as strings
            except OSError:
                continue

    # 3. No global converter found — flag it
    return [Violation(
        check="ENUM-004",
        message=(
            "No global JsonStringEnumConverter configured. All C# enums will serialize "
            "as integers (0, 1, 2) but frontend code expects strings ('submitted', 'approved'). "
            "Add to Program.cs: builder.Services.AddControllers().AddJsonOptions(o => "
            "o.JsonSerializerOptions.Converters.Add(new JsonStringEnumConverter()));"
        ),
        file_path="Program.cs",
        line=0,
        severity="error",
    )]


def _check_cqrs_persistence(project_root: Path, scope: ScanScope | None = None) -> list[Violation]:
    """SDL-001: CQRS command handlers missing persistence calls.

    Checks if command handler files contain at least one persistence keyword.
    File-level check (not method-body parsing) for simplicity and reliability.
    """
    violations: list[Violation] = []

    # Persistence keywords — if a command handler contains NONE of these, flag it
    _PERSISTENCE_KEYWORDS = (
        "SaveChangesAsync", "SaveChanges", "CommitAsync", "Commit(",
        "_repository.Add", "_repository.Update", "_repository.Delete",
        "_repository.Remove", "_repository.Insert",
        "_context.Add", "_context.Update", "_dbContext.Add", "_dbContext.Update",
        "_unitOfWork.Complete", "_unitOfWork.SaveChanges", "_unitOfWork.Commit",
        "session.flush", "db.commit", "await session.commit",
        "db.session.add", "db.session.commit",
    )

    # Skip keywords — handlers that only dispatch events legitimately don't persist
    _SKIP_KEYWORDS = (
        "INotificationHandler", "_mediator.Publish", "_eventBus",
        "_messageQueue", "IEventHandler", "EventHandler",
    )

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fname in files:
            # Match command handler files, exclude query handlers
            if not any(p.lower() in fname.lower() for p in ("commandhandler", "command_handler")):
                continue
            if any(skip.lower() in fname.lower() for skip in ("queryhandler", "query_handler", "test", "spec")):
                continue

            fpath = Path(root) / fname
            if scope and scope.changed_files:
                if fpath.resolve() not in set(scope.changed_files):
                    continue

            try:
                content = fpath.read_text(errors="ignore")
            except OSError:
                continue

            # Skip event-only handlers
            if any(sk in content for sk in _SKIP_KEYWORDS):
                continue

            # Check for persistence
            if not any(pk in content for pk in _PERSISTENCE_KEYWORDS):
                rel = fpath.relative_to(project_root).as_posix()
                violations.append(Violation(
                    check="SDL-001",
                    message=(
                        f"Command handler '{fname}' contains no persistence call "
                        f"(SaveChangesAsync, SaveChanges, Commit, etc.). "
                        f"Data modifications will be lost. Add a persistence call."
                    ),
                    file_path=rel,
                    line=0,
                    severity="error",
                ))

            if len(violations) >= _MAX_VIOLATIONS:
                break

    return sorted(violations, key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line))


# Regex to parse TypeScript interface field declarations
# Matches both multi-line (field at line start) and single-line (field after ; or {)
_RE_TS_INTERFACE_FIELD = re.compile(r'(?:^|[;{])\s*(\w+)\s*(\?)?\s*:', re.MULTILINE)

# Regex to match the START of a TypeScript interface/type declaration (up to the opening brace).
# The body is then extracted using _find_balanced_braces() to handle nested type literals.
_RE_TS_INTERFACE_START = re.compile(
    r'(?:export\s+)?(?:interface|type)\s+(\w+)\s*(?:extends\s+[^{]+)?\s*(?:=\s*)?\{',
    re.DOTALL,
)

# Kept for backward compat / other call-sites
_RE_TS_INTERFACE_BLOCK = re.compile(
    r'(?:export\s+)?(?:interface|type)\s+(\w+)\s*(?:extends\s+[^{]+)?\s*(?:=\s*)?\{([^}]*)\}',
    re.DOTALL,
)


def _strip_nested_braces(body: str) -> str:
    """Remove content inside nested ``{...}`` blocks, keeping only top-level tokens.

    Example::

        "id: string; assignee: { id: string; fullName: string } | null; title: string"
        →  "id: string; assignee:  | null; title: string"

    This prevents ``_RE_TS_INTERFACE_FIELD`` from matching fields that live
    inside nested type literals (e.g. ``fullName`` inside ``assignee``).
    """
    result: list[str] = []
    depth = 0
    for char in body:
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        elif depth == 0:
            result.append(char)
    return ''.join(result)


# Request / command interface name suffixes — these model the *request body*
# sent TO the backend, not the response coming back. They should be excluded
# from the bidirectional response-field check.
_REQUEST_SUFFIXES: tuple[str, ...] = (
    'Request', 'Payload', 'Input', 'Args', 'Params', 'Command',
    'CreateRequest', 'UpdateRequest', 'DeleteRequest',
)

# Universal fields to skip in bidirectional check
_UNIVERSAL_FIELDS: frozenset[str] = frozenset({
    "id", "createdAt", "updatedAt", "createdBy", "updatedBy",
})

# UI-only fields to skip in bidirectional check
_UI_ONLY_FIELDS: frozenset[str] = frozenset({
    "isLoading", "isSelected", "isExpanded", "className",
    "key", "ref", "children", "style",
})


def _check_frontend_extra_fields(
    contract: SvcContract,
    project_root: Path,
    violations: list[Violation],
) -> None:
    """API-002 bidirectional: Check frontend interface for fields NOT in SVC response schema.

    For each SVC entry with response_fields, find matching frontend TypeScript interfaces
    and flag extra fields that the backend won't provide.
    """
    if not contract.response_fields:
        return

    svc_field_names = set(contract.response_fields.keys())
    svc_field_names_lower = {f.lower() for f in svc_field_names}

    # Find frontend type/interface files
    type_def_patterns = [r'(?:models?|interfaces?|types?|dto)']
    type_def_files: list[Path] = []
    for pat in type_def_patterns:
        type_def_files.extend(_find_files_by_pattern(project_root, pat))

    # Only check TypeScript files — exclude backend-only paths (Fix 3)
    ts_files = [
        f for f in type_def_files
        if f.suffix in ('.ts', '.tsx')
        and 'backend' not in f.relative_to(project_root).parts
    ]
    if not ts_files:
        return

    for ts_file in ts_files:
        try:
            content = ts_file.read_text(encoding="utf-8", errors="replace")
            if len(content) > _MAX_FILE_SIZE:
                continue
        except OSError:
            continue

        # Find all interface/type blocks using start-pattern + balanced braces
        for match in _RE_TS_INTERFACE_START.finditer(content):
            iface_name = match.group(1)

            # Fix 4: Skip request/command interfaces — they model the request
            # body, not the response shape.
            if iface_name.endswith(_REQUEST_SUFFIXES):
                continue

            # Extract balanced body (handles nested type literals)
            brace_start = match.end() - 1  # position of the opening {
            balanced = _find_balanced_braces(content, brace_start)
            if not balanced:
                continue
            interface_body = balanced[1:-1]  # strip outer braces

            # Strip nested braces to avoid matching fields inside nested
            # type literals (e.g. assignee: { id, fullName })
            flat_body = _strip_nested_braces(interface_body)

            # Parse field declarations from the flattened body
            interface_fields: dict[str, bool] = {}  # field_name -> is_optional
            for field_match in _RE_TS_INTERFACE_FIELD.finditer(flat_body):
                field_name = field_match.group(1)
                is_optional = field_match.group(2) == '?'
                interface_fields[field_name] = is_optional

            if not interface_fields:
                continue

            # Check overlap — interface must have >=50% of SVC *domain-specific*
            # fields to be a match.  Exclude universal fields (id, createdAt, …)
            # from both sets so that common timestamp/ID fields don't inflate the
            # overlap score and cause false matches (Fix 5).
            universal_lower = {f.lower() for f in _UNIVERSAL_FIELDS}
            interface_field_names_lower = {f.lower() for f in interface_fields}
            svc_domain_lower = svc_field_names_lower - universal_lower
            iface_domain_lower = interface_field_names_lower - universal_lower
            if not svc_domain_lower:
                continue  # SVC entry has only universal fields — skip
            domain_overlap = svc_domain_lower & iface_domain_lower
            if len(domain_overlap) < len(svc_domain_lower) * 0.5:
                continue  # Not enough domain-specific overlap — different type

            # Found a matching interface — check for extra fields
            rel = ts_file.relative_to(project_root).as_posix()
            for iface_field, is_optional in interface_fields.items():
                # Skip universal and UI-only fields
                if iface_field in _UNIVERSAL_FIELDS or iface_field in _UI_ONLY_FIELDS:
                    continue

                # Check if field exists in SVC response (case-insensitive)
                if iface_field.lower() not in svc_field_names_lower:
                    severity = "warning" if is_optional else "error"
                    violations.append(Violation(
                        check="API-002",
                        message=(
                            f"{contract.svc_id}: Frontend interface expects field "
                            f"'{iface_field}' but response schema does not include it. "
                            f"Backend must either add this field to the response DTO or "
                            f"frontend must remove it from the interface."
                        ),
                        file_path=rel,
                        line=0,
                        severity=severity,
                    ))


def run_silent_data_loss_scan(
    project_root: Path,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Scan project for silent data loss patterns (SDL-001).

    Wraps _check_cqrs_persistence() following the standard scan function signature.

    Returns:
        List of Violation objects (SDL-001).
    """
    violations = _check_cqrs_persistence(project_root, scope)
    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )
    return violations


def run_api_contract_scan(
    project_root: Path,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Scan project for API contract violations between SVC-xxx specs and code.

    Parses the SVC-xxx wiring table from REQUIREMENTS.md, extracts field schemas,
    and cross-references them against backend DTO properties and frontend model
    field names. Only produces violations for rows that have explicit field schemas
    (rows with just class names are skipped — backward compatible).

    Returns:
        List of Violation objects (API-001, API-002, API-003, API-004, ENUM-004).
    """
    violations: list[Violation] = []

    # Find REQUIREMENTS.md (check milestone dirs too)
    req_paths = [
        project_root / "REQUIREMENTS.md",
        project_root / ".agent-team" / "REQUIREMENTS.md",
    ]
    # Also check milestone directories
    milestones_dir = project_root / ".agent-team" / "milestones"
    if milestones_dir.is_dir():
        for ms_dir in sorted(milestones_dir.iterdir()):
            if ms_dir.is_dir():
                req_path = ms_dir / "REQUIREMENTS.md"
                if req_path.is_file():
                    req_paths.append(req_path)

    requirements_text = ""
    for req_path in req_paths:
        if req_path.is_file():
            try:
                requirements_text += "\n" + req_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

    if not requirements_text:
        # ENUM-004 check runs regardless of SVC table presence
        violations.extend(_check_enum_serialization(project_root, scope))
        violations = violations[:_MAX_VIOLATIONS]
        violations.sort(
            key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
        )
        return violations

    # Parse SVC-xxx table
    contracts = _parse_svc_table(requirements_text)
    if not contracts:
        # ENUM-004 check runs regardless of SVC table presence
        violations.extend(_check_enum_serialization(project_root, scope))
        violations = violations[:_MAX_VIOLATIONS]
        violations.sort(
            key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
        )
        return violations

    # Only check contracts that have field schemas (backward compat)
    contracts_with_schemas = [
        c for c in contracts
        if c.response_fields or c.request_fields
    ]

    if not contracts_with_schemas:
        # ENUM-004 check runs regardless of SVC table presence
        violations.extend(_check_enum_serialization(project_root, scope))
        violations = violations[:_MAX_VIOLATIONS]
        violations.sort(
            key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
        )
        return violations

    # Run all checks (API-001, API-002 forward, API-003, API-002 bidirectional)
    for contract in contracts_with_schemas:
        if len(violations) >= _MAX_VIOLATIONS:
            break
        _check_backend_fields(contract, project_root, violations)
        _check_frontend_fields(contract, project_root, violations)
        _check_type_compatibility(contract, project_root, violations)
        _check_frontend_extra_fields(contract, project_root, violations)

    # API-004: Check request field passthrough (frontend sends → backend accepts)
    violations.extend(_check_request_field_passthrough(contracts_with_schemas, project_root, scope))

    # ENUM-004: Check .NET enum serialization (runs as part of API contract scan)
    violations.extend(_check_enum_serialization(project_root, scope))

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )
    return violations


# ---------------------------------------------------------------------------
# XREF-001: Frontend-backend endpoint cross-reference scan
# ---------------------------------------------------------------------------

# Angular HttpClient pattern: this.http.get/post/put/delete/patch(...)
# Uses nested-generic-aware pattern to handle <Outer<Inner>> type params
_RE_ANGULAR_HTTP = re.compile(
    r"""(?:this\.)?(?:http|httpClient)\s*\.\s*"""
    r"""(get|post|put|delete|patch)\s*(?:<(?:[^<>]|<[^>]*>)*>)?\s*\(\s*"""
    r"""[`'"](.*?)[`'"]""",
    re.IGNORECASE,
)

# Axios pattern: axios.get/post/put/delete/patch(...) or api.get/post(...)
# Uses nested-generic-aware pattern to handle <Outer<Inner>> type params
_RE_AXIOS = re.compile(
    r"""(?:axios|api|apiClient|axiosInstance|client|http)\s*\.\s*"""
    r"""(get|post|put|delete|patch)\s*(?:<(?:[^<>]|<[^>]*>)*>)?\s*\(\s*"""
    r"""[`'"](.*?)[`'"]""",
    re.IGNORECASE,
)

# fetch() pattern: fetch('url') or fetch(`url`, { method: ... })
_RE_FETCH = re.compile(
    r"""fetch\s*\(\s*[`'"](.*?)[`'"]""",
    re.IGNORECASE,
)

# fetch() method extraction: { method: 'POST' } or { method: "PUT" }
_RE_FETCH_METHOD = re.compile(
    r"""method\s*:\s*['"](\w+)['"]""",
    re.IGNORECASE,
)

# .NET class-level [Route("api/...")] or [Route("[controller]")]
_RE_DOTNET_ROUTE = re.compile(
    r"""\[Route\(\s*["'](.*?)["']\s*\)\]""",
    re.IGNORECASE,
)

# .NET controller class name
_RE_DOTNET_CONTROLLER = re.compile(
    r"""class\s+(\w+Controller)\s*""",
    re.IGNORECASE,
)

# .NET HTTP method attribute [HttpGet("path")], [HttpPost], etc.
_RE_DOTNET_HTTP_METHOD = re.compile(
    r"""\[(Http(?:Get|Post|Put|Delete|Patch))\s*(?:\(\s*["'](.*?)["']\s*\))?\]""",
    re.IGNORECASE,
)

# Express router pattern: router.get('/path', ...) or app.get('/path', ...)
_RE_EXPRESS_ROUTE = re.compile(
    r"""(?:router|app)\s*\.\s*(get|post|put|delete|patch|all)\s*\(\s*"""
    r"""['"`](.*?)['"`]""",
    re.IGNORECASE,
)

# Express app.use() mount: app.use('/api/v1', someRouter)
_RE_EXPRESS_MOUNT = re.compile(
    r"""app\s*\.\s*use\s*\(\s*['"`](.*?)['"`]""",
    re.IGNORECASE,
)

# Flask route decorator: @app.route('/path', methods=['GET', 'POST'])
# or @blueprint.route('/path')
_RE_FLASK_ROUTE = re.compile(
    r"""@\s*(?:\w+\.)?route\s*\(\s*['"`](.*?)['"`]"""
    r"""(?:\s*,\s*methods\s*=\s*\[(.*?)\])?""",
    re.IGNORECASE,
)

# FastAPI route decorator: @app.get('/path'), @router.post('/path')
_RE_FASTAPI_ROUTE = re.compile(
    r"""@\s*(?:\w+\.)\s*(get|post|put|delete|patch)\s*\(\s*"""
    r"""['"`](.*?)['"`]""",
    re.IGNORECASE,
)

# Django path() in urls.py: path('api/items/', views.item_list)
_RE_DJANGO_PATH = re.compile(
    r"""path\s*\(\s*['"`](.*?)['"`]""",
    re.IGNORECASE,
)


_FrontendCall = collections.namedtuple("_FrontendCall", ["method", "path", "file_path", "line"])
_BackendRoute = collections.namedtuple("_BackendRoute", ["method", "path", "file_path", "line"])


# Directories to skip when scanning for XREF — extends EXCLUDED_DIRS
_XREF_SKIP_PARTS: frozenset[str] = EXCLUDED_DIRS | frozenset({".env"})

# File suffixes to skip (test files, specs, etc.)
_XREF_SKIP_SUFFIXES: tuple[str, ...] = (
    ".spec.ts", ".spec.js", ".test.ts", ".test.js",
    ".spec.tsx", ".test.tsx", ".spec.jsx", ".test.jsx",
    ".d.ts",
)


def _normalize_api_path(path: str) -> str:
    """Normalize an API path for matching.

    - Strips protocol + host
    - Replaces path parameter patterns with ``{param}``
    - Lowercases
    - Strips trailing slashes and leading double-slashes
    - Removes ``/api/v1`` or ``/api`` prefix for matching flexibility

    Examples::

        '/api/v1/tenders/${id}' → 'tenders/{param}'
        'https://localhost:5000/api/items' → 'items'
        '/Tenders/GetAll' → 'tenders/getall'
    """
    p = path.strip()

    # Strip protocol + host
    if "://" in p:
        idx = p.index("://") + 3
        slash_idx = p.find("/", idx)
        if slash_idx >= 0:
            p = p[slash_idx:]
        else:
            return ""

    # Strip leading base URL variable interpolations (contain `.`, indicating
    # object property access like ${this.apiUrl} or ${environment.apiUrl}).
    # These are NOT path parameters — they're base URL prefixes.
    # Mid-path params like /tenders/${tenderId}/approval are unaffected.
    p = re.sub(r'^\$\{[^}]*\.[^}]*\}\s*/?', '/', p)

    # Replace remaining template literal interpolations: ${...} → {param}
    p = re.sub(r'\$\{[^}]*\}', '{param}', p)
    # Replace :param → {param}
    p = re.sub(r'/:([^/]+)', '/{param}', p)
    # Replace [controller] placeholder
    p = re.sub(r'\[controller\]', '{controller}', p, flags=re.IGNORECASE)
    # Replace <type:param> (Flask style) → {param}
    p = re.sub(r'<[^>]*>', '{param}', p)
    # Replace {id}, {id:int}, {tenantId} etc. → {param}
    p = re.sub(r'\{[^}]*\}', '{param}', p)

    # Lowercase
    p = p.lower()

    # Ensure leading slash before prefix check
    if not p.startswith("/"):
        p = "/" + p

    # Remove common API prefixes for matching flexibility
    for prefix in ("/api/v1/", "/api/v2/", "/api/"):
        if p.startswith(prefix):
            p = "/" + p[len(prefix):]
            break

    # Normalize slashes
    p = p.rstrip("/")
    if not p.startswith("/"):
        p = "/" + p

    return p


def _is_external_url(path: str) -> bool:
    """Return True if the path points to an external (non-localhost) URL."""
    lower = path.lower().strip()
    if "://" in lower:
        # Allow localhost URLs
        for local in ("localhost", "127.0.0.1", "0.0.0.0"):
            if local in lower:
                return False
        return True
    return False


def _should_skip_xref_file(file_path: Path, project_root: Path) -> bool:
    """Return True if the file should be skipped for XREF scanning."""
    try:
        parts = file_path.relative_to(project_root).parts
    except ValueError:
        return True

    # Skip directories
    for part in parts:
        if part in _XREF_SKIP_PARTS:
            return True

    # Skip test files
    name = file_path.name
    for suffix in _XREF_SKIP_SUFFIXES:
        if name.endswith(suffix):
            return True

    # Skip e2e directories
    for part in parts:
        if part in ("e2e", "__tests__", "tests", "test"):
            return True

    return False


def _extract_frontend_http_calls(
    project_root: Path,
    scope: ScanScope | None,
) -> list["_FrontendCall"]:
    """Extract all HTTP calls from frontend source files.

    Scans TypeScript/JavaScript files for Angular HttpClient, Axios, and
    fetch() patterns.  Skips external URLs (unless localhost), test files,
    and build artifacts.

    When ``scope`` is provided, collects ALL calls from ALL files (needed for
    complete matching), but the caller should only report violations for
    scoped files (same v6 pattern as other scans).
    """
    calls: list[_FrontendCall] = []
    frontend_extensions = (".ts", ".tsx", ".js", ".jsx")

    # BUG-1 fix: regex for Angular variable-URL refs (no quotes around URL)
    # e.g., this.http.get<Task>(this.apiUrl, ...) or this.http.post(this.apiUrl, data)
    # Uses nested-generic-aware pattern: <Outer<Inner>> instead of simple <[^>]*>
    re_angular_var = re.compile(
        r"""(?:this\.)?(?:http|httpClient)\s*\.\s*"""
        r"""(get|post|put|delete|patch)\s*(?:<(?:[^<>]|<[^>]*>)*>)?\s*\(\s*"""
        r"""(this\.\w+)""",
        re.IGNORECASE,
    )
    # Regex to resolve class field values like: private apiUrl = '/api/tasks'
    # or: private apiUrl = `${environment.apiUrl}/tasks`
    re_field_value = re.compile(
        r"""(?:private|readonly|public|protected|\s)\s*(\w+)\s*[:=]\s*[`'"](.*?)[`'"]""",
    )

    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _XREF_SKIP_PARTS]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix not in frontend_extensions:
                continue
            if _should_skip_xref_file(fpath, project_root):
                continue

            # Skip backend directories
            try:
                rel_parts = fpath.relative_to(project_root).parts
            except ValueError:
                continue
            if any(p in ("backend", "server", "api", "Controllers", "Handlers") for p in rel_parts):
                continue

            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if len(content) > _MAX_FILE_SIZE:
                continue

            rel = fpath.relative_to(project_root).as_posix()

            # Build field value lookup for this file (used by BUG-1 variable
            # resolution AND BUG-3 base URL variable resolution in template literals)
            field_values: dict[str, str] = {}
            for fm in re_field_value.finditer(content):
                field_values[fm.group(1)] = fm.group(2)

            # BUG-2 fix: deduplicate by line number (not match position, since
            # Angular and Axios regexes can overlap at different char offsets
            # on the same source line, e.g. "this.http.post" matches both)
            seen_lines: set[int] = set()

            # Regex to detect leading ${this.xxx} or ${self.xxx} base URL variable
            re_base_var = re.compile(r'^\$\{(?:this|self)\.(\w+)\}')

            def _resolve_base_url_var(url_path: str) -> str:
                """Resolve leading ${this.xxx} in template literals to field value.

                If the field value is known, substitute it. Otherwise return as-is.
                """
                m_var = re_base_var.match(url_path)
                if not m_var:
                    return url_path
                var_name = m_var.group(1)
                field_val = field_values.get(var_name, "")
                if field_val:
                    # Replace ${this.xxx} with the resolved value
                    return field_val + url_path[m_var.end():]
                return url_path

            def _add_call(method: str, url_path: str, match_start: int) -> None:
                """Add a frontend call, deduplicating by line number."""
                line_no = content[:match_start].count("\n") + 1
                if line_no in seen_lines:
                    return
                # Resolve base URL variables in template literals
                url_path = _resolve_base_url_var(url_path)
                if _is_external_url(url_path):
                    return
                # Skip complex template literals with multiple interpolations
                if "${" in url_path and url_path.count("${") > 1:
                    return
                seen_lines.add(line_no)
                calls.append(_FrontendCall(method=method.upper(), path=url_path, file_path=rel, line=line_no))

            # Angular HttpClient (quoted URLs)
            for m in _RE_ANGULAR_HTTP.finditer(content):
                _add_call(m.group(1), m.group(2), m.start())

            # Axios (quoted URLs)
            for m in _RE_AXIOS.finditer(content):
                _add_call(m.group(1), m.group(2), m.start())

            # fetch() (quoted URLs)
            for m in _RE_FETCH.finditer(content):
                url_path = m.group(1)
                url_path = _resolve_base_url_var(url_path)
                if _is_external_url(url_path):
                    continue
                if "${" in url_path and url_path.count("${") > 1:
                    continue
                after = content[m.end():m.end() + 200]
                method_match = _RE_FETCH_METHOD.search(after)
                method = method_match.group(1).upper() if method_match else "GET"
                line_no = content[:m.start()].count("\n") + 1
                if line_no not in seen_lines:
                    seen_lines.add(line_no)
                    calls.append(_FrontendCall(method=method, path=url_path, file_path=rel, line=line_no))

            for m in re_angular_var.finditer(content):
                line_no = content[:m.start()].count("\n") + 1
                if line_no in seen_lines:
                    continue  # Already captured by quoted-URL regex
                method = m.group(1).upper()
                var_ref = m.group(2)  # e.g., "this.apiUrl"
                var_name = var_ref.split(".")[-1]  # e.g., "apiUrl"

                # Try to resolve the variable to a URL path
                resolved = field_values.get(var_name, "")
                if resolved:
                    # Field has a string value — use it as the path
                    _add_call(method, resolved, m.start())
                else:
                    # Can't resolve statically — skip (no false positive)
                    pass

    return calls


def _extract_backend_routes_dotnet(
    project_root: Path,
    scope: ScanScope | None,
) -> list["_BackendRoute"]:
    """Extract all API routes from .NET controller files."""
    routes: list[_BackendRoute] = []
    cs_extensions = (".cs",)

    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _XREF_SKIP_PARTS]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix not in cs_extensions:
                continue
            if "Controller" not in fname:
                continue

            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if len(content) > _MAX_FILE_SIZE:
                continue

            rel = fpath.relative_to(project_root).as_posix()

            # Extract class-level route prefix
            route_prefix = ""
            route_match = _RE_DOTNET_ROUTE.search(content)
            if route_match:
                route_prefix = route_match.group(1)

            # Replace [controller] with the controller name (minus "Controller" suffix)
            ctrl_match = _RE_DOTNET_CONTROLLER.search(content)
            ctrl_name = ""
            if ctrl_match:
                ctrl_name = ctrl_match.group(1).replace("Controller", "")
            if "[controller]" in route_prefix.lower():
                route_prefix = re.sub(r'\[controller\]', ctrl_name, route_prefix, flags=re.IGNORECASE)

            # Extract individual HTTP method attributes
            for m in _RE_DOTNET_HTTP_METHOD.finditer(content):
                attr = m.group(1)  # HttpGet, HttpPost, etc.
                action_path = m.group(2) or ""

                # Map attribute to HTTP method
                method_map = {
                    "httpget": "GET", "httppost": "POST", "httpput": "PUT",
                    "httpdelete": "DELETE", "httppatch": "PATCH",
                }
                method = method_map.get(attr.lower(), "GET")

                # Handle ~ route override (absolute path, ignore controller prefix)
                if action_path.startswith("~"):
                    full_path = action_path[1:]  # Strip ~ and use as absolute
                else:
                    # Combine prefix + action path
                    full_path = route_prefix.rstrip("/")
                    if action_path:
                        full_path = full_path + "/" + action_path.lstrip("/")
                if not full_path.startswith("/"):
                    full_path = "/" + full_path

                line_no = content[:m.start()].count("\n") + 1
                routes.append(_BackendRoute(method=method, path=full_path, file_path=rel, line=line_no))

    return routes


def _resolve_import_path(
    import_rel: str,
    mount_file: Path,
    project_root: Path,
    js_extensions: tuple[str, ...] = (".ts", ".js", ".mjs"),
) -> str | None:
    """Resolve a relative import path to a project-relative posix path.

    Tries ``import_rel`` with various extensions and ``/index`` fallbacks.
    Returns the project-relative posix path if the file exists, else ``None``.
    """
    base_dir = mount_file.parent
    # Strip leading ./ and normalize
    rel = import_rel.lstrip("./")
    candidate = base_dir / rel

    # Try as-is, then with extensions appended (NOT with_suffix, which
    # replaces multi-dot names like auth.routes → auth.ts instead of auth.routes.ts)
    candidates: list[Path] = [candidate]
    for ext in js_extensions:
        candidates.append(Path(str(candidate) + ext))
        candidates.append(candidate / ("index" + ext))

    for c in candidates:
        if c.is_file():
            try:
                return c.relative_to(project_root).as_posix()
            except ValueError:
                return c.as_posix()
    return None


def _extract_backend_routes_express(
    project_root: Path,
    scope: ScanScope | None,
) -> list["_BackendRoute"]:
    """Extract all API routes from Express/Node.js router files."""
    routes: list[_BackendRoute] = []
    js_extensions = (".ts", ".js", ".mjs")

    # BUG-4 fix: Resolve mount prefixes to ROUTE FILE paths, not mount file paths.
    # Parse app.use('/prefix', routerVar) AND import/require statements to build
    # a mapping from route_file_posix → mount_prefix.

    # Regex: app.use('/prefix', someRouter) — captures prefix AND variable name
    re_mount_full = re.compile(
        r"""app\s*\.\s*use\s*\(\s*['"`](.*?)['"`]\s*,\s*(\w+)""",
        re.IGNORECASE,
    )
    # Import patterns: import varName from './path' OR import { varName } from './path'
    re_import = re.compile(
        r"""import\s+(?:\{\s*)?(\w+)(?:\s*\})?\s+from\s+['"`](.*?)['"`]""",
    )
    # Require patterns: const varName = require('./path')
    re_require = re.compile(
        r"""(?:const|let|var)\s+(\w+)\s*=\s*require\s*\(\s*['"`](.*?)['"`]\s*\)""",
    )

    mount_prefixes: dict[str, str] = {}  # route_file_posix → prefix

    # First pass: parse mount files to resolve router → prefix mappings
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _XREF_SKIP_PARTS]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix not in js_extensions:
                continue
            if _should_skip_xref_file(fpath, project_root):
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            # Collect import/require mappings: variable_name → import_path
            imports: dict[str, str] = {}
            for m in re_import.finditer(content):
                imports[m.group(1)] = m.group(2)
            for m in re_require.finditer(content):
                imports[m.group(1)] = m.group(2)

            # Collect mount points: app.use('/prefix', routerVar)
            for m in re_mount_full.finditer(content):
                prefix = m.group(1).rstrip("/")
                router_var = m.group(2)

                # Resolve the router variable to a file path
                import_path = imports.get(router_var, "")
                if import_path:
                    resolved = _resolve_import_path(import_path, fpath, project_root, js_extensions)
                    if resolved:
                        mount_prefixes[resolved] = prefix

    # Second pass: collect route definitions and apply mount prefixes
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _XREF_SKIP_PARTS]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix not in js_extensions:
                continue
            if _should_skip_xref_file(fpath, project_root):
                continue

            # Only look at files likely to be route files
            name_lower = fname.lower()
            is_route_file = any(
                kw in name_lower
                for kw in ("route", "router", "controller", "handler", "api", "endpoint", "app", "server", "index")
            )
            if not is_route_file:
                continue

            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if len(content) > _MAX_FILE_SIZE:
                continue

            rel = fpath.relative_to(project_root).as_posix()

            # Look up mount prefix for this route file
            prefix = mount_prefixes.get(rel, "")

            for m in _RE_EXPRESS_ROUTE.finditer(content):
                method = m.group(1).upper()
                if method == "ALL":
                    method = "GET"  # Treat app.all() as GET for matching
                route_path = m.group(2)

                # Apply mount prefix if available
                if prefix:
                    full_path = prefix.rstrip("/") + "/" + route_path.lstrip("/")
                else:
                    full_path = route_path

                line_no = content[:m.start()].count("\n") + 1
                routes.append(_BackendRoute(method=method, path=full_path, file_path=rel, line=line_no))

    return routes


def _extract_backend_routes_python(
    project_root: Path,
    scope: ScanScope | None,
) -> list["_BackendRoute"]:
    """Extract all API routes from Flask/FastAPI/Django files."""
    routes: list[_BackendRoute] = []

    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _XREF_SKIP_PARTS]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix != ".py":
                continue
            if _should_skip_xref_file(fpath, project_root):
                continue

            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if len(content) > _MAX_FILE_SIZE:
                continue

            rel = fpath.relative_to(project_root).as_posix()

            # Flask @app.route / @blueprint.route
            for m in _RE_FLASK_ROUTE.finditer(content):
                path_str = m.group(1)
                methods_str = m.group(2)
                if methods_str:
                    # Parse methods=['GET', 'POST']
                    methods = re.findall(r"['\"](\w+)['\"]", methods_str)
                    for method in methods:
                        line_no = content[:m.start()].count("\n") + 1
                        routes.append(_BackendRoute(method=method.upper(), path=path_str, file_path=rel, line=line_no))
                else:
                    line_no = content[:m.start()].count("\n") + 1
                    routes.append(_BackendRoute(method="GET", path=path_str, file_path=rel, line=line_no))

            # FastAPI @app.get / @router.post
            for m in _RE_FASTAPI_ROUTE.finditer(content):
                method = m.group(1).upper()
                path_str = m.group(2)
                line_no = content[:m.start()].count("\n") + 1
                routes.append(_BackendRoute(method=method, path=path_str, file_path=rel, line=line_no))

            # Django path() — only in urls.py files
            if "urls" in fname.lower():
                for m in _RE_DJANGO_PATH.finditer(content):
                    path_str = m.group(1)
                    # Django doesn't have method in path(), default to ALL methods
                    line_no = content[:m.start()].count("\n") + 1
                    routes.append(_BackendRoute(method="ANY", path=path_str, file_path=rel, line=line_no))

    return routes


# Regex detecting unresolvable function-call URLs like ${this.func(...)}/path
_RE_FUNCTION_CALL_URL = re.compile(
    r'\$\{(?:this|self)\.\w+\([^)]*\)\}'
)


def _has_function_call_url(raw_path: str) -> bool:
    """Return True if *raw_path* contains an unresolvable function-call interpolation.

    Example patterns that match:
      ``${this.importUrl(tenderId, bidId)}/parse``
      ``${self.getEndpoint(id)}/action``

    These can't be resolved statically so violations for them are
    demoted to ``info`` severity.
    """
    return bool(_RE_FUNCTION_CALL_URL.search(raw_path))


def _check_endpoint_xref(
    frontend_calls: list["_FrontendCall"],
    backend_routes: list["_BackendRoute"],
) -> list[Violation]:
    """Cross-reference frontend HTTP calls against backend routes.

    Uses 3-level matching:
      1. Exact match (normalized path + method)
      2. Method-agnostic match (normalized path only) → XREF-002
      3. No match at all → XREF-001

    Violations for URLs containing unresolvable function calls
    (``${this.func(...)}/...``) are demoted to ``info`` severity
    since the scanner cannot resolve them statically.
    """
    violations: list[Violation] = []

    # Normalize backend routes into lookup structures
    backend_exact: set[tuple[str, str]] = set()  # (method, normalized_path)
    backend_paths: set[str] = set()  # normalized_path only

    for route in backend_routes:
        norm = _normalize_api_path(route.path)
        if not norm:
            continue
        backend_exact.add((route.method.upper(), norm))
        backend_paths.add(norm)
        # Django "ANY" matches all methods
        if route.method == "ANY":
            for m in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                backend_exact.add((m, norm))

    # Track already-reported paths to avoid duplicates
    reported: set[tuple[str, str, str]] = set()  # (method, normalized_path, file_path)

    for call in frontend_calls:
        norm = _normalize_api_path(call.path)
        if not norm:
            continue

        key = (call.method, norm, call.file_path)
        if key in reported:
            continue
        reported.add(key)

        # Detect function-call URLs — demote to info if present
        is_func_call = _has_function_call_url(call.path)

        # Level 1: exact match
        if (call.method, norm) in backend_exact:
            continue  # Perfect match

        # Level 2: method-agnostic match → method mismatch
        if norm in backend_paths:
            violations.append(Violation(
                check="XREF-002",
                message=(
                    f"Frontend calls {call.method} {call.path} but backend defines "
                    f"a different HTTP method for this path. Verify the correct "
                    f"method is used."
                ),
                file_path=call.file_path,
                line=call.line,
                severity="info" if is_func_call else "warning",
            ))
            continue

        # Level 3: no match at all → missing endpoint
        violations.append(Violation(
            check="XREF-001",
            message=(
                f"Frontend calls {call.method} {call.path} but no matching "
                f"backend endpoint was found. The backend controller/router "
                f"must define this endpoint."
                + (" (unresolvable function-call URL)" if is_func_call else "")
            ),
            file_path=call.file_path,
            line=call.line,
            severity="info" if is_func_call else "error",
        ))

        if len(violations) >= _MAX_VIOLATIONS:
            break

    return violations


def run_endpoint_xref_scan(
    project_root: Path,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Scan project for frontend-backend endpoint cross-reference mismatches.

    Auto-detects the backend framework (.NET, Express, Flask/FastAPI/Django)
    and extracts both frontend HTTP calls and backend route definitions.
    Cross-references them to find missing endpoints (XREF-001) and HTTP
    method mismatches (XREF-002).

    Returns an empty list if no frontend calls or no backend routes are found
    (project may not be full-stack).

    Returns:
        List of Violation objects (XREF-001, XREF-002).
    """
    # Extract frontend calls
    frontend_calls = _extract_frontend_http_calls(project_root, scope)
    if not frontend_calls:
        return []

    # Auto-detect backend framework and extract routes
    backend_routes: list[_BackendRoute] = []

    # Try .NET
    dotnet_routes = _extract_backend_routes_dotnet(project_root, scope)
    backend_routes.extend(dotnet_routes)

    # Try Express/Node.js
    express_routes = _extract_backend_routes_express(project_root, scope)
    backend_routes.extend(express_routes)

    # Try Python (Flask/FastAPI/Django)
    python_routes = _extract_backend_routes_python(project_root, scope)
    backend_routes.extend(python_routes)

    if not backend_routes:
        return []

    # Cross-reference
    violations = _check_endpoint_xref(frontend_calls, backend_routes)

    # Apply scope filter: only report violations for scoped files
    if scope and scope.changed_files:
        scope_posix: set[str] = set()
        for cf in scope.changed_files:
            try:
                scope_posix.add(cf.relative_to(project_root).as_posix())
            except ValueError:
                scope_posix.add(cf.as_posix())
        violations = [v for v in violations if v.file_path in scope_posix]

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )
    return violations


# ---------------------------------------------------------------------------
# API-004: Request field passthrough (write-side field dropped)
# ---------------------------------------------------------------------------


def _extract_csharp_class_properties(file_content: str, class_name: str) -> set[str]:
    """Extract public property names from a C# class definition.

    Finds the class by name and extracts properties defined with
    ``public Type PropertyName { get; set; }`` pattern.  Returns
    property names in their original casing.
    """
    # Find the class definition
    class_pattern = re.compile(
        rf'class\s+{re.escape(class_name)}\b[^{{]*\{{',
        re.DOTALL,
    )
    class_match = class_pattern.search(file_content)
    if not class_match:
        return set()

    # Extract balanced braces for the class body
    brace_start = class_match.end() - 1
    body = _find_balanced_braces(file_content, brace_start)
    if not body:
        return set()

    # Extract property names
    prop_pattern = re.compile(
        r'public\s+\w[\w<>\[\]?,\s]*\s+(\w+)\s*\{',
    )
    return {m.group(1) for m in prop_pattern.finditer(body)}


def _check_request_field_passthrough(
    contracts: list[SvcContract],
    project_root: Path,
    scope: ScanScope | None,
) -> list[Violation]:
    """API-004: Check that fields the frontend sends are accepted by the backend.

    For each SVC-xxx row with request_fields, extracts the backend Command/DTO
    class properties and verifies that every field the frontend sends has a
    matching property in the backend class.  Fields sent by the frontend but
    missing from the backend DTO are silently dropped.

    Only checks contracts with explicit request field schemas.
    """
    violations: list[Violation] = []

    # Collect contracts with request fields
    contracts_with_req = [c for c in contracts if c.request_fields]
    if not contracts_with_req:
        return violations

    # Find backend files (commands, DTOs, models)
    backend_patterns = [
        r'(?:commands?|handlers?|dtos?|requests?)',
        r'(?:controllers?|models?|viewmodels?)',
    ]
    backend_files: list[Path] = []
    for pat in backend_patterns:
        backend_files.extend(_find_files_by_pattern(project_root, pat))

    if not backend_files:
        return violations

    # Cache file contents
    file_contents: dict[Path, str] = {}
    for bf in backend_files:
        try:
            content = bf.read_text(encoding="utf-8", errors="replace")
            if len(content) <= _MAX_FILE_SIZE:
                file_contents[bf] = content
        except OSError:
            continue

    for contract in contracts_with_req:
        if len(violations) >= _MAX_VIOLATIONS:
            break

        # Extract class name from request_dto text: "CreateFooCommand { name: string }" → "CreateFooCommand"
        dto_text = contract.request_dto.strip()
        brace_idx = dto_text.find("{")
        if brace_idx > 0:
            class_name = dto_text[:brace_idx].strip()
        else:
            class_name = dto_text.strip()

        # Clean up class name — remove any backtick or quote artifacts
        class_name = re.sub(r'[`\'\"<>\[\]]', '', class_name).strip()
        if not class_name or not re.match(r'^[A-Za-z_]\w*$', class_name):
            continue

        # Search backend files for this class
        backend_props: set[str] = set()
        backend_ids: set[str] = set()
        for bf, content in file_contents.items():
            if class_name in content:
                props = _extract_csharp_class_properties(content, class_name)
                backend_props.update(props)
                # Also collect raw identifiers as fallback
                backend_ids.update(_extract_identifiers_from_file(content))

        # If we found explicit properties, use those; otherwise fall back to identifiers
        check_set = backend_props if backend_props else backend_ids
        if not check_set:
            continue

        for field_name in contract.request_fields:
            pascal_name = _to_pascal_case(field_name)
            # Accept either camelCase or PascalCase
            if field_name not in check_set and pascal_name not in check_set:
                violations.append(Violation(
                    check="API-004",
                    message=(
                        f"{contract.svc_id}: Frontend sends field '{field_name}' in "
                        f"{contract.http_method} request but backend class '{class_name}' "
                        f"has no matching property. The field is silently dropped. "
                        f"Add '{pascal_name}' property to '{class_name}' or remove "
                        f"the field from the frontend form."
                    ),
                    file_path="REQUIREMENTS.md",
                    line=0,
                    severity="error",
                ))

    return violations


# ---------------------------------------------------------------------------
# API-001..002: API completeness scan (v16 Phase 3.6)
# ---------------------------------------------------------------------------

# Patterns to find model/entity class definitions (reuse from entity coverage)
_MODEL_DEF_PY = re.compile(
    r"class\s+(\w+)\s*\([^)]*(?:Base|Model|DeclarativeBase|SQLModel)\b",
    re.MULTILINE,
)
_MODEL_DEF_TS = re.compile(
    r"@Entity\s*\(\s*\)\s*(?:export\s+)?class\s+(\w+)",
    re.MULTILINE,
)

# Patterns to find route/endpoint definitions per entity
_ROUTE_DEF_PY_GET = re.compile(r"@(?:router|app)\.get\s*\(\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_ROUTE_DEF_PY_POST = re.compile(r"@(?:router|app)\.post\s*\(\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_ROUTE_DEF_PY_PUT = re.compile(r"@(?:router|app)\.(?:put|patch)\s*\(\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_ROUTE_DEF_PY_DELETE = re.compile(r"@(?:router|app)\.delete\s*\(\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)

_ROUTE_DEF_TS_GET = re.compile(r"@Get\s*\(\s*['\"]?([^'\")\s]*)", re.MULTILINE)
_ROUTE_DEF_TS_POST = re.compile(r"@Post\s*\(\s*['\"]?([^'\")\s]*)", re.MULTILINE)
_ROUTE_DEF_TS_PUT = re.compile(r"@(?:Put|Patch)\s*\(\s*['\"]?([^'\")\s]*)", re.MULTILINE)
_ROUTE_DEF_TS_DELETE = re.compile(r"@Delete\s*\(\s*['\"]?([^'\")\s]*)", re.MULTILINE)

_PAGINATION_PATTERNS = re.compile(
    r"(?:page|limit|offset|pageSize|per_page|skip|take)\b",
    re.IGNORECASE,
)


def run_api_completeness_scan(
    project_root: Path,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Verify entities have CRUD endpoints with pagination.

    Checks:
    - API-001: Entity model exists but has fewer than 2 route methods
    - API-002: List endpoint exists but has no pagination parameters

    Returns violations sorted by severity, capped at ``_MAX_VIOLATIONS``.
    """
    violations: list[Violation] = []
    models: dict[str, str] = {}  # normalized_name -> file_path
    routes_by_entity: dict[str, set[str]] = {}  # normalized_name -> set of methods
    has_pagination: dict[str, bool] = {}  # entity -> bool

    source_files = _iter_source_files(project_root)
    if scope and scope.mode == "changed_only":
        if not scope.changed_files:
            return []
        scope_set = set(scope.changed_files)
        source_files = [f for f in source_files if f.resolve() in scope_set]

    for file_path in source_files:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if len(content) > _MAX_FILE_SIZE:
            continue

        rel_path = file_path.relative_to(project_root).as_posix()
        is_python = file_path.suffix == ".py"
        is_ts = file_path.suffix in (".ts", ".js")

        # Collect models
        if is_python:
            for m in _MODEL_DEF_PY.finditer(content):
                models[m.group(1).lower()] = rel_path
        elif is_ts:
            for m in _MODEL_DEF_TS.finditer(content):
                models[m.group(1).lower()] = rel_path

        # Collect routes — normalize entity name from URL path
        route_patterns: list[tuple[re.Pattern, str]] = []
        if is_python:
            route_patterns = [
                (_ROUTE_DEF_PY_GET, "GET"), (_ROUTE_DEF_PY_POST, "POST"),
                (_ROUTE_DEF_PY_PUT, "PUT"), (_ROUTE_DEF_PY_DELETE, "DELETE"),
            ]
        elif is_ts:
            route_patterns = [
                (_ROUTE_DEF_TS_GET, "GET"), (_ROUTE_DEF_TS_POST, "POST"),
                (_ROUTE_DEF_TS_PUT, "PUT"), (_ROUTE_DEF_TS_DELETE, "DELETE"),
            ]

        for pat, method in route_patterns:
            for m in pat.finditer(content):
                path = m.group(1).strip("/")
                if not path:
                    continue
                # Extract entity from first path segment
                segment = path.split("/")[0].lower().rstrip("s")
                routes_by_entity.setdefault(segment, set()).add(method)

                # Check for pagination on GET (list) endpoints
                if method == "GET" and ":" not in path and "{" not in path:
                    # This is likely a list endpoint — check for pagination nearby
                    context = content[max(0, m.start() - 200):m.end() + 500]
                    if _PAGINATION_PATTERNS.search(context):
                        has_pagination[segment] = True

    # API-001: Entity with fewer than 2 route methods
    for model_name, model_file in models.items():
        norm = model_name.rstrip("s")
        methods = routes_by_entity.get(norm, set()) | routes_by_entity.get(model_name, set())
        if len(methods) < 2:
            violations.append(Violation(
                check="API-001",
                message=(
                    f"Entity '{model_name}' has {len(methods)} route method(s) "
                    f"(expected at least GET + POST for basic CRUD)."
                ),
                file_path=model_file,
                line=0,
                severity="info",
            ))

    # API-002: List endpoint without pagination
    for entity, paginated in has_pagination.items():
        if not paginated:
            violations.append(Violation(
                check="API-002",
                message=f"List endpoint for '{entity}' has no pagination parameters.",
                file_path="(routes)",
                line=0,
                severity="info",
            ))

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.check, v.file_path)
    )
    return violations


# ---------------------------------------------------------------------------
# XSVC-001..002: Cross-service integration verification (v16 Phase 3.4)
# ---------------------------------------------------------------------------

# Patterns to detect HTTP client calls to other services
_HTTP_CLIENT_CALL_PY = re.compile(
    r"(?:await\s+)?(?:httpx|requests|aiohttp|self\.\w+_client)\."
    r"(?:get|post|put|patch|delete)\s*\(\s*"
    r"(?:f?['\"]([^'\"]+)['\"]|(\w+))",
    re.IGNORECASE,
)
_HTTP_CLIENT_CALL_TS = re.compile(
    r"(?:await\s+)?(?:this\.\w+|fetch|axios|HttpClient)\."
    r"(?:get|post|put|patch|delete|request)\s*[<(]\s*"
    r"(?:['\"`]([^'\"`]+)['\"`]|(\w+))",
    re.IGNORECASE,
)

# Patterns to detect event publishing
_EVENT_PUBLISH_PY = re.compile(
    r"(?:publish_event|publish|emit)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_EVENT_PUBLISH_TS = re.compile(
    r"\.(?:publish|emit|publishEvent)\s*\(\s*['\"`]([^'\"`]+)['\"`]",
    re.IGNORECASE,
)

# Patterns to detect event subscription
_EVENT_SUBSCRIBE_PY = re.compile(
    r"(?:subscribe|listen)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_EVENT_SUBSCRIBE_TS = re.compile(
    r"\.(?:subscribe|on)\s*\(\s*['\"`]([^'\"`]+)['\"`]",
    re.IGNORECASE,
)


def run_cross_service_scan(
    project_root: Path,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Verify cross-service HTTP calls and event pub/sub match.

    Checks:
    - XSVC-001: Event published but no service subscribes to it
    - XSVC-002: Event subscribed but no service publishes it

    Returns violations sorted by severity.
    """
    violations: list[Violation] = []
    publishers: dict[str, str] = {}   # event_name -> file_path
    subscribers: dict[str, str] = {}  # event_name -> file_path

    source_files = _iter_source_files(project_root)
    if scope and scope.mode == "changed_only":
        if not scope.changed_files:
            return []
        scope_set = set(scope.changed_files)
        source_files = [f for f in source_files if f.resolve() in scope_set]

    for file_path in source_files:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if len(content) > _MAX_FILE_SIZE:
            continue

        rel_path = file_path.relative_to(project_root).as_posix()
        is_python = file_path.suffix == ".py"
        is_ts = file_path.suffix in (".ts", ".js")

        # Extract event publications
        pub_pat = _EVENT_PUBLISH_PY if is_python else (_EVENT_PUBLISH_TS if is_ts else None)
        if pub_pat:
            for m in pub_pat.finditer(content):
                event_name = m.group(1).lower()
                publishers[event_name] = rel_path

        # Extract event subscriptions
        sub_pat = _EVENT_SUBSCRIBE_PY if is_python else (_EVENT_SUBSCRIBE_TS if is_ts else None)
        if sub_pat:
            for m in sub_pat.finditer(content):
                event_name = m.group(1).lower()
                subscribers[event_name] = rel_path

    # XSVC-001: Published but no subscriber
    for event_name, pub_file in publishers.items():
        if event_name not in subscribers:
            violations.append(Violation(
                check="XSVC-001",
                message=f"Event '{event_name}' is published but no service subscribes to it.",
                file_path=pub_file,
                line=0,
                severity="info",
            ))

    # XSVC-002: Subscribed but no publisher
    for event_name, sub_file in subscribers.items():
        if event_name not in publishers:
            violations.append(Violation(
                check="XSVC-002",
                message=f"Event '{event_name}' is subscribed but no service publishes it.",
                file_path=sub_file,
                line=0,
                severity="warning",
            ))

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.check, v.file_path)
    )
    return violations


# ---------------------------------------------------------------------------
# PLACEHOLDER-001: Placeholder / stub comment scanner (v16 quality fix)
# ---------------------------------------------------------------------------

# Patterns that indicate a placeholder implementation disguised as code.
# These detect the exact anti-pattern found in v16: builder acknowledges
# what the code *should* do but writes a comment instead of actual logic.
_PLACEHOLDER_PATTERNS = re.compile(
    r"(?:"
    r"[Ii]n production[,\s].*(?:would|should|will|could)\b|"
    r"\b(?:would|should|could) be (?:compared|calculated|validated|implemented|processed|handled)|"
    r"\bTODO:\s*implement|"
    r"\bFIXME:\s*implement|"
    r"\bplaceholder\s+(?:implementation|logic|handler|code)|"
    r"\bstub\s+(?:implementation|handler|logic|code)|"
    r"\bnot yet implemented|"
    r"\bto be implemented|"
    r"\bmock\s+(?:implementation|response|data)\s*[-—]|"
    r"\btemporary\s+(?:implementation|stub|placeholder)"
    r")",
    re.IGNORECASE,
)

# Files that should be excluded from placeholder scanning
_PLACEHOLDER_SKIP_SUFFIXES = frozenset({".md", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".lock"})
_PLACEHOLDER_SKIP_PREFIXES = ("test_", "spec_", "test.", "spec.")
_PLACEHOLDER_SKIP_CONTAINS = (".test.", ".spec.", "__test__", "__spec__")


def run_placeholder_scan(
    project_root: Path,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Detect placeholder comments that indicate stub implementations.

    Scans all source files for comments like "In production, amounts would
    be compared" or "TODO: implement" which indicate the builder acknowledged
    a requirement but deferred implementation.

    Returns violations sorted by severity, capped at ``_MAX_VIOLATIONS``.
    """
    violations: list[Violation] = []
    source_files = _iter_source_files(project_root)
    if scope and scope.mode == "changed_only":
        if not scope.changed_files:
            return []
        scope_set = set(scope.changed_files)
        source_files = [f for f in source_files if f.resolve() in scope_set]

    for file_path in source_files:
        if len(violations) >= _MAX_VIOLATIONS:
            break

        # Skip non-source files
        if file_path.suffix in _PLACEHOLDER_SKIP_SUFFIXES:
            continue

        # Skip test files
        name_lower = file_path.name.lower()
        if any(name_lower.startswith(p) for p in _PLACEHOLDER_SKIP_PREFIXES):
            continue
        if any(s in name_lower for s in _PLACEHOLDER_SKIP_CONTAINS):
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if len(content) > _MAX_FILE_SIZE:
            continue

        rel_path = file_path.relative_to(project_root).as_posix()

        for line_no, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            # Only match in comment lines to avoid false positives on string literals
            # that happen to mention "production" in config or env checks.
            is_comment = stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("*")

            # M22 fix: also detect inline block comments /* ... */
            if not is_comment and "/*" in stripped:
                # Extract all block comment content from the line
                for bc_match in re.finditer(r"/\*(.+?)\*/", stripped):
                    comment_text = bc_match.group(1).strip()
                    if _PLACEHOLDER_PATTERNS.search(comment_text):
                        violations.append(Violation(
                            check="PLACEHOLDER-001",
                            message=(
                                f"Placeholder block comment detected: '/* {comment_text[:100]} */'. "
                                f"This indicates deferred implementation — "
                                f"the actual logic must be written, not described in a comment."
                            ),
                            file_path=rel_path,
                            line=line_no,
                            severity="error",
                        ))
                continue

            if not is_comment:
                continue
            if _PLACEHOLDER_PATTERNS.search(stripped):
                violations.append(Violation(
                    check="PLACEHOLDER-001",
                    message=(
                        f"Placeholder comment detected: '{stripped[:120]}'. "
                        f"This indicates deferred implementation — "
                        f"the actual logic must be written, not described in a comment."
                    ),
                    file_path=rel_path,
                    line=line_no,
                    severity="error",
                ))

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )
    return violations


# ---------------------------------------------------------------------------
# UNUSED-PARAM-001: Unused parameter detector (v16 quality fix)
# ---------------------------------------------------------------------------

# Regex to extract function signatures with parameters
_FUNC_SIG_PY = re.compile(
    r"^(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)\s*(?:->.*)?:",
    re.MULTILINE,
)
_FUNC_SIG_TS = re.compile(
    r"(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*(?::\s*\S[^{]*)?\s*\{",
    re.MULTILINE,
)

# Control-flow keywords and built-in calls that should not be treated as
# function definitions.
_TS_NON_FUNCTION_NAMES = frozenset({
    # Control-flow keywords
    "if", "else", "for", "while", "switch", "catch", "return", "throw",
    "new", "typeof", "instanceof", "await", "yield", "do", "try",
    "finally", "delete", "void", "in", "of",
    # Built-in constructors / global functions
    "Number", "String", "Boolean", "Object", "Array", "Date", "RegExp",
    "Error", "TypeError", "RangeError", "Promise", "Map", "Set", "Symbol",
    "parseInt", "parseFloat", "JSON", "Math", "require", "import",
    # Decorators / Angular / CSS-in-JS
    "Component", "Injectable", "NgModule", "Directive", "Pipe",
    "media", "keyframes", "supports",
})

# Parameters that are commonly unused by convention (framework injected)
_IGNORED_PARAMS = frozenset({
    "self", "cls", "req", "request", "res", "response", "next",
    "ctx", "context", "args", "kwargs", "_",
})

# Contexts where a parameter appearing only counts as "log-only"
_LOG_CONTEXT_PATTERNS = re.compile(
    r"(?:"
    r"logger\.\w+\(|"
    r"logging\.\w+\(|"
    r"console\.\w+\(|"
    r"this\.logger\.\w+\(|"
    r"self\.logger\.\w+\(|"
    r"print\(|"
    r"log\.\w+\(|"
    r"['\"`].*\$\{|"
    r"f['\"].*\{"
    r")"
)


def _split_params_respecting_generics(params_str: str) -> list[str]:
    """Split parameters by comma while respecting angle-bracket nesting.

    e.g. ``'a: Map<string, number>, b: string'``
    -> ``['a: Map<string, number>', 'b: string']``
    """
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in params_str:
        if ch == "<":
            depth += 1
            current.append(ch)
        elif ch == ">":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def _extract_param_names(params_str: str, is_python: bool) -> list[str]:
    """Extract parameter names from a function signature string."""
    params: list[str] = []
    # For TypeScript, split respecting generic angle brackets so that
    # e.g. Record<string, any> is not broken at the inner comma.
    raw_parts = (
        params_str.split(",")
        if is_python
        else _split_params_respecting_generics(params_str)
    )
    for part in raw_parts:
        part = part.strip()
        if not part:
            continue
        if is_python:
            # Python: name: type = default, or *args, **kwargs
            if part.startswith("*"):
                continue
            name = part.split(":")[0].split("=")[0].strip()
        else:
            # TypeScript: name: type = default, or ...rest
            if part.startswith("..."):
                continue
            # Remove decorators like @Body(), @Param() etc
            part = re.sub(r"@\w+\([^)]*\)\s*", "", part)
            name = part.split(":")[0].split("=")[0].strip()
            # Remove access modifiers
            for mod in ("public", "private", "protected", "readonly"):
                if name.startswith(mod + " "):
                    name = name[len(mod) + 1:]
        name = name.strip()
        if name and name not in _IGNORED_PARAMS:
            params.append(name)
    return params


def _is_param_used_in_logic(param_name: str, body_lines: list[str]) -> bool:
    """Check if a parameter is used in business logic (not just logging)."""
    pat = re.compile(r"\b" + re.escape(param_name) + r"\b")

    used_in_logic = False
    for line in body_lines:
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        if not pat.search(stripped):
            continue
        if _LOG_CONTEXT_PATTERNS.search(stripped):
            non_log = re.sub(r"(?:logger|logging|console|this\.logger|self\.logger|log)\.\w+\(.*\)", "", stripped)
            non_log = re.sub(r"print\(.*\)", "", non_log)
            if pat.search(non_log):
                used_in_logic = True
        else:
            used_in_logic = True

    return used_in_logic


def run_unused_param_scan(
    project_root: Path,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Detect function parameters that are accepted but never used in business logic.

    Catches the v16 anti-pattern where ``tolerancePercent`` was accepted by
    the match function but only appeared in a log message, never in any
    comparison or calculation.

    Returns violations sorted by severity, capped at ``_MAX_VIOLATIONS``.
    """
    violations: list[Violation] = []
    source_files = _iter_source_files(project_root)
    if scope and scope.mode == "changed_only":
        if not scope.changed_files:
            return []
        scope_set = set(scope.changed_files)
        source_files = [f for f in source_files if f.resolve() in scope_set]

    for file_path in source_files:
        if len(violations) >= _MAX_VIOLATIONS:
            break

        # Skip test files
        name_lower = file_path.name.lower()
        if any(name_lower.startswith(p) for p in _PLACEHOLDER_SKIP_PREFIXES):
            continue
        if any(s in name_lower for s in _PLACEHOLDER_SKIP_CONTAINS):
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if len(content) > _MAX_FILE_SIZE:
            continue

        rel_path = file_path.relative_to(project_root).as_posix()
        is_python = file_path.suffix == ".py"
        is_ts = file_path.suffix in (".ts", ".js")
        if not is_python and not is_ts:
            continue

        sig_pattern = _FUNC_SIG_PY if is_python else _FUNC_SIG_TS

        for match in sig_pattern.finditer(content):
            func_name = match.group(1)
            if not is_python:
                # Skip control-flow keywords and built-in calls
                if func_name in _TS_NON_FUNCTION_NAMES:
                    continue
                # Skip method calls (preceded by '.') and decorators ('@')
                pos = match.start()
                if pos > 0 and content[pos - 1] in ".@":
                    continue
            params_str = match.group(2)
            param_names = _extract_param_names(params_str, is_python)
            if not param_names:
                continue

            body_lines = _extract_function_body_lines(content, match.start(), is_python)
            real_lines = [l for l in body_lines if l.strip() and not l.strip().startswith(("#", "//"))]
            if len(real_lines) < 3:
                continue

            for param_name in param_names:
                if not _is_param_used_in_logic(param_name, body_lines):
                    line_no = content[:match.start()].count("\n") + 1
                    violations.append(Violation(
                        check="UNUSED-PARAM-001",
                        message=(
                            f"Parameter '{param_name}' in function '{func_name}()' is accepted "
                            f"but never used in business logic (only appears in logging). "
                            f"If the parameter is needed, use it in the function's core logic."
                        ),
                        file_path=rel_path,
                        line=line_no,
                        severity="warning",
                    ))

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )
    return violations


# ---------------------------------------------------------------------------
# SM-001: State machine completeness scan (v16 quality check)
# ---------------------------------------------------------------------------

# Patterns to locate transition maps in source code
_SM_TRANSITION_MAP_PY = re.compile(
    r"(?:VALID_TRANSITIONS|STATUS_TRANSITIONS|_TRANSITIONS)\s*[=:][^{;\n]*\{",
    re.IGNORECASE,
)
_SM_TRANSITION_MAP_TS = re.compile(
    r"(?:VALID_TRANSITIONS|validTransitions|transitions\s*=|readonly\s+transitions|const\s+TRANSITIONS\s*:)"
    r"[^{;]*\{",
    re.IGNORECASE,
)

# States that indicate "backward" / retry flow (used for severity heuristic)
_BACKWARD_STATE_KEYWORDS = frozenset({
    "draft", "created", "initiated", "received", "new", "pending",
    "open", "initial", "start", "queued",
})


def _parse_transition_map_from_content(content: str, start_pos: int) -> dict[str, list[str]]:
    """Extract a {from_state: [to_states]} dict starting from *start_pos*.

    Handles both Python-style dicts (``{"draft": ["submitted", "void"]}``)
    and TypeScript-style objects (``{ draft: ['submitted', 'void'] }``).
    Terminates at the matching closing brace.
    """
    # Find the opening brace
    brace_idx = content.find("{", start_pos)
    if brace_idx == -1:
        return {}

    # Extract the balanced brace block
    depth = 0
    end_idx = brace_idx
    for i in range(brace_idx, min(len(content), brace_idx + 5000)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                end_idx = i + 1
                break
    else:
        return {}

    block = content[brace_idx:end_idx]

    # Parse entries: key → [values]
    # Matches: "draft": ["submitted", "void"]  or  draft: ['submitted', 'void']
    entry_pattern = re.compile(
        r"""["\']?(\w+)["\']?\s*:\s*\[([^\]]*)\]""",
        re.DOTALL,
    )
    result: dict[str, list[str]] = {}
    for m in entry_pattern.finditer(block):
        from_state = m.group(1).lower().strip()
        to_states_raw = m.group(2)
        to_states = [
            s.strip().strip("\"'").lower()
            for s in to_states_raw.split(",")
            if s.strip().strip("\"'")
        ]
        if to_states:
            result[from_state] = to_states
    return result


def _is_backward_state(state: str) -> bool:
    """Return True if *state* looks like a lifecycle-initial/backward state."""
    state_lower = state.lower()
    return any(kw in state_lower for kw in _BACKWARD_STATE_KEYWORDS)


def _pascal_to_words_sm(name: str) -> list[str]:
    """Split PascalCase into lowercase words for SM matching.

    E.g. "IntercompanyTransaction" -> ["intercompany", "transaction"]
         "JournalEntry" -> ["journal", "entry"]
    """
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    return spaced.lower().split()


# Words too generic to use for last-word file matching
_GENERIC_LAST_WORDS = frozenset({
    "entry", "item", "record", "data", "type", "info", "detail",
    "details", "status", "value", "line", "note",
})


def _match_entity_to_file(entity: str, file_path: Path, content: str) -> bool:
    """Check if *file_path* or its content is likely related to *entity*.

    Uses multiple matching strategies to handle diverse naming conventions:
    - PascalCase -> snake_case (JournalEntry -> journal_entry)
    - PascalCase -> kebab-case (JournalEntry -> journal-entry)
    - PascalCase -> lowercase  (JournalEntry -> journalentry)
    - Last-word matching (IntercompanyTransaction -> transaction)
    - Abbreviation matching (IntercompanyTransaction -> ic_transaction)
    - class/interface declarations in file content
    """
    entity_lower = re.sub(r"[_\-\s]", "", entity.lower())
    # --- Strategy 1: stripped comparison (original logic) ---
    file_stem = re.sub(r"[_\-\s.]", "", file_path.stem.lower())
    if entity_lower in file_stem or file_stem in entity_lower:
        return True

    # --- Strategy 2: path variants (snake_case, kebab-case, lowercase) ---
    words = _pascal_to_words_sm(entity)
    rel_lower = file_path.as_posix().lower()
    if words:
        snake = "_".join(words)       # journal_entry
        kebab = "-".join(words)       # journal-entry
        joined = "".join(words)       # journalentry
        if snake in rel_lower or kebab in rel_lower or joined in rel_lower:
            return True

    # --- Strategy 3: last-word matching for compound entities ---
    # "IntercompanyTransaction" -> try "transaction" in file stem
    # Skip overly generic last words
    if len(words) >= 2:
        last_word = words[-1]
        if last_word not in _GENERIC_LAST_WORDS and last_word in file_stem:
            return True
        # Also try the first word if non-generic
        first_word = words[0]
        if first_word not in _GENERIC_LAST_WORDS and first_word in file_stem:
            return True

    # --- Strategy 4: abbreviation matching ---
    # "IntercompanyTransaction" -> "ic_transaction", "ic-transaction"
    if len(words) >= 2:
        initials = "".join(w[0] for w in words[:-1])  # "ic"
        abbrev_snake = f"{initials}_{words[-1]}"       # "ic_transaction"
        abbrev_kebab = f"{initials}-{words[-1]}"       # "ic-transaction"
        if abbrev_snake in rel_lower or abbrev_kebab in rel_lower:
            return True

    # --- Strategy 5: class/interface name containing the entity ---
    entity_pattern = re.compile(
        r"(?:class|interface|enum)\s+" + re.escape(entity),
        re.IGNORECASE,
    )
    if entity_pattern.search(content):
        return True

    return False


def _match_entity_to_transition_map_by_proximity(
    entity: str,
    content: str,
    tmap_start: int,
    proximity_lines: int = 50,
) -> bool:
    """Check if *entity* name appears near a transition map in file content.

    Searches up to *proximity_lines* lines above the transition map position
    for the entity name (in various forms).
    """
    words = _pascal_to_words_sm(entity)
    if not words:
        return False

    # Build patterns to search for near the transition map
    patterns: list[str] = [
        re.sub(r"[_\-\s]", "", entity.lower()),  # journalentry
        "_".join(words),                           # journal_entry
        "-".join(words),                           # journal-entry
        " ".join(words),                           # journal entry
    ]
    if len(words) >= 2:
        last = words[-1]
        if last not in _GENERIC_LAST_WORDS:
            patterns.append(last)                  # transaction
        initials = "".join(w[0] for w in words[:-1])
        patterns.append(f"{initials}_{words[-1]}")  # ic_transaction

    # Walk backwards from tmap_start counting newlines
    pos = tmap_start
    newline_count = 0
    while pos > 0 and newline_count < proximity_lines:
        pos -= 1
        if content[pos] == "\n":
            newline_count += 1
    context_window = content[pos:tmap_start].lower()

    for pat in patterns:
        if pat and len(pat) >= 3 and pat in context_window:
            return True

    return False


def run_state_machine_completeness_scan(
    project_root: Path,
    parsed_state_machines: list[dict] | None = None,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Compare PRD-defined state machine transitions against code implementations.

    For each state machine in *parsed_state_machines*, locates transition maps
    in the source code and reports missing transitions.

    Missing transitions whose ``to_state`` looks like a backward/initial state
    (e.g. "draft", "created") are flagged as ``"warning"`` severity; other
    missing transitions are flagged as ``"info"``.

    Returns violations sorted by severity, capped at ``_MAX_VIOLATIONS``.
    """
    if not parsed_state_machines:
        return []

    violations: list[Violation] = []
    source_files = _iter_source_files(project_root)
    if scope and scope.mode == "changed_only":
        if not scope.changed_files:
            return []
        scope_set = set(scope.changed_files)
        source_files = [f for f in source_files if f.resolve() in scope_set]

    # Build index: file_path → (content, parsed transition map, match start pos)
    file_transition_maps: list[tuple[Path, str, dict[str, list[str]], int]] = []

    for file_path in source_files:
        is_python = file_path.suffix == ".py"
        is_ts = file_path.suffix in (".ts", ".js")
        if not is_python and not is_ts:
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if len(content) > _MAX_FILE_SIZE:
            continue

        pattern = _SM_TRANSITION_MAP_PY if is_python else _SM_TRANSITION_MAP_TS
        for match in pattern.finditer(content):
            tmap = _parse_transition_map_from_content(content, match.start())
            if tmap:
                file_transition_maps.append((file_path, content, tmap, match.start()))

    # For each parsed state machine, find matching code and compare
    for sm in parsed_state_machines:
        entity = sm.get("entity", "")
        prd_transitions = sm.get("transitions", [])
        if not prd_transitions:
            continue

        # Build PRD transition set: {(from_state, to_state)}
        prd_set: set[tuple[str, str]] = set()
        for t in prd_transitions:
            fr = t.get("from_state", "").lower().strip()
            to = t.get("to_state", "").lower().strip()
            if fr and to:
                prd_set.add((fr, to))

        if not prd_set:
            continue

        # Find best matching file(s) for this entity
        matched_maps: list[tuple[Path, dict[str, list[str]]]] = []
        for file_path, content, tmap, tmap_start in file_transition_maps:
            if _match_entity_to_file(entity, file_path, content):
                matched_maps.append((file_path, tmap))
            elif _match_entity_to_transition_map_by_proximity(
                entity, content, tmap_start
            ):
                matched_maps.append((file_path, tmap))

        if not matched_maps:
            # No code transition map found for this entity — report all as missing
            for fr, to in sorted(prd_set):
                if len(violations) >= _MAX_VIOLATIONS:
                    break
                sev = "warning" if _is_backward_state(to) else "info"
                violations.append(Violation(
                    check="SM-001",
                    message=(
                        f"State machine '{entity}': transition "
                        f"'{fr}' -> '{to}' defined in PRD but no "
                        f"transition map found in code."
                    ),
                    file_path="(no matching file)",
                    line=0,
                    severity=sev,
                ))
            continue

        # Compare against each matched map
        for file_path, tmap in matched_maps:
            if len(violations) >= _MAX_VIOLATIONS:
                break

            # Build code transition set
            code_set: set[tuple[str, str]] = set()
            for from_st, to_list in tmap.items():
                for to_st in to_list:
                    code_set.add((from_st, to_st))

            # Missing transitions (in PRD but not in code)
            missing = prd_set - code_set
            rel_path = file_path.relative_to(project_root).as_posix()

            for fr, to in sorted(missing):
                if len(violations) >= _MAX_VIOLATIONS:
                    break
                sev = "warning" if _is_backward_state(to) else "info"
                violations.append(Violation(
                    check="SM-001",
                    message=(
                        f"State machine '{entity}': transition "
                        f"'{fr}' -> '{to}' defined in PRD but missing "
                        f"from code transition map."
                    ),
                    file_path=rel_path,
                    line=0,
                    severity=sev,
                ))

            # Extra transitions (in code but not in PRD) — info only
            extra = code_set - prd_set
            for fr, to in sorted(extra):
                if len(violations) >= _MAX_VIOLATIONS:
                    break
                violations.append(Violation(
                    check="SM-001",
                    message=(
                        f"State machine '{entity}': transition "
                        f"'{fr}' -> '{to}' found in code but not "
                        f"defined in PRD (may be intentional)."
                    ),
                    file_path=rel_path,
                    line=0,
                    severity="info",
                ))

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )
    return violations


# ---------------------------------------------------------------------------
# Business rule verification (RULE-001)
# ---------------------------------------------------------------------------

# Map operation names to regex patterns for detecting them in code
_OPERATION_PATTERNS: dict[str, re.Pattern[str]] = {
    "multiplication": re.compile(r"\*|multiply|times", re.IGNORECASE),
    "comparison": re.compile(
        r"[<>]=?|Math\.abs|abs\(|tolerance|threshold|variance",
        re.IGNORECASE,
    ),
    "http_call": re.compile(
        r"fetch\(|axios\.|httpx\.|\.post\(|\.get\(|\.put\(|\.patch\(",
        re.IGNORECASE,
    ),
    "db_write": re.compile(
        r"\.save\(|\.create\(|\.insert\(|\.execute\(|\.update\(",
        re.IGNORECASE,
    ),
    "subtraction": re.compile(r"\s-\s|subtract|minus", re.IGNORECASE),
    "division": re.compile(r"/[^/]|divide|ratio", re.IGNORECASE),
    "absolute_value": re.compile(r"Math\.abs|abs\(|fabs\(", re.IGNORECASE),
}

# Map rule_type -> function-name patterns to search for
_RULE_TYPE_FUNC_PATTERNS: dict[str, re.Pattern[str]] = {
    "validation": re.compile(
        r"(?:def|async\s+)?(?:match|validate|verify|check)\s*\(",
        re.IGNORECASE,
    ),
    "computation": re.compile(
        r"(?:def|async\s+)?(?:calculate|compute|depreciate|revalue)\s*\(",
        re.IGNORECASE,
    ),
    "integration": re.compile(
        r"fetch\(|axios\.|httpx\.|\.post\(|\.get\(|\.put\(|\.patch\(",
        re.IGNORECASE,
    ),
    "guard": re.compile(
        r"transition|guard|can[A-Z]\w*\(|allow|permit|fsm|state_machine",
        re.IGNORECASE,
    ),
}

# Anti-pattern detection regexes
_ANTI_PATTERN_MAP: dict[str, re.Pattern[str]] = {
    "field existence": re.compile(r"^\s*if\s*\(\s*!?\w+\.\w+\s*\)"),
    "string existence": re.compile(r"^\s*if\s*\(\s*!?\w+\.\w+\s*\)"),
    "hardcoded": re.compile(
        r"return\s+(?:0|1|true|false|null|None|'[^']*'|\"[^\"]*\")\s*[;\n]"
    ),
    "log the event": _LOG_ONLY_PATTERNS,
}

# Python function definition pattern (for body extraction)
_RE_PY_FUNC_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)

# TypeScript / JS function/method patterns (for body extraction)
_RE_TS_FUNC_DEF = re.compile(
    r"(?:async\s+)?(?:(\w+)\s*\(|(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*(?:=>|:))",
    re.MULTILINE,
)


def _normalize_entity_for_path(entity: str) -> list[str]:
    """Convert an entity name to multiple path-friendly variants.

    E.g. "PurchaseInvoice" -> ["purchase-invoice", "purchase_invoice",
    "purchaseinvoice"]
    """
    # Insert separator before uppercase letters: PurchaseInvoice -> Purchase Invoice
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", entity)
    parts = spaced.lower().split()
    return [
        "-".join(parts),   # purchase-invoice
        "_".join(parts),   # purchase_invoice
        "".join(parts),    # purchaseinvoice
    ]


def _find_candidate_files(
    entity: str,
    source_files: list[Path],
    project_root: Path,
    service: str = "",
) -> list[Path]:
    """Find source files that are likely related to *entity*.

    Uses three strategies:
    1. Entity name variants in file path (e.g., "purchase-invoice" in path)
    2. Service directory matching (e.g., service="asset" matches services/assets/)
    3. First-word partial matching (e.g., "reconciliation" from "ReconciliationSession")
    """
    variants = _normalize_entity_for_path(entity)
    candidates: list[Path] = []
    seen: set[Path] = set()

    # Strategy 1: exact entity name variant matching (original behavior)
    for file_path in source_files:
        rel = file_path.relative_to(project_root).as_posix().lower()
        if any(v in rel for v in variants):
            if file_path not in seen:
                candidates.append(file_path)
                seen.add(file_path)

    # Strategy 2: service directory matching
    if service:
        svc_lower = service.lower().rstrip("_service").rstrip("-service")
        for file_path in source_files:
            if file_path in seen:
                continue
            rel = file_path.relative_to(project_root).as_posix().lower()
            # Match service directory: services/assets/, services/banking/, etc.
            parts = rel.split("/")
            if any(svc_lower in p for p in parts[:3]):
                candidates.append(file_path)
                seen.add(file_path)

    # Strategy 3: first-word partial matching for multi-word entities
    if not candidates:
        spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", entity)
        words = spaced.lower().split()
        if len(words) >= 2:
            first_word = words[0]
            if len(first_word) >= 5:  # Avoid matching short common words
                for file_path in source_files:
                    if file_path in seen:
                        continue
                    fname = file_path.name.lower()
                    if first_word in fname:
                        candidates.append(file_path)
                        seen.add(file_path)

    return candidates


def _find_implementing_functions(
    content: str,
    rule_type: str,
    is_python: bool,
) -> list[tuple[str, list[str]]]:
    """Find functions in *content* that likely implement a business rule.

    Returns a list of (function_name, body_lines) tuples.
    """
    func_pattern = _RULE_TYPE_FUNC_PATTERNS.get(rule_type)
    if func_pattern is None:
        return []

    results: list[tuple[str, list[str]]] = []

    # For "integration" rules, search for HTTP calls inside function bodies
    # rather than matching function names (avoids false positives like
    # bare ``fetch(`` calls being classified as function definitions).
    if rule_type == "integration":
        func_re = _RE_PY_FUNC_DEF if is_python else _RE_TS_FUNC_DEF
        for match in func_re.finditer(content):
            if is_python:
                func_name = match.group(1)
            else:
                func_name = match.group(1) or match.group(2)
            if not func_name:
                continue
            body = _extract_function_body_lines(content, match.start(), is_python)
            body_text = "\n".join(body)
            if func_pattern.search(body_text):
                results.append((func_name, body))
        return results

    if is_python:
        for match in _RE_PY_FUNC_DEF.finditer(content):
            func_name = match.group(1)
            # Check if this function name matches the rule type pattern
            if func_pattern.search(f"{func_name}("):
                body = _extract_function_body_lines(content, match.start(), True)
                results.append((func_name, body))
    else:
        # TypeScript/JS: find method/function definitions
        for match in _RE_TS_FUNC_DEF.finditer(content):
            func_name = match.group(1) or match.group(2)
            if func_name and func_pattern.search(f"{func_name}("):
                body = _extract_function_body_lines(content, match.start(), False)
                results.append((func_name, body))

    return results


def run_business_rule_verification(
    project_root: Path,
    business_rules: list[dict] | None = None,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Verify that business rules from the PRD have corresponding implementations.

    For each business rule, locates candidate files by entity name, searches
    for implementing functions, and checks that required operations are present
    and anti-patterns are absent.

    Returns violations sorted by severity, capped at ``_MAX_VIOLATIONS``.
    """
    if not business_rules:
        return []

    violations: list[Violation] = []
    source_files = _iter_source_files(project_root)

    if scope and scope.mode == "changed_only":
        if not scope.changed_files:
            return []
        scope_set = set(scope.changed_files)
        source_files = [f for f in source_files if f.resolve() in scope_set]

    for rule in business_rules:
        if len(violations) >= _MAX_VIOLATIONS:
            break

        rule_id = rule.get("id", "UNKNOWN")
        entity = rule.get("entity", "")
        rule_type = rule.get("rule_type", "validation")
        required_ops: list[str] = rule.get("required_operations", [])
        anti_patterns: list[str] = rule.get("anti_patterns", [])

        if not entity:
            continue

        # Find candidate files for this entity
        service = rule.get("service", "")
        candidates = _find_candidate_files(entity, source_files, project_root, service=service)

        if not candidates:
            violations.append(Violation(
                check="RULE-001",
                message=(
                    f"No implementation found for {rule_id}: "
                    f"no source files match entity '{entity}'."
                ),
                file_path="(no matching file)",
                line=0,
                severity="critical",
            ))
            continue

        # Search candidate files for implementing functions
        rule_implemented = False

        for file_path in candidates:
            if len(violations) >= _MAX_VIOLATIONS:
                break

            # Skip test files — they naturally contain mocks and stubs
            fname_lower = file_path.name.lower()
            if any(pat in fname_lower for pat in (
                ".spec.", ".test.", "_test.", ".e2e-spec.", "_spec.",
                "test_", "conftest", "__tests__",
            )):
                continue
            # Skip contract/client wrapper files — HTTP wrappers, not business logic
            if any(pat in fname_lower for pat in (
                "_client.", "client.",
            )):
                continue
            # Also skip test/contract/infra directories
            rel_str = file_path.relative_to(project_root).as_posix().lower()
            if any(d in rel_str for d in (
                "/test/", "/tests/", "/__tests__/", "/e2e/",
                "/contracts/", "/generated/", "/stubs/",
                "services/shared/",
            )):
                continue

            is_python = file_path.suffix == ".py"
            is_ts = file_path.suffix in (".ts", ".js", ".tsx", ".jsx")
            if not is_python and not is_ts:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            if len(content) > _MAX_FILE_SIZE:
                continue

            implementing_funcs = _find_implementing_functions(
                content, rule_type, is_python,
            )

            if not implementing_funcs:
                continue

            rule_implemented = True
            rel_path = file_path.relative_to(project_root).as_posix()

            for func_name, body_lines in implementing_funcs:
                if len(violations) >= _MAX_VIOLATIONS:
                    break

                body_text = "\n".join(body_lines)

                # Check required operations
                missing_ops: list[str] = []
                for op in required_ops:
                    pattern = _OPERATION_PATTERNS.get(op)
                    if pattern and not pattern.search(body_text):
                        missing_ops.append(op)

                if missing_ops:
                    violations.append(Violation(
                        check="RULE-001",
                        message=(
                            f"{rule_id} ({entity}): function '{func_name}' "
                            f"is missing required operations: "
                            f"{', '.join(missing_ops)}."
                        ),
                        file_path=rel_path,
                        line=0,
                        severity="warning",
                    ))

                # Check anti-patterns
                for ap_desc in anti_patterns:
                    if len(violations) >= _MAX_VIOLATIONS:
                        break
                    ap_lower = ap_desc.lower()
                    matched_ap = False
                    for key, ap_re in _ANTI_PATTERN_MAP.items():
                        if key in ap_lower:
                            # Check each line for the anti-pattern
                            for line in body_lines:
                                if ap_re.match(line) or ap_re.search(line):
                                    matched_ap = True
                                    break
                            if matched_ap:
                                break

                    if matched_ap:
                        violations.append(Violation(
                            check="RULE-001",
                            message=(
                                f"{rule_id} ({entity}): function "
                                f"'{func_name}' exhibits anti-pattern: "
                                f"{ap_desc}."
                            ),
                            file_path=rel_path,
                            line=0,
                            severity="error",
                        ))

        if not rule_implemented:
            violations.append(Violation(
                check="RULE-001",
                message=(
                    f"No implementation found for {rule_id}: "
                    f"no implementing function for entity '{entity}' "
                    f"(rule_type={rule_type})."
                ),
                file_path="(no matching file)",
                line=0,
                severity="critical",
            ))

    violations = violations[:_MAX_VIOLATIONS]
    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )
    return violations


# ---------------------------------------------------------------------------
# CONTRACT-001: Contract Import Verification Scan
# ---------------------------------------------------------------------------


def run_contract_import_scan(
    project_root: Path,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """Detect services using raw HTTP calls instead of generated contract clients.

    Checks for raw fetch()/axios/httpx calls in service files that exist
    alongside generated client libraries (e.g., GlClient, ArClient).
    """
    violations: list[Violation] = []
    source_files = _iter_source_files(project_root)

    if scope and scope.mode == "changed_only":
        if not scope.changed_files:
            return []
        scope_set = set(scope.changed_files)
        source_files = [f for f in source_files if f.resolve() in scope_set]

    # Phase 1: Find generated client files
    client_pattern = re.compile(
        r"(?:class|export\s+class)\s+(\w+Client)\b", re.IGNORECASE,
    )
    available_clients: dict[str, str] = {}  # service_prefix -> client class name

    for file_path in source_files:
        fname = file_path.name.lower()
        if "client" not in fname:
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in client_pattern.finditer(content):
            client_name = m.group(1)
            # Extract service prefix: GlClient -> gl, ArClient -> ar
            prefix = re.sub(r"Client$", "", client_name, flags=re.IGNORECASE).lower()
            if prefix:
                available_clients[prefix] = client_name

    if not available_clients:
        return []

    # Phase 2: Check service files for raw HTTP calls
    raw_http_re = re.compile(
        r"\bfetch\s*\(|"
        r"\baxios\s*[\.(]|"
        r"\bhttpx\s*[\.(]|"
        r"new\s+HttpClient\s*\(|"
        r"requests\s*\.\s*(?:get|post|put|patch|delete)\s*\(",
        re.IGNORECASE,
    )
    # Patterns that indicate a generated client IS being used
    client_import_re = re.compile(
        r"(?:import|from)\s+.*(?:"
        + "|".join(re.escape(c) for c in available_clients.values())
        + r")",
        re.IGNORECASE,
    )

    for file_path in source_files:
        if len(violations) >= _MAX_VIOLATIONS:
            break
        fname_lower = file_path.name.lower()
        # Only check service/controller files, not clients themselves
        if "client" in fname_lower:
            continue
        if not any(kw in fname_lower for kw in (
            "service", "controller", "handler", "subscriber",
        )):
            continue
        # Skip test files
        if any(pat in fname_lower for pat in (
            ".spec.", ".test.", "_test.", ".e2e-spec.",
        )):
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if len(content) > _MAX_FILE_SIZE:
            continue

        # Check for raw HTTP calls
        raw_matches = list(raw_http_re.finditer(content))
        if not raw_matches:
            continue

        # Check if the file also imports a generated client
        has_client_import = bool(client_import_re.search(content))

        for match in raw_matches:
            if len(violations) >= _MAX_VIOLATIONS:
                break
            # Find line number
            line_num = content[:match.start()].count("\n") + 1
            call_text = content[match.start():match.start() + 40].strip()
            violations.append(Violation(
                check="CONTRACT-001",
                message=(
                    f"Raw HTTP call '{call_text}...' found in service file. "
                    f"Generated contract clients are available: "
                    f"{', '.join(available_clients.values())}. "
                    f"{'File also imports a client — verify this call is necessary.' if has_client_import else 'Consider using the generated client instead of raw HTTP.'}"
                ),
                file_path=file_path.relative_to(project_root).as_posix(),
                line=line_num,
                severity="warning",
            ))

    violations.sort(
        key=lambda v: (_SEVERITY_ORDER.get(v.severity, 99), v.file_path, v.line)
    )
    return violations[:_MAX_VIOLATIONS]


# ---------------------------------------------------------------------------
# B4: Accounting Smoke Test
# ---------------------------------------------------------------------------

_ACCOUNTING_CHECKS_LIST = [
    {
        "name": "double_entry_check",
        "description": "Journal entry creation checks debit == credit balance",
        "file_keywords": ["journal", "entry", "gl"],
        "body_re": r"debit.*credit|credit.*debit|total.*debit.*total.*credit|balance.*zero|sum.*lines",
    },
    {
        "name": "period_close_event",
        "description": "Period close publishes event or checks posting",
        "file_keywords": ["period", "fiscal"],
        "body_re": r"emit|publish|dispatch|event|closed|posting.*forbidden|cannot.*post",
    },
    {
        "name": "depreciation_arithmetic",
        "description": "Depreciation function contains arithmetic",
        "file_keywords": ["depreciat", "asset"],
        "body_re": r"cost.*residual|useful.*life|straight.*line|depreciation.*amount",
    },
    {
        "name": "matching_comparison",
        "description": "Matching function contains comparison or tolerance logic",
        "file_keywords": ["match", "invoice", "purchase"],
        "body_re": r"tolerance|threshold|difference|mismatch",
    },
    {
        "name": "reconciliation_balance",
        "description": "Reconciliation verifies difference equals zero",
        "file_keywords": ["reconcil", "banking"],
        "body_re": r"difference.*zero|balance.*zero|difference|unreconciled",
    },
    {
        "name": "invoice_gl_posting",
        "description": "Invoice creation triggers GL journal entry",
        "file_keywords": ["invoice", "ar", "ap"],
        "body_re": r"gl.*client|journal.*entry|create.*journal|gl.*service|post.*journal",
    },
]


def run_accounting_smoke_test(
    project_root: Path,
    business_rules: list | None = None,
) -> list[Violation]:
    """B4: Verify critical accounting patterns are implemented, not just declared."""
    violations: list[Violation] = []
    source_files = _iter_source_files(project_root)

    for check in _ACCOUNTING_CHECKS_LIST:
        check_name = check["name"]
        file_keywords = check["file_keywords"]
        body_pat = re.compile(check["body_re"], re.IGNORECASE)

        candidates = [
            f for f in source_files
            if any(kw in f.name.lower() or kw in str(f.parent).lower()
                   for kw in file_keywords)
            and not _RE_TEST_FILE.search(f.name)
        ]

        if not candidates:
            violations.append(Violation(
                check="ACCT-001",
                message=f"Accounting check '{check_name}': no source files found",
                file_path="(project-wide)",
                line=0,
                severity="warning",
            ))
            continue

        pattern_found = False
        for f in candidates:
            try:
                c = f.read_text(encoding="utf-8", errors="replace")
                if body_pat.search(c):
                    pattern_found = True
                    break
            except OSError:
                continue

        if not pattern_found:
            violations.append(Violation(
                check="ACCT-002",
                message=(
                    f"Accounting check '{check_name}' FAILED: {check['description']} -- "
                    f"no matching pattern in {len(candidates)} file(s)"
                ),
                file_path=candidates[0].relative_to(project_root).as_posix() if candidates else "(unknown)",
                line=0,
                severity="warning",
            ))

    return violations


# ---------------------------------------------------------------------------
# B2: Shortcut Detection Scan
# ---------------------------------------------------------------------------

_TRIVIAL_BODY_RE = re.compile(
    r"^\s*(?:"
    r"pass\s*$|"
    r"return\s*$|"
    r"return\s+(?:None|null|0|0\.0|true|True|false|False|\[\]|\{\})\s*[;\s]*$|"
    r"\.\.\.\s*$"  # Python Ellipsis
    r")",
    re.MULTILINE,
)

_EMPTY_CLASS_RE = re.compile(
    r"(?:export\s+)?class\s+(\w+)[^{]*\{\s*\}",
    re.MULTILINE | re.DOTALL,
)

# Log-only function body pattern (matches when ALL lines are logging)
_SHORTCUT_LOG_RE = re.compile(
    r"^\s*(?:"
    r"logger\.\w+\(|"
    r"logging\.\w+\(|"
    r"console\.\w+\(|"
    r"this\.logger\.\w+\(|"
    r"self\.logger\.\w+\(|"
    r"print\("
    r")",
)


def run_shortcut_detection_scan(
    project_root: Path,
    scope: ScanScope | None = None,
) -> list[Violation]:
    """B2: Detect functions that accept inputs they don't use.

    Also detects:
    - SHORTCUT-003: Functions with trivial return-only bodies
    - SHORTCUT-004: Empty class bodies
    - SHORTCUT-005: Functions whose body is only logging statements
    """
    violations: list[Violation] = []
    source_files = _iter_source_files(project_root)

    if scope and scope.mode == "changed_only":
        if not scope.changed_files:
            return []
        scope_set = set(scope.changed_files)
        source_files = [f for f in source_files if f.resolve() in scope_set]

    fn_pat = re.compile(
        r"(?:export\s+)?(?:async\s+)?(?:def|function)\s+(\w+)\s*\(([^)]*)\)",
    )
    await_pat = re.compile(r"await")

    for file_path in source_files:
        if len(violations) >= _MAX_VIOLATIONS:
            break
        if _RE_TEST_FILE.search(file_path.name):
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if len(content) > _MAX_FILE_SIZE:
            continue

        rel_path = file_path.relative_to(project_root).as_posix()
        file_lines = content.splitlines()

        for lineno, line in enumerate(file_lines, start=1):
            m = fn_pat.search(line)
            if not m:
                continue

            fn_name = m.group(1)
            params_str = m.group(2).strip()
            if not params_str:
                continue

            params = [p.strip().split(":")[0].split("=")[0].strip()
                       for p in params_str.split(",") if p.strip()]
            params = [p for p in params if p and p != "self" and p != "cls"]
            if len(params) < 3:
                continue

            body_lines = file_lines[lineno: min(lineno + 30, len(file_lines))]
            body = "\n".join(body_lines)

            is_async = "async" in line
            if is_async and not await_pat.search(body):
                violations.append(Violation(
                    check="SHORTCUT-001",
                    message=f"Async function '{fn_name}()' never uses await",
                    file_path=rel_path,
                    line=lineno,
                    severity="info",
                ))

            unused_count = sum(1 for p in params if p.split()[0] not in body)
            if unused_count > len(params) // 2:
                violations.append(Violation(
                    check="SHORTCUT-002",
                    message=f"Function '{fn_name}()' ignores {unused_count}/{len(params)} parameters",
                    file_path=rel_path,
                    line=lineno,
                    severity="warning",
                ))

        # --- SHORTCUT-003: Trivial-return functions ---
        # Scan all function definitions (including those with 0-2 params)
        fn_all_pat = re.compile(
            r"(?:export\s+)?(?:async\s+)?(?:def|function)\s+(\w+)\s*\([^)]*\)",
        )
        for m_fn in fn_all_pat.finditer(content):
            if len(violations) >= _MAX_VIOLATIONS:
                break
            fn_name_tr = m_fn.group(1)
            fn_lineno = content[:m_fn.start()].count("\n") + 1
            # Extract body (next 10 lines, skip docstrings/comments)
            fn_body_lines = file_lines[fn_lineno: min(fn_lineno + 10, len(file_lines))]
            # Filter out empty lines, comments, and docstrings
            meaningful_lines: list[str] = []
            in_docstring = False
            for bl in fn_body_lines:
                stripped = bl.strip()
                if not stripped:
                    continue
                # Skip Python docstrings
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    if in_docstring:
                        in_docstring = False
                        continue
                    if stripped.count('"""') == 2 or stripped.count("'''") == 2:
                        continue  # Single-line docstring
                    in_docstring = True
                    continue
                if in_docstring:
                    continue
                # Skip comments
                if stripped.startswith("#") or stripped.startswith("//"):
                    continue
                meaningful_lines.append(stripped)
            # Check if there's exactly 1 meaningful line and it's trivial
            if len(meaningful_lines) == 1 and _TRIVIAL_BODY_RE.match(meaningful_lines[0]):
                violations.append(Violation(
                    check="SHORTCUT-003",
                    message=f"Function '{fn_name_tr}()' has a trivial body: '{meaningful_lines[0].strip()}'",
                    file_path=rel_path,
                    line=fn_lineno,
                    severity="warning",
                ))

        # --- SHORTCUT-004: Empty class bodies ---
        for m_cls in _EMPTY_CLASS_RE.finditer(content):
            if len(violations) >= _MAX_VIOLATIONS:
                break
            cls_name = m_cls.group(1)
            cls_lineno = content[:m_cls.start()].count("\n") + 1
            violations.append(Violation(
                check="SHORTCUT-004",
                message=f"Class '{cls_name}' has an empty body",
                file_path=rel_path,
                line=cls_lineno,
                severity="warning",
            ))

        # --- SHORTCUT-005: Log-only function bodies ---
        for m_fn in fn_all_pat.finditer(content):
            if len(violations) >= _MAX_VIOLATIONS:
                break
            fn_name_lg = m_fn.group(1)
            fn_lineno = content[:m_fn.start()].count("\n") + 1
            fn_body_lines_lg = file_lines[fn_lineno: min(fn_lineno + 20, len(file_lines))]
            # Collect non-empty, non-comment lines
            code_lines: list[str] = []
            for bl in fn_body_lines_lg:
                stripped = bl.strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("//"):
                    continue
                # Stop at next function/class definition (same or lower indent)
                if re.match(r"(?:export\s+)?(?:async\s+)?(?:def|function|class)\s+", stripped):
                    break
                code_lines.append(stripped)
            # Need at least 1 code line and ALL must be logging
            if code_lines and all(_SHORTCUT_LOG_RE.match(cl) for cl in code_lines):
                violations.append(Violation(
                    check="SHORTCUT-005",
                    message=f"Function '{fn_name_lg}()' body contains only logging statements",
                    file_path=rel_path,
                    line=fn_lineno,
                    severity="info",
                ))

    return violations[:_MAX_VIOLATIONS]



# ---------------------------------------------------------------------------
# A10: Quality Score Prediction (Regression Guardrail)
# ---------------------------------------------------------------------------


def compute_quality_score(
    project_root: Path,
    entity_names: list[str] | None = None,
) -> dict:
    """Compute a predicted quality score for a build.

    Runs all scans and produces a score prediction calibrated against manual
    audits. Used by the regression guardrail (Sim 15) to verify builds don't
    regress.

    Returns dict with 'predicted_score', 'deductions', and 'scan_results'.
    """
    spot = run_spot_checks(project_root)
    handlers = run_handler_completeness_scan(project_root)
    entities_v = run_entity_coverage_scan(project_root, entity_names) if entity_names else []

    from collections import Counter
    ecodes = Counter(v.check for v in entities_v)
    scodes = Counter(v.check for v in spot)

    # Stub-specific violations (high penalty)
    stub_count = sum(scodes.get(c, 0) for c in [
        'STUB-010', 'STUB-011', 'STUB-012', 'STUB-013', 'STUB-014', 'STUB-015', 'STUB-016',
    ])

    base = 12000
    deductions = {
        'handler_stubs': min(len(handlers) * 150, 800),
        'code_stubs': min(stub_count * 25, 400),
        'missing_entities': min(ecodes.get('ENTITY-001', 0) * 35, 450),
        'missing_routes': min(ecodes.get('ENTITY-002', 0) * 12, 250),
        'missing_tests': min(ecodes.get('ENTITY-003', 0) * 6, 200),
        'spot_quality': min((len(spot) - stub_count) * 2, 150),
    }
    total_deduction = sum(deductions.values())
    predicted = base - total_deduction

    return {
        'predicted_score': predicted,
        'base': base,
        'total_deduction': total_deduction,
        'deductions': deductions,
        'scan_counts': {
            'spot_checks': len(spot),
            'handler_stubs': len(handlers),
            'entity_violations': len(entities_v),
            'stub_violations': stub_count,
        },
    }


# ---------------------------------------------------------------------------
# DOCKER-001: Dockerfile Quality Scan (M23 fix)
# ---------------------------------------------------------------------------


def run_dockerfile_scan(
    project_root: Path,
) -> list[Violation]:
    """Detect missing best practices in Dockerfiles.

    Checks:
    - DOCKER-001: Missing HEALTHCHECK instruction
    """
    violations: list[Violation] = []

    # Find all Dockerfiles (not in node_modules, .git, .venv)
    skip_dirs = frozenset({
        "node_modules", ".git", ".venv", "venv", "__pycache__",
        ".mypy_cache", ".pytest_cache",
    })
    for root_dir, dirs, files in os.walk(project_root):
        # Prune skipped directories
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if fname != "Dockerfile":
                continue
            fpath = Path(root_dir) / fname
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            rel_path = fpath.relative_to(project_root).as_posix()

            # DOCKER-001: Missing HEALTHCHECK
            if not re.search(r"^\s*HEALTHCHECK\s", content, re.MULTILINE):
                violations.append(Violation(
                    check="DOCKER-001",
                    message=(
                        f"Dockerfile '{rel_path}' is missing a HEALTHCHECK instruction. "
                        f"Add HEALTHCHECK to enable container health monitoring."
                    ),
                    file_path=rel_path,
                    line=1,
                    severity="warning",
                ))

    return violations
