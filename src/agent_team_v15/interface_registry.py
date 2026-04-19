"""Live interface registry — project-wide IntelliSense for milestones.

Maintains a structured registry of every module's public interfaces
(function signatures, endpoints, types, events). Updated after each
milestone completes. Each milestone receives the full registry (compact —
signatures only, not implementations) so it has project-wide awareness
without loading the entire codebase.

For 500K LOC with 200 entities, the registry is ~20K tokens — 10% of
the context window. Each milestone also receives targeted implementations
of functions it directly calls (~10-20K tokens).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FunctionSignature:
    """A single exported function/method signature."""
    name: str
    file_path: str
    params: list[str] = field(default_factory=list)
    return_type: str = ""
    is_async: bool = False
    line: int = 0


@dataclass
class EndpointEntry:
    """A registered API endpoint."""
    method: str       # GET, POST, PUT, PATCH, DELETE
    path: str         # /invoices, /invoices/{id}
    handler: str      # function name
    file_path: str
    line: int = 0


@dataclass
class EventEntry:
    """A registered event publication or subscription."""
    event_name: str
    direction: str    # "publish" or "subscribe"
    handler: str      # function name
    file_path: str
    line: int = 0


@dataclass
class ModuleInterface:
    """Complete interface for a single module/service."""
    module_name: str
    functions: list[FunctionSignature] = field(default_factory=list)
    endpoints: list[EndpointEntry] = field(default_factory=list)
    events: list[EventEntry] = field(default_factory=list)
    types: list[str] = field(default_factory=list)  # Exported type/class names
    updated_by_milestone: str = ""


@dataclass
class InterfaceRegistry:
    """The complete project interface registry."""
    project_name: str = ""
    modules: dict[str, ModuleInterface] = field(default_factory=dict)
    last_updated_milestone: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "project_name": self.project_name,
            "last_updated_milestone": self.last_updated_milestone,
            "modules": {
                name: {
                    "module_name": mod.module_name,
                    "functions": [asdict(f) for f in mod.functions],
                    "endpoints": [asdict(e) for e in mod.endpoints],
                    "events": [asdict(e) for e in mod.events],
                    "types": mod.types,
                    "updated_by_milestone": mod.updated_by_milestone,
                }
                for name, mod in self.modules.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InterfaceRegistry:
        """Deserialize from a JSON dict."""
        registry = cls(
            project_name=data.get("project_name", ""),
            last_updated_milestone=data.get("last_updated_milestone", ""),
        )
        for name, mod_data in data.get("modules", {}).items():
            registry.modules[name] = ModuleInterface(
                module_name=mod_data.get("module_name", name),
                functions=[FunctionSignature(**f) for f in mod_data.get("functions", [])],
                endpoints=[EndpointEntry(**e) for e in mod_data.get("endpoints", [])],
                events=[EventEntry(**e) for e in mod_data.get("events", [])],
                types=mod_data.get("types", []),
                updated_by_milestone=mod_data.get("updated_by_milestone", ""),
            )
        return registry


# ---------------------------------------------------------------------------
# Extraction: scan source files for public interfaces
# ---------------------------------------------------------------------------

# Python patterns
_PY_FUNC = re.compile(
    r"^(async\s+)?def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([^\s:]+))?",
    re.MULTILINE,
)
_PY_CLASS = re.compile(r"^class\s+(\w+)", re.MULTILINE)
_PY_ROUTE = re.compile(
    r'@(?:router|app)\.(get|post|put|patch|delete)\s*\(\s*["\']([^"\']+)',
    re.IGNORECASE | re.MULTILINE,
)

# TypeScript patterns
_TS_FUNC = re.compile(
    r"(async\s+)?(\w+)\s*\(([^)]*)\)\s*(?::\s*([^\s{]+))?\s*\{",
    re.MULTILINE,
)
_TS_CLASS = re.compile(r"(?:export\s+)?class\s+(\w+)", re.MULTILINE)
_TS_ROUTE = re.compile(
    r"@(Get|Post|Put|Patch|Delete)\s*\(\s*['\"]?([^'\")\s]*)",
    re.MULTILINE,
)

# Event patterns (both languages)
_EVENT_PUBLISH = re.compile(
    r"(?:publish_event|publish|emit|publishEvent)\s*\(\s*['\"`]([^'\"`]+)",
    re.IGNORECASE,
)
_EVENT_SUBSCRIBE = re.compile(
    r"(?:subscribe|listen|on)\s*\(\s*['\"`]([^'\"`]+)",
    re.IGNORECASE,
)

# Skip directories
_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".git", "dist", "build",
    ".venv", "venv", ".next", ".angular", "coverage",
})

_SOURCE_EXTS = frozenset({".py", ".ts", ".js"})


def extract_module_interface(
    module_dir: Path,
    module_name: str,
    project_root: Path | None = None,
) -> ModuleInterface:
    """Extract public interfaces from all source files in a module directory.

    Scans for function definitions, class definitions, route decorators,
    and event publish/subscribe patterns.
    """
    interface = ModuleInterface(module_name=module_name)

    if not module_dir.is_dir():
        return interface

    root = project_root or module_dir.parent

    for file_path in _walk_source_files(module_dir):
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if len(content) > 200_000:  # Skip very large files
            continue

        rel_path = str(file_path.relative_to(root)).replace("\\", "/")
        is_python = file_path.suffix == ".py"

        # Functions
        func_pat = _PY_FUNC if is_python else _TS_FUNC
        for m in func_pat.finditer(content):
            is_async = bool(m.group(1))
            name = m.group(2)
            # Skip private/internal functions
            if name.startswith("_") and not name.startswith("__"):
                continue
            params_raw = m.group(3).strip()
            params = [p.strip().split(":")[0].strip() for p in params_raw.split(",") if p.strip()] if params_raw else []
            return_type = (m.group(4) or "").strip()
            line = content[:m.start()].count("\n") + 1
            interface.functions.append(FunctionSignature(
                name=name, file_path=rel_path, params=params,
                return_type=return_type, is_async=is_async, line=line,
            ))

        # Classes/types
        class_pat = _PY_CLASS if is_python else _TS_CLASS
        for m in class_pat.finditer(content):
            interface.types.append(m.group(1))

        # Routes/endpoints
        route_pat = _PY_ROUTE if is_python else _TS_ROUTE
        for m in route_pat.finditer(content):
            method = m.group(1).upper()
            path = m.group(2)
            line = content[:m.start()].count("\n") + 1
            # Find the handler function name (next def/function after the decorator)
            after = content[m.end():]
            handler = ""
            if is_python:
                hm = re.search(r"def\s+(\w+)", after)
                if hm:
                    handler = hm.group(1)
            else:
                hm = re.search(r"(\w+)\s*\(", after)
                if hm:
                    handler = hm.group(1)
            interface.endpoints.append(EndpointEntry(
                method=method, path=path, handler=handler,
                file_path=rel_path, line=line,
            ))

        # Events
        for m in _EVENT_PUBLISH.finditer(content):
            line = content[:m.start()].count("\n") + 1
            interface.events.append(EventEntry(
                event_name=m.group(1), direction="publish",
                handler="", file_path=rel_path, line=line,
            ))
        for m in _EVENT_SUBSCRIBE.finditer(content):
            line = content[:m.start()].count("\n") + 1
            interface.events.append(EventEntry(
                event_name=m.group(1), direction="subscribe",
                handler="", file_path=rel_path, line=line,
            ))

    # Deduplicate types
    interface.types = sorted(set(interface.types))

    return interface


def _walk_source_files(directory: Path) -> list[Path]:
    """Walk directory for source files, skipping excluded dirs."""
    # Safe walker — prunes node_modules / .pnpm at descent so Windows
    # MAX_PATH inside pnpm's symlink tree can't raise WinError 3
    # (project_walker.py post smoke #9/#10).
    from .project_walker import DEFAULT_SKIP_DIRS, iter_project_files

    merged_skips = set(DEFAULT_SKIP_DIRS) | set(_SKIP_DIRS)
    return [
        item
        for item in iter_project_files(directory, skip_dirs=merged_skips)
        if item.suffix in _SOURCE_EXTS
    ]


# ---------------------------------------------------------------------------
# Registry operations
# ---------------------------------------------------------------------------

def update_registry_from_milestone(
    registry: InterfaceRegistry,
    project_root: Path,
    milestone_id: str,
    service_dirs: list[str] | None = None,
) -> InterfaceRegistry:
    """Update the registry after a milestone completes.

    Scans the project for module directories and extracts interfaces.
    If *service_dirs* is provided, only scans those directories.
    Otherwise, auto-detects service directories.
    """
    if service_dirs is None:
        service_dirs = _detect_service_dirs(project_root)

    for svc_dir_name in service_dirs:
        svc_path = project_root / svc_dir_name
        if not svc_path.is_dir():
            # Try under services/
            svc_path = project_root / "services" / svc_dir_name
        if not svc_path.is_dir():
            continue

        module_name = svc_dir_name.replace("services/", "").replace("\\", "/").split("/")[-1]
        interface = extract_module_interface(svc_path, module_name, project_root)
        interface.updated_by_milestone = milestone_id
        registry.modules[module_name] = interface

    registry.last_updated_milestone = milestone_id
    return registry


def _detect_service_dirs(project_root: Path) -> list[str]:
    """Auto-detect service directories in the project."""
    dirs: list[str] = []
    # Check services/ directory
    services_dir = project_root / "services"
    if services_dir.is_dir():
        for item in services_dir.iterdir():
            if item.is_dir() and item.name not in _SKIP_DIRS:
                dirs.append(f"services/{item.name}")
    # Check src/ directory
    src_dir = project_root / "src"
    if src_dir.is_dir():
        for item in src_dir.iterdir():
            if item.is_dir() and item.name not in _SKIP_DIRS:
                dirs.append(f"src/{item.name}")
    # Check for shared/ directory
    shared_dir = project_root / "shared"
    if shared_dir.is_dir():
        dirs.append("shared")
    # Check for frontend/
    frontend_dir = project_root / "frontend"
    if frontend_dir.is_dir():
        dirs.append("frontend")
    return dirs


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def save_registry(registry: InterfaceRegistry, path: Path) -> None:
    """Save registry to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(registry.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )


