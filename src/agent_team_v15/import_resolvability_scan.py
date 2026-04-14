"""Deterministic post-Wave-D scanner for TypeScript import resolvability.

Bug class: Wave D writes a file (e.g. `apps/web/src/i18n/navigation.ts`) without
exporting symbols that other files import (`Link`, `usePathname`, `redirect`,
`useRouter`). The audit catches it eventually, but a deterministic scanner
catches it as a structural check before the audit and feeds findings into the
existing frontend-hallucination fix sub-agent.

Findings:
  IMPORT-RESOLVABLE-001 — imported symbol is not exported by the resolved target
  IMPORT-RESOLVABLE-002 — module specifier resolves to no file on disk

The scanner is pure-Python regex-based to match the existing
`quality_checks.py` style (no Node/ts-morph dependency).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .quality_checks import EXCLUDED_DIRS, Violation


_RESOLVABLE_EXTENSIONS = (".ts", ".tsx", ".d.ts", ".js", ".jsx")
_INDEX_FILES = ("index.ts", "index.tsx", "index.d.ts", "index.js", "index.jsx")
_MAX_VIOLATIONS = 200

# Match: import { A, B as Bx, type C } from 'path';
_RE_NAMED_IMPORT = re.compile(
    r"""^\s*import\s+
        (?:type\s+)?                       # type-only import keyword (skip)
        (?:[A-Za-z_$][\w$]*\s*,\s*)?        # optional default before braces
        \{\s*([^}]+)\}\s*
        from\s*['"]([^'"]+)['"]""",
    re.VERBOSE | re.MULTILINE,
)

# Match: import Foo from 'path';   (default-only)
_RE_DEFAULT_IMPORT = re.compile(
    r"""^\s*import\s+
        (?!type\s)
        ([A-Za-z_$][\w$]*)\s+
        from\s*['"]([^'"]+)['"]""",
    re.VERBOSE | re.MULTILINE,
)

# Match: import * as Foo from 'path';
_RE_NAMESPACE_IMPORT = re.compile(
    r"""^\s*import\s+\*\s+as\s+
        ([A-Za-z_$][\w$]*)\s+
        from\s*['"]([^'"]+)['"]""",
    re.VERBOSE | re.MULTILINE,
)

# Top-level `export` patterns we recognize as providing a name:
_RE_EXPORT_NAMED_DECL = re.compile(
    r"""^\s*export\s+
        (?:async\s+)?
        (?:const|let|var|function|class|interface|type|enum)\s+
        ([A-Za-z_$][\w$]*)""",
    re.VERBOSE | re.MULTILINE,
)

# export { A, B as C, type D }
_RE_EXPORT_NAMED_LIST = re.compile(
    r"""^\s*export\s*\{\s*([^}]+)\}""",
    re.VERBOSE | re.MULTILINE,
)

# export const { A, B } = ...
_RE_EXPORT_DESTRUCTURED = re.compile(
    r"""^\s*export\s+
        (?:const|let|var)\s*
        \{\s*([^}]+)\}\s*
        =""",
    re.VERBOSE | re.MULTILINE,
)

# export * from './x';
_RE_EXPORT_STAR_FROM = re.compile(
    r"""^\s*export\s*\*\s*from\s*['"]([^'"]+)['"]""",
    re.VERBOSE | re.MULTILINE,
)

_RE_EXPORT_DEFAULT = re.compile(r"^\s*export\s+default\b", re.MULTILINE)


def run_import_resolvability_scan(project_root: Path) -> list[Violation]:
    """Walk TypeScript sources and emit import-resolvability findings."""
    project_root = Path(project_root)
    if not project_root.is_dir():
        return []

    tsconfigs = _load_tsconfigs(project_root)
    export_cache: dict[Path, set[str] | None] = {}
    violations: list[Violation] = []

    for source_file in _iter_ts_files(project_root):
        if len(violations) >= _MAX_VIOLATIONS:
            break
        try:
            content = source_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel_importer = source_file.relative_to(project_root).as_posix()
        except ValueError:
            rel_importer = str(source_file)

        for line_no, names, specifier, allow_default in _iter_imports(content):
            if _is_external_specifier(specifier):
                continue
            target = _resolve_specifier(
                specifier=specifier,
                importer=source_file,
                project_root=project_root,
                tsconfigs=tsconfigs,
            )
            if target is None:
                violations.append(Violation(
                    check="IMPORT-RESOLVABLE-002",
                    message=f"Module specifier '{specifier}' does not resolve to a file on disk",
                    file_path=rel_importer,
                    line=line_no,
                    severity="error",
                ))
                continue
            exports = _exports_for(target, project_root, export_cache)
            if exports is None:
                continue  # could not parse — don't false-positive
            if allow_default and "default" not in exports and not names:
                violations.append(Violation(
                    check="IMPORT-RESOLVABLE-001",
                    message=(
                        f"Default import from '{specifier}' but target has no `export default`"
                    ),
                    file_path=rel_importer,
                    line=line_no,
                    severity="error",
                ))
            for name in names:
                if name in exports:
                    continue
                violations.append(Violation(
                    check="IMPORT-RESOLVABLE-001",
                    message=(
                        f"Import `{name}` from '{specifier}' is not exported by "
                        f"{target.relative_to(project_root).as_posix()}"
                    ),
                    file_path=rel_importer,
                    line=line_no,
                    severity="error",
                ))

    violations.sort(key=lambda v: (v.file_path, v.line, v.message))
    return violations[:_MAX_VIOLATIONS]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _iter_ts_files(project_root: Path):
    for path in project_root.rglob("*"):
        if not path.is_file() or path.suffix not in (".ts", ".tsx"):
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        yield path


def _is_external_specifier(specifier: str) -> bool:
    if not specifier:
        return True
    if specifier.startswith((".", "/")):
        return False
    # Path aliases (e.g. @/) start with @ but contain a slash (after @scope/pkg the rest is bare-pkg)
    # We treat anything starting with "@/" or other configured alias as path alias (handled in resolve).
    if specifier.startswith("@/"):
        return False
    return True  # bare pkg specifier ("react", "@scope/pkg", "next-intl/navigation", etc.)


def _iter_imports(content: str):
    """Yield (line_no, names, specifier, allow_default) for each import."""
    for match in _RE_NAMESPACE_IMPORT.finditer(content):
        # `import * as X from 'y'` — only checks that y resolves; cannot validate symbol
        line_no = content[: match.start()].count("\n") + 1
        yield (line_no, [], match.group(2), False)
    for match in _RE_NAMED_IMPORT.finditer(content):
        # Skip type-only imports — TS type imports are erased and need looser checks
        leading = match.group(0).split("import", 1)[1].lstrip()
        if leading.startswith("type"):
            continue
        names_blob = match.group(1)
        names = _parse_import_names(names_blob)
        if not names:
            continue
        line_no = content[: match.start()].count("\n") + 1
        yield (line_no, names, match.group(2), False)
    for match in _RE_DEFAULT_IMPORT.finditer(content):
        line_no = content[: match.start()].count("\n") + 1
        yield (line_no, [], match.group(2), True)


def _parse_import_names(blob: str) -> list[str]:
    """Parse `A, B as C, type D` → ['A', 'C']. 'type' qualifier ignored."""
    names: list[str] = []
    for raw in blob.split(","):
        tok = raw.strip()
        if not tok:
            continue
        # strip trailing comments
        if "//" in tok:
            tok = tok.split("//", 1)[0].strip()
        if tok.startswith("type "):
            continue  # type-only named import; permissive
        if " as " in tok:
            tok = tok.split(" as ", 1)[1].strip()
        # strip generics or other noise — leave plain identifier
        m = re.match(r"([A-Za-z_$][\w$]*)", tok)
        if m:
            names.append(m.group(1))
    return names


def _load_tsconfigs(project_root: Path) -> list[tuple[Path, dict]]:
    """Return [(tsconfig_dir, paths_map_dict)] for tsconfig.json files in project."""
    results: list[tuple[Path, dict]] = []
    for cfg_path in project_root.rglob("tsconfig.json"):
        if any(part in EXCLUDED_DIRS for part in cfg_path.parts):
            continue
        try:
            raw = cfg_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # tsconfig allows trailing commas + comments — strip naively
        cleaned = re.sub(r"//[^\n]*", "", raw)
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            continue
        compiler_opts = data.get("compilerOptions") or {}
        paths = compiler_opts.get("paths") or {}
        base_url = compiler_opts.get("baseUrl") or "."
        if paths:
            base_dir = (cfg_path.parent / base_url).resolve()
            results.append((base_dir, paths))
    return results


def _resolve_specifier(
    *,
    specifier: str,
    importer: Path,
    project_root: Path,
    tsconfigs: list[tuple[Path, dict]],
) -> Path | None:
    candidate: Path | None = None
    if specifier.startswith("."):
        candidate = (importer.parent / specifier).resolve()
    elif specifier.startswith("/"):
        candidate = Path(specifier).resolve()
    else:
        # path alias resolution
        for base_dir, paths in tsconfigs:
            for alias, targets in paths.items():
                if not isinstance(targets, list) or not targets:
                    continue
                if alias.endswith("/*"):
                    prefix = alias[:-2]
                    if specifier.startswith(prefix + "/"):
                        suffix = specifier[len(prefix) + 1:]
                        for tgt in targets:
                            if not isinstance(tgt, str):
                                continue
                            replaced = tgt.replace("*", suffix)
                            candidate = (base_dir / replaced).resolve()
                            resolved = _try_extensions(candidate)
                            if resolved is not None:
                                return resolved
                elif alias == specifier:
                    for tgt in targets:
                        if not isinstance(tgt, str):
                            continue
                        candidate = (base_dir / tgt).resolve()
                        resolved = _try_extensions(candidate)
                        if resolved is not None:
                            return resolved
        return None  # alias did not match; treat as external
    return _try_extensions(candidate)


def _try_extensions(candidate: Path | None) -> Path | None:
    if candidate is None:
        return None
    if candidate.is_file():
        return candidate
    for ext in _RESOLVABLE_EXTENSIONS:
        with_ext = candidate.with_suffix(ext)
        if with_ext.is_file():
            return with_ext
        # also handle no-suffix candidates
        sibling = candidate.parent / (candidate.name + ext)
        if sibling.is_file():
            return sibling
    if candidate.is_dir():
        for index in _INDEX_FILES:
            idx = candidate / index
            if idx.is_file():
                return idx
    return None


def _exports_for(
    target: Path,
    project_root: Path,
    cache: dict[Path, set[str] | None],
) -> set[str] | None:
    if target in cache:
        return cache[target]
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        cache[target] = None
        return None
    exports: set[str] = set()
    for match in _RE_EXPORT_NAMED_DECL.finditer(content):
        exports.add(match.group(1))
    for match in _RE_EXPORT_NAMED_LIST.finditer(content):
        for raw in match.group(1).split(","):
            tok = raw.strip()
            if not tok:
                continue
            if tok.startswith("type "):
                tok = tok[5:].strip()
            if " as " in tok:
                tok = tok.split(" as ", 1)[1].strip()
            m = re.match(r"([A-Za-z_$][\w$]*)", tok)
            if m:
                exports.add(m.group(1))
    for match in _RE_EXPORT_DESTRUCTURED.finditer(content):
        for raw in match.group(1).split(","):
            tok = raw.strip()
            if not tok:
                continue
            if ":" in tok:
                # `Foo: localName` — exported name is the key (LHS of :)
                tok = tok.split(":", 1)[0].strip()
            m = re.match(r"([A-Za-z_$][\w$]*)", tok)
            if m:
                exports.add(m.group(1))
    if _RE_EXPORT_DEFAULT.search(content):
        exports.add("default")
    # Re-export: `export * from './x'` — pull in target's exports
    for match in _RE_EXPORT_STAR_FROM.finditer(content):
        sub_specifier = match.group(1)
        if not sub_specifier.startswith("."):
            continue
        sub_target = _try_extensions((target.parent / sub_specifier).resolve())
        if sub_target is None:
            continue
        sub_exports = _exports_for(sub_target, project_root, cache)
        if sub_exports:
            exports.update(name for name in sub_exports if name != "default")

    cache[target] = exports
    return exports