def load_registry(path: Path) -> InterfaceRegistry:
    """Load registry from a JSON file."""
    if not path.is_file():
        return InterfaceRegistry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return InterfaceRegistry.from_dict(data)
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Failed to load interface registry: %s", exc)
        return InterfaceRegistry()


# ---------------------------------------------------------------------------
# Formatting for prompt injection
# ---------------------------------------------------------------------------

def format_registry_for_prompt(
    registry: InterfaceRegistry,
    max_tokens: int = 20000,
) -> str:
    """Format the registry as compact markdown for prompt injection.

    Shows function signatures, endpoints, events, and types per module.
    Caps output at ~max_tokens to stay within context budget.
    """
    if not registry.modules:
        return ""

    lines = [
        "[INTERFACE REGISTRY — Project-Wide Module Signatures]\n",
        "Use these EXACT signatures when calling functions from other modules.\n",
    ]

    for mod_name, mod in sorted(registry.modules.items()):
        lines.append(f"### {mod_name}")

        # Types (just names)
        if mod.types:
            lines.append(f"Types: {', '.join(mod.types[:20])}")

        # Endpoints
        if mod.endpoints:
            for ep in mod.endpoints[:15]:
                lines.append(f"  {ep.method} {ep.path} → {ep.handler}()")

        # Key functions (skip trivial ones)
        key_funcs = [f for f in mod.functions if not f.name.startswith("_")
                     and f.name not in ("__init__", "main")][:20]
        if key_funcs:
            for func in key_funcs:
                async_prefix = "async " if func.is_async else ""
                params_str = ", ".join(func.params[:5])
                if len(func.params) > 5:
                    params_str += ", ..."
                ret = f" → {func.return_type}" if func.return_type else ""
                lines.append(f"  {async_prefix}{func.name}({params_str}){ret}  [{func.file_path}]")

        # Events
        pubs = [e for e in mod.events if e.direction == "publish"]
        subs = [e for e in mod.events if e.direction == "subscribe"]
        if pubs:
            lines.append(f"  Publishes: {', '.join(e.event_name for e in pubs[:10])}")
        if subs:
            lines.append(f"  Subscribes: {', '.join(e.event_name for e in subs[:10])}")

        lines.append("")

        # Check token budget
        current_size = sum(len(line) for line in lines) // 4
        if current_size > max_tokens:
            lines.append(f"[... truncated at {max_tokens} token budget ...]")
            break

    return "\n".join(lines)


def get_targeted_files(
    registry: InterfaceRegistry,
    needed_functions: list[str],
    project_root: Path,
    max_chars: int = 40000,
) -> str:
    """Load implementation code for specific functions from the registry.

    Given a list of function names that a milestone needs to call,
    finds their source files and returns the relevant code blocks.
    """
    # Build function → file mapping from registry
    func_files: dict[str, str] = {}
    for mod in registry.modules.values():
        for func in mod.functions:
            func_files[func.name] = func.file_path
            # Also index as module.function
            func_files[f"{mod.module_name}.{func.name}"] = func.file_path

    # Collect unique files to load
    files_to_load: dict[str, list[str]] = {}  # file_path → [function_names]
    for func_name in needed_functions:
        file_path = func_files.get(func_name, "")
        if file_path:
            files_to_load.setdefault(file_path, []).append(func_name)

    # Load and format
    lines = ["[TARGETED FILE CONTENTS — Implementations needed by this milestone]\n"]
    total_chars = 0

    for file_path, func_names in files_to_load.items():
        full_path = project_root / file_path
        if not full_path.is_file():
            continue
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Truncate large files
        if len(content) > 10000:
            content = content[:10000] + "\n... [truncated]"

        lines.append(f"### {file_path} (needed for: {', '.join(func_names)})")
        lines.append(f"```")
        lines.append(content)
        lines.append(f"```\n")

        total_chars += len(content)
        if total_chars > max_chars:
            lines.append(f"[... truncated at {max_chars} char budget ...]")
            break

    return "\n".join(lines)
