"""Wave-specific compile profiles for scoped inter-wave verification.

The wave engine should not compile the full workspace after every wave.
This module resolves the smallest useful compile target per wave and stack,
executes those commands, and returns structured compiler errors for fix prompts.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .async_subprocess_compat import create_subprocess_exec_compat

_SKIP_DIRS = frozenset(
    {
        ".agent-team",
        ".git",
        ".next",
        ".venv",
        ".vs",
        "__pycache__",
        "bin",
        "build",
        "dist",
        "node_modules",
        "obj",
        "out",
        "target",
    }
)

# Windows App Execution Alias emits this placeholder for ``tsc.exe``
# (and similar) when the command is invoked but the real binary is not
# installed locally. The message exits non-zero — the compile-check
# harness used to treat that as a real compile failure and loop the
# fix prompts up to the iteration cap (smoke #8
# ``build-final-smoke-20260418-232245`` burned $10.72 this way). The
# sentinel is detected before the tsc-error parser runs and converts
# the result to a dedicated ``ENV_NOT_READY`` diagnostic so downstream
# logic can distinguish "no tsc" from "tsc found errors".
_WINDOWS_AEP_SENTINEL_RE = re.compile(
    r"This is not the\s+\S+\s+command you are looking for",
    re.IGNORECASE,
)

_BACKEND_PARTS = frozenset({"api", "apis", "backend", "server", "service", "services"})
_FRONTEND_PARTS = frozenset({"app", "apps", "client", "frontend", "mobile", "ui", "web"})
_GENERATED_PARTS = frozenset({"generated", "generated-client", "generated_client", "sdk"})
_SHARED_PARTS = frozenset({"common", "contract", "contracts", "shared", "shared-contracts"})


@dataclass
class CompileProfile:
    """Defines what to compile and how."""

    name: str
    commands: list[list[str]]
    description: str = ""


@dataclass
class CompileResult:
    """Raw compile gate result for a single wave boundary."""

    passed: bool = True
    error_count: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    raw_output: str = ""


@dataclass
class CompileCheckResult:
    """Compatibility dataclass for wave compile gate orchestration."""

    passed: bool = True
    iterations: int = 1
    initial_error_count: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


def get_compile_profile(
    wave: str,
    template: str,
    stack_target: str,
    project_root: Path,
) -> CompileProfile:
    """Return the scoped compile profile for this wave and stack."""

    root = Path(project_root)
    stack = (stack_target or "").lower()

    hinted = _stack_ecosystems(stack)
    discovered = _discovered_ecosystems(root)
    ecosystems = hinted or discovered

    profiles: list[CompileProfile] = []
    if "typescript" in ecosystems and _has_tsconfig(root):
        profiles.append(_get_typescript_profile(wave, template, root))
    if "dart" in ecosystems and _has_pubspec(root):
        profiles.append(_get_dart_profile(wave, template, root))
    if "dotnet" in ecosystems and _has_dotnet(root):
        profiles.append(_get_dotnet_profile(wave, template, root))

    profiles = [profile for profile in profiles if profile.commands]
    if not profiles:
        return CompileProfile(name="noop", commands=[], description="No compile profile detected")
    if len(profiles) == 1:
        return profiles[0]
    return _merge_profiles(profiles, wave)


_get_compile_profile = get_compile_profile


def _has_tsconfig(root: Path) -> bool:
    return (root / "tsconfig.json").is_file() or any(_iter_paths(root, "tsconfig.json"))


def _has_pubspec(root: Path) -> bool:
    return (root / "pubspec.yaml").is_file() or any(_iter_paths(root, "pubspec.yaml"))


def _has_dotnet(root: Path) -> bool:
    return any(_iter_paths(root, "*.csproj")) or any(_iter_paths(root, "*.sln"))


def _stack_ecosystems(stack: str) -> set[str]:
    ecosystems: set[str] = set()
    if any(token in stack for token in ("nest", "next", "react", "angular", "typescript")):
        ecosystems.add("typescript")
    if any(token in stack for token in ("flutter", "dart")):
        ecosystems.add("dart")
    if any(token in stack for token in ("dotnet", ".net", "asp.net", "blazor", "c#")):
        ecosystems.add("dotnet")
    return ecosystems


def _discovered_ecosystems(root: Path) -> set[str]:
    ecosystems: set[str] = set()
    if _has_tsconfig(root):
        ecosystems.add("typescript")
    if _has_pubspec(root):
        ecosystems.add("dart")
    if _has_dotnet(root):
        ecosystems.add("dotnet")
    return ecosystems


def _iter_paths(root: Path, pattern: str) -> list[Path]:
    """Return files matching *pattern* under *root*, pruning _SKIP_DIRS at descent.

    Uses the shared safe walker (project_walker.iter_project_files)
    so node_modules / .pnpm symlink trees can never raise WinError 3
    mid-iteration (see PR #39 / smoke #9).
    """
    from .project_walker import iter_project_files
    return iter_project_files(root, patterns=(pattern,), skip_dirs=_SKIP_DIRS)


def _profile_name(prefix: str, wave: str) -> str:
    return f"{prefix}_wave_{wave or 'unknown'}"


def _merge_profiles(profiles: list[CompileProfile], wave: str) -> CompileProfile:
    commands: list[list[str]] = []
    descriptions: list[str] = []
    for profile in profiles:
        commands.extend(profile.commands)
        if profile.description:
            descriptions.append(profile.description)
    return CompileProfile(
        name=f"mixed_stack_wave_{wave or 'unknown'}",
        commands=commands,
        description="; ".join(descriptions),
    )


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _path_parts_lower(path: Path) -> set[str]:
    return {part.lower() for part in path.parts}


def _discover_tsconfig_groups(root: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {
        "backend": [],
        "frontend": [],
        "generated": [],
        "shared": [],
        "other": [],
    }

    for tsconfig in _iter_paths(root, "tsconfig.json"):
        rel = tsconfig.relative_to(root)
        parts = _path_parts_lower(rel.parent)

        if tsconfig == root / "tsconfig.json":
            groups["other"].append(tsconfig)
            continue
        if parts & _GENERATED_PARTS:
            groups["generated"].append(tsconfig)
            continue
        if parts & _SHARED_PARTS:
            groups["shared"].append(tsconfig)
            continue
        if parts & _BACKEND_PARTS:
            groups["backend"].append(tsconfig)
            continue
        if parts & _FRONTEND_PARTS:
            groups["frontend"].append(tsconfig)
            continue
        groups["other"].append(tsconfig)

    for key in groups:
        groups[key] = _dedupe_paths(groups[key])
    return groups


def _get_typescript_profile(wave: str, template: str, root: Path) -> CompileProfile:
    """TypeScript compile profiles using ``tsc --noEmit``."""

    groups = _discover_tsconfig_groups(root)
    root_tsconfig = root / "tsconfig.json"

    selected: list[Path] = []
    description = ""
    profile_prefix = "typescript"

    if wave in {"A", "B"}:
        selected.extend(groups["backend"])
        if wave == "B":
            selected.extend(groups["shared"])
        description = f"Scoped backend compile after Wave {wave}"
        profile_prefix = "backend"
    elif wave in {"D", "D5"}:
        selected.extend(groups["frontend"])
        selected.extend(groups["generated"])
        selected.extend(groups["shared"])
        description = f"Scoped frontend/generated-client compile after Wave {wave}"
        profile_prefix = "frontend"
    elif wave in {"E", "T"}:
        # V18.2: Wave T runs after all code exists (same scope as Wave E).
        if root_tsconfig.is_file():
            return CompileProfile(
                name=f"typescript_full_workspace_wave_{wave}",
                commands=[["npx", "tsc", "--noEmit", "--pretty", "false"]],
                description=f"Full workspace compile in Wave {wave}",
            )
        selected.extend(groups["backend"])
        selected.extend(groups["frontend"])
        selected.extend(groups["generated"])
        selected.extend(groups["shared"])
        selected.extend(groups["other"])
        description = f"Full workspace compile in Wave {wave}"
        profile_prefix = "full_workspace"
    else:
        selected.extend(groups["backend"])
        selected.extend(groups["shared"])
        description = f"Fallback TypeScript compile for Wave {wave}"

    selected = _dedupe_paths(selected)
    if not selected and wave in {"A", "B"} and groups["other"] and not groups["frontend"]:
        selected.extend(groups["other"])
        selected = _dedupe_paths(selected)
    if not selected and wave in {"D", "D5"} and groups["other"] and not groups["backend"]:
        selected.extend(groups["other"])
        selected = _dedupe_paths(selected)
    if not selected and root_tsconfig.is_file():
        if wave in {"A", "B"} and groups["frontend"] and not groups["backend"] and not groups["shared"]:
            return CompileProfile(
                name="noop",
                commands=[],
                description="No scoped TypeScript backend compile target detected",
            )
        if wave in {"D", "D5"} and groups["backend"] and not groups["frontend"] and not groups["generated"]:
            return CompileProfile(
                name="noop",
                commands=[],
                description="No scoped TypeScript frontend compile target detected",
            )
        return CompileProfile(
            name=_profile_name("typescript_root", wave),
            commands=[["npx", "tsc", "--noEmit", "--pretty", "false"]],
            description=f"Root TypeScript compile fallback for Wave {wave}",
        )

    if not selected:
        return CompileProfile(name="noop", commands=[], description="No TypeScript compile target detected")

    commands = [
        ["npx", "tsc", "--noEmit", "--pretty", "false", "--project", str(path.resolve())]
        for path in selected
    ]
    return CompileProfile(
        name=_profile_name(profile_prefix, wave),
        commands=commands,
        description=description or f"TypeScript compile profile for template {template}",
    )


def _discover_pubspec_dirs(root: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {
        "backend": [],
        "frontend": [],
        "generated": [],
        "shared": [],
        "other": [],
    }

    for pubspec in _iter_paths(root, "pubspec.yaml"):
        directory = pubspec.parent
        rel = directory.relative_to(root)
        parts = _path_parts_lower(rel)

        if directory == root:
            groups["other"].append(directory)
            continue
        if parts & _GENERATED_PARTS:
            groups["generated"].append(directory)
            continue
        if parts & _SHARED_PARTS:
            groups["shared"].append(directory)
            continue
        if parts & _BACKEND_PARTS:
            groups["backend"].append(directory)
            continue
        if parts & _FRONTEND_PARTS:
            groups["frontend"].append(directory)
            continue
        groups["other"].append(directory)

    for key in groups:
        groups[key] = _dedupe_paths(groups[key])
    return groups


def _get_dart_profile(wave: str, template: str, root: Path) -> CompileProfile:
    """Dart compile profiles using ``dart analyze``."""

    groups = _discover_pubspec_dirs(root)
    selected: list[Path] = []
    description = ""

    if wave in {"A", "B"}:
        selected.extend(groups["backend"])
        if wave == "B":
            selected.extend(groups["shared"])
        description = f"Scoped Dart backend analysis after Wave {wave}"
    elif wave in {"D", "D5"}:
        selected.extend(groups["frontend"])
        selected.extend(groups["generated"])
        selected.extend(groups["shared"])
        description = f"Scoped Dart frontend/generated analysis after Wave {wave}"
    elif wave in {"E", "T"}:
        # V18.2: Wave T runs after all code exists (same scope as Wave E).
        if (root / "pubspec.yaml").is_file():
            return CompileProfile(
                name=f"dart_full_workspace_wave_{wave}",
                commands=[["dart", "analyze", str(root)]],
                description=f"Full workspace Dart analysis in Wave {wave}",
            )
        selected.extend(groups["backend"])
        selected.extend(groups["frontend"])
        selected.extend(groups["generated"])
        selected.extend(groups["shared"])
        selected.extend(groups["other"])
        description = f"Full workspace Dart analysis in Wave {wave}"
    else:
        selected.extend(groups["other"])
        description = f"Fallback Dart analysis for Wave {wave}"

    selected = _dedupe_paths(selected)
    if not selected and (root / "pubspec.yaml").is_file():
        if wave in {"A", "B"} and groups["frontend"] and not groups["backend"] and not groups["shared"]:
            return CompileProfile(
                name="noop",
                commands=[],
                description="No scoped Dart backend compile target detected",
            )
        if wave in {"D", "D5"} and groups["backend"] and not groups["frontend"] and not groups["generated"]:
            return CompileProfile(
                name="noop",
                commands=[],
                description="No scoped Dart frontend compile target detected",
            )
        return CompileProfile(
            name=_profile_name("dart_root", wave),
            commands=[["dart", "analyze", str(root)]],
            description=f"Root Dart analysis fallback for Wave {wave}",
        )
    if not selected:
        return CompileProfile(name="noop", commands=[], description="No Dart compile target detected")

    return CompileProfile(
        name=_profile_name("dart", wave),
        commands=[["dart", "analyze", str(path.resolve())] for path in selected],
        description=description or f"Dart compile profile for template {template}",
    )


def _discover_dotnet_groups(root: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {
        "backend": [],
        "frontend": [],
        "generated": [],
        "shared": [],
        "other": [],
    }

    for csproj in _iter_paths(root, "*.csproj"):
        rel = csproj.relative_to(root)
        parts = _path_parts_lower(rel.parent)

        if parts & _GENERATED_PARTS:
            groups["generated"].append(csproj)
            continue
        if parts & _SHARED_PARTS:
            groups["shared"].append(csproj)
            continue
        if parts & _BACKEND_PARTS:
            groups["backend"].append(csproj)
            continue
        if parts & _FRONTEND_PARTS or "blazor" in rel.as_posix().lower():
            groups["frontend"].append(csproj)
            continue
        groups["other"].append(csproj)

    for key in groups:
        groups[key] = _dedupe_paths(groups[key])
    return groups


def _get_dotnet_profile(wave: str, template: str, root: Path) -> CompileProfile:
    """Dotnet compile profiles using ``dotnet build --no-restore``."""

    groups = _discover_dotnet_groups(root)
    solutions = _dedupe_paths(_iter_paths(root, "*.sln"))
    selected: list[Path] = []
    description = ""

    if wave in {"A", "B"}:
        selected.extend(groups["backend"])
        if wave == "B":
            selected.extend(groups["shared"])
        description = f"Scoped dotnet backend build after Wave {wave}"
    elif wave in {"D", "D5"}:
        selected.extend(groups["frontend"])
        selected.extend(groups["generated"])
        selected.extend(groups["shared"])
        description = f"Scoped dotnet frontend/generated build after Wave {wave}"
    elif wave in {"E", "T"}:
        # V18.2: Wave T runs after all code exists (same scope as Wave E).
        if solutions:
            return CompileProfile(
                name=f"dotnet_full_workspace_wave_{wave}",
                commands=[["dotnet", "build", str(solutions[0].resolve()), "--no-restore", "-nologo"]],
                description=f"Full workspace dotnet build in Wave {wave}",
            )
        selected.extend(groups["backend"])
        selected.extend(groups["frontend"])
        selected.extend(groups["generated"])
        selected.extend(groups["shared"])
        selected.extend(groups["other"])
        description = f"Full workspace dotnet build in Wave {wave}"
    else:
        selected.extend(groups["backend"])
        selected.extend(groups["shared"])
        description = f"Fallback dotnet build for Wave {wave}"

    selected = _dedupe_paths(selected)
    if not selected:
        if wave in {"D", "D5"} and not groups["frontend"] and not groups["generated"] and not groups["shared"]:
            return CompileProfile(
                name="noop",
                commands=[],
                description="No scoped dotnet frontend compile target detected",
            )
        if solutions:
            return CompileProfile(
                name=_profile_name("solution", wave),
                commands=[["dotnet", "build", str(solutions[0].resolve()), "--no-restore", "-nologo"]],
                description=f"Solution-level dotnet build fallback for Wave {wave}",
            )
        selected = _dedupe_paths(groups["other"])
    if not selected:
        return CompileProfile(name="noop", commands=[], description="No dotnet compile target detected")

    return CompileProfile(
        name=_profile_name("dotnet", wave),
        commands=[["dotnet", "build", str(path.resolve()), "--no-restore", "-nologo"] for path in selected],
        description=description or f"Dotnet compile profile for template {template}",
    )


# Per-schema prisma-generate timeout. Cold first-run can take 30-90s
# while the engine binary is materialised; aligns with the per-tsc 120s
# discipline already used by ``_run_command``. When prisma exceeds this,
# we surface a structured TIMEOUT error rather than blocking the gate.
_PRISMA_GENERATE_TIMEOUT_S = 120

# Stderr truncation for the synthesised PRISMA_GENERATE_FAILED message —
# enough to land the actual schema error in the operator-facing summary,
# bounded so the retry payload stays under its 12 KB ceiling.
_PRISMA_STDERR_MAX_CHARS = 800


def _discover_prisma_schemas(root: Path) -> list[Path]:
    """Locate ``schema.prisma`` files under *root*.

    Honours the shared ``_SKIP_DIRS`` (so ``node_modules/`` /
    ``.git/`` etc. are pruned at descent — a Prisma client install
    ships its own example schemas under
    ``node_modules/@prisma/engines-tests``, and matching them would
    explode the generate budget). Returns deduped absolute paths.
    """
    return _dedupe_paths(_iter_paths(root, "schema.prisma"))


def _detect_package_manager(root: Path) -> str:
    """Detect the workspace package manager at *root*.

    Returns one of ``"pnpm"``, ``"yarn"``, ``"npm"``, or ``""`` (no
    evidence — caller falls back to the historical npx-from-grandparent
    behaviour, which preserves the existing test fixtures that don't
    carry a lockfile).

    Detection precedence (operator-pinned in the dispatch prompt):

    1. **``packageManager`` field in root ``package.json``** — the
       Corepack-canonical declaration. ``"pnpm@9.x"`` → pnpm,
       ``"yarn@4.x"`` → yarn, ``"npm@10.x"`` → npm. This is what the
       scaffold writes (see ``scaffold_runner.py`` line ~1466 emitting
       ``_SCAFFOLD_PNPM_PACKAGE_MANAGER``) and is the strongest signal.
    2. **Lockfile presence at root** — ``pnpm-lock.yaml`` → pnpm;
       ``yarn.lock`` → yarn; ``package-lock.json`` → npm. Robust on
       in-progress scaffolds where ``packageManager`` may be missing
       but ``pnpm install`` has already materialised the lockfile.
    3. **Fallback ``""``** — no evidence; caller uses the historical
       ``npx`` shape from the schema's grandparent. Preserves existing
       test fixtures that don't carry a lockfile.

    Note: Phase 5 closeout fix #2 deliberately does NOT probe
    ``node_modules/.pnpm/`` to infer pnpm. That heuristic could
    misclassify a partially-installed npm tree; the lockfile/manifest
    signals above are unambiguous.
    """
    package_json = root / "package.json"
    if package_json.is_file():
        try:
            text = package_json.read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            pm_field = data.get("packageManager")
            if isinstance(pm_field, str):
                pm_lower = pm_field.strip().lower()
                if pm_lower.startswith("pnpm"):
                    return "pnpm"
                if pm_lower.startswith("yarn"):
                    return "yarn"
                if pm_lower.startswith("npm"):
                    return "npm"

    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    if (root / "package-lock.json").is_file():
        return "npm"

    return ""


def _read_workspace_name(package_json: Path) -> str:
    """Return the ``name`` field from a workspace ``package.json``, or "".

    Used by :func:`_resolve_pnpm_workspace_for_schema` to derive the
    ``--filter`` argument for pnpm. When the file is missing or
    malformed, returns ``""`` so the caller can fall back to the
    workspace-less ``pnpm exec`` shape.
    """
    try:
        text = package_json.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError):
        return ""
    if isinstance(data, dict):
        name = data.get("name")
        if isinstance(name, str):
            return name.strip()
    return ""


def _resolve_pnpm_workspace_for_schema(
    root: Path, schema: Path
) -> tuple[Path | None, str]:
    """Resolve the workspace package directory that owns *schema* (or has prisma).

    Mirrors the canonical Docker pattern at
    ``src/agent_team_v15/templates/pnpm_monorepo/apps/api/Dockerfile:49``::

        RUN pnpm --filter {{ API_SERVICE_NAME }} exec sh -c \
            '[ -f prisma/schema.prisma ] && pnpm exec prisma generate || true'

    Resolution algorithm (operator-pinned):

    1. **Walk up from the schema's directory** to *root*, picking the
       first ancestor that has a ``node_modules/.bin/prisma`` shim.
       This handles the canonical scaffold layout
       ``apps/api/prisma/schema.prisma`` → workspace = ``apps/api``.
    2. **Scan ``apps/*/node_modules/.bin/prisma``** then
       ``packages/*/node_modules/.bin/prisma``. Picks the first match.
       Handles a root-level ``prisma/schema.prisma`` (the failing
       artifact from rerun3) where the binary lives at
       ``apps/api/node_modules/.bin/prisma``.
    3. **Schema's grandparent** as a final structural guess (the package
       root that owns ``prisma/`` per the canonical layout). Returned
       even without ``.bin/prisma`` so ``pnpm`` itself can resolve the
       binary via the corepack/global pnpm install path — this is what
       the Docker pattern at line 49 does (``pnpm exec`` from the
       workspace root, NOT from a directory verified to have
       ``.bin/prisma``).

    Returns ``(workspace_dir | None, workspace_name)``. ``workspace_name``
    is the ``name`` field from ``<workspace>/package.json`` when
    present (drives ``pnpm --filter <name>``); empty string when the
    package.json is missing/malformed (caller falls back to
    ``pnpm exec`` without ``--filter``).
    """
    try:
        schema_resolved = schema.resolve()
        root_resolved = root.resolve()
    except OSError:
        return None, ""

    # (1) Walk up from schema dir to root.
    cursor = schema_resolved.parent
    while True:
        candidate = cursor / "node_modules" / ".bin" / "prisma"
        if candidate.exists():
            return cursor, _read_workspace_name(cursor / "package.json")
        if cursor == root_resolved or cursor == cursor.parent:
            break
        cursor = cursor.parent

    # (2) Scan apps/* then packages/* under root.
    for parent_name in ("apps", "packages"):
        parent_dir = root_resolved / parent_name
        if not parent_dir.is_dir():
            continue
        try:
            children = sorted(p for p in parent_dir.iterdir() if p.is_dir())
        except OSError:
            continue
        for child in children:
            candidate = child / "node_modules" / ".bin" / "prisma"
            if candidate.exists():
                return child, _read_workspace_name(child / "package.json")

    # (3) Schema's grandparent as a structural fallback. ``pnpm exec``
    # from there can still resolve a globally-installed prisma binary,
    # mirroring the Docker pattern (which never verifies ``.bin/prisma``
    # before invoking ``pnpm exec``).
    grandparent = schema_resolved.parent.parent
    if grandparent.is_dir():
        return grandparent, _read_workspace_name(grandparent / "package.json")

    return None, ""


def _build_prisma_generate_command(
    root: Path, schema: Path
) -> tuple[list[str], Path, str]:
    """Build the package-manager-aware ``prisma generate`` command.

    Returns ``(argv, cwd, pm_label)`` where:

    * ``argv`` is the spawn vector for :func:`_run_command`.
    * ``cwd`` is the directory the command runs from.
    * ``pm_label`` is the package-manager front binary (``"pnpm"`` /
      ``"yarn"`` / ``"npx"``) — used in the ``MISSING_COMMAND`` message
      so operators see *which* binary was missing.

    Behaviour by package manager (operator-pinned in the dispatch
    prompt; mirrors the Docker patterns at
    ``templates/pnpm_monorepo/apps/api/Dockerfile`` lines 44-50):

    * **pnpm** — workspace-aware. Prefers
      ``pnpm --filter <name> exec prisma generate --schema <abs>`` from
      *root* when the workspace-name is known (matches the canonical
      Docker shape at line 49). Falls back to
      ``pnpm exec prisma generate --schema <abs>`` from the resolved
      workspace root when the name is missing. This avoids fighting
      pnpm's per-package ``node_modules/.bin/`` isolation: a bare
      ``npx`` from the monorepo root would NOT find the prisma shim
      that lives under ``apps/api/node_modules/.bin/prisma``.
    * **yarn** — ``yarn exec prisma generate --schema <abs>`` from the
      resolved workspace root (yarn workspaces also isolate per-package
      ``.bin``; same rationale as pnpm).
    * **npm** and **fallback (no PM detected)** — ``npx prisma
      generate --schema <abs>`` from the schema's grandparent. Preserves
      the pre-fix shape so existing tests/fixtures without a lockfile
      keep working byte-identically.

    Note: the dispatch prompt forbids a silent ``npx`` fallback when
    pnpm is detected. The pnpm branch ALWAYS produces a ``pnpm``-prefixed
    spawn — it never silently downgrades to npx.
    """
    pm = _detect_package_manager(root)

    if pm == "pnpm":
        try:
            schema_resolved = schema.resolve()
        except OSError:
            schema_resolved = schema
        workspace_dir, workspace_name = _resolve_pnpm_workspace_for_schema(
            root, schema_resolved
        )
        if workspace_name:
            # Canonical Docker shape — `pnpm --filter <name> exec ...`
            # from the monorepo root. pnpm itself dispatches into the
            # named workspace's `node_modules/.bin/`.
            argv = [
                "pnpm",
                "--filter",
                workspace_name,
                "exec",
                "prisma",
                "generate",
                "--schema",
                str(schema_resolved),
            ]
            return argv, root, "pnpm"
        # Workspace name unknown — run `pnpm exec` from the workspace
        # directory we resolved (or schema grandparent fallback). pnpm
        # exec walks up to find the nearest .bin/prisma.
        cwd = workspace_dir if workspace_dir is not None else root
        argv = [
            "pnpm",
            "exec",
            "prisma",
            "generate",
            "--schema",
            str(schema_resolved),
        ]
        return argv, cwd, "pnpm"

    if pm == "yarn":
        try:
            schema_resolved = schema.resolve()
        except OSError:
            schema_resolved = schema
        workspace_dir, _workspace_name = _resolve_pnpm_workspace_for_schema(
            root, schema_resolved
        )
        cwd = workspace_dir if workspace_dir is not None else root
        argv = [
            "yarn",
            "exec",
            "prisma",
            "generate",
            "--schema",
            str(schema_resolved),
        ]
        return argv, cwd, "yarn"

    # npm or no PM detected — preserve the pre-fix `npx` from
    # grandparent shape. This is the path the existing 17 test
    # fixtures (none of which carry a lockfile) traverse.
    package_root = schema.parent.parent
    cwd_for_generate = package_root if package_root.is_dir() else root
    argv = ["npx", "prisma", "generate", "--schema", str(schema)]
    return argv, cwd_for_generate, "npx"


async def _run_prisma_generate_if_needed(
    root: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Run ``prisma generate --schema <abs>`` for every detected schema.

    Spawn shape is package-manager-aware (see
    :func:`_build_prisma_generate_command` for the per-PM matrix). The
    canonical Docker pattern at
    ``templates/pnpm_monorepo/apps/api/Dockerfile:49`` uses
    ``pnpm --filter <api-pkg> exec ... pnpm exec prisma generate``;
    this host pre-step mirrors that for pnpm projects so the 5.6c
    strict-compile profile doesn't regress against the workspace
    isolation pnpm enforces (per-package ``node_modules/.bin/``,
    nothing hoisted to root). For npm / no-lockfile cases the
    historical ``npx prisma generate`` shape is preserved.

    Returns a ``(errors, raw_outputs)`` tuple:

    * ``errors`` is empty when no schema is present (no-op contract per
      the dispatch prompt) or every generate command exited cleanly.
      Otherwise each entry is a structured error dict mirroring the
      ``CompileResult.errors`` shape used by the rest of this module:

        - ``MISSING_COMMAND`` when the package-manager front binary
          (``pnpm`` / ``yarn`` / ``npx``) is not on PATH (env-blocked;
          ``is_compile_env_unavailable`` continues to classify the
          overall result as env-unavailable so existing
          ``tsc_env_unavailable`` semantics are preserved).
        - ``TIMEOUT`` when a generate exceeds
          ``_PRISMA_GENERATE_TIMEOUT_S`` (120s; matches the per-tsc
          120s discipline).
        - ``PRISMA_GENERATE_FAILED`` for any other non-zero exit; the
          message carries up to ``_PRISMA_STDERR_MAX_CHARS`` of
          truncated stderr so the operator-facing summary names the
          actual schema problem.

    * ``raw_outputs`` collects each generate command's combined
      stdout+stderr so the eventual ``CompileResult.raw_output`` keeps
      a verbatim audit trail of the pre-step (matters for retry-payload
      construction in :mod:`agent_team_v15.retry_feedback`).

    Idempotency: ``prisma generate`` itself is idempotent — it
    overwrites ``node_modules/.prisma/client/`` from the schema. No
    separate idempotency layer is needed here.
    """
    schemas = _discover_prisma_schemas(root)
    if not schemas:
        return [], []

    errors: list[dict[str, Any]] = []
    outputs: list[str] = []

    for schema in schemas:
        cmd, cwd_for_generate, pm_label = _build_prisma_generate_command(
            root, schema
        )
        try:
            returncode, combined = await _run_command(
                cmd,
                cwd_for_generate,
                timeout=_PRISMA_GENERATE_TIMEOUT_S,
                extra_env={"PRISMA_GENERATE_SKIP_AUTOINSTALL": "true"},
            )
        except asyncio.TimeoutError:
            message = (
                f"prisma generate timed out after "
                f"{_PRISMA_GENERATE_TIMEOUT_S}s for schema {schema}"
            )
            errors.append(
                {
                    "file": str(schema),
                    "line": 0,
                    "code": "TIMEOUT",
                    "message": message,
                }
            )
            outputs.append(message)
            continue
        except FileNotFoundError:
            # Package-manager front binary not on PATH — env-blocked.
            # ``is_compile_env_unavailable`` already includes
            # ``MISSING_COMMAND`` in its env-unavailability set, so this
            # preserves the pre-Phase-5-closeout
            # ``tsc_env_unavailable=True`` semantics rather than promoting
            # a missing toolchain to a wave failure.
            message = (
                f"Command not found: {pm_label} (prisma generate pre-step)"
            )
            errors.append(
                {
                    "file": str(schema),
                    "line": 0,
                    "code": "MISSING_COMMAND",
                    "message": message,
                }
            )
            outputs.append(message)
            continue

        outputs.append(combined)
        if returncode == 0:
            continue

        # Real prisma failure — bad schema, missing engine, etc. Truncate
        # the stderr/stdout blob so the operator-facing summary stays
        # bounded but still names the actual schema diagnostic.
        truncated = (combined or "").strip()
        if len(truncated) > _PRISMA_STDERR_MAX_CHARS:
            truncated = (
                truncated[:_PRISMA_STDERR_MAX_CHARS] + "\n…(truncated)"
            )
        message = (
            f"prisma generate failed (exit {returncode}) for schema "
            f"{schema}: {truncated}".rstrip(": ").rstrip()
        )
        errors.append(
            {
                "file": str(schema),
                "line": 0,
                "code": "PRISMA_GENERATE_FAILED",
                "message": message,
            }
        )

    return errors, outputs


async def run_wave_compile_check(
    cwd: str,
    profile: CompileProfile | None = None,
    *,
    wave: str = "",
    template: str = "",
    config: Any | None = None,
    milestone: Any | None = None,
    project_root: Path | None = None,
    stack_target: str = "",
) -> CompileResult:
    """Execute wave compile commands and parse structured errors.

    The optional keyword arguments keep this function compatible with both:
    - the Phase 2 implementation prompt (`cwd`, `profile`)
    - the current `wave_executor.py` callback shape (`cwd`, `wave`, `template`, ...)
    """

    del config  # Reserved for later phases; unused in Phase 2B.

    root = Path(project_root or cwd)
    if profile is None:
        resolved_stack = stack_target or getattr(milestone, "stack_target", "")
        profile = get_compile_profile(wave, template, resolved_stack, root)

    if not profile.commands:
        return CompileResult(passed=True, raw_output="")

    # Phase 5 closeout — Prisma generate parity gap with 5.6b Docker path.
    #
    # The 5.6b Docker compose path (apps/api/Dockerfile) runs
    # ``prisma generate`` before ``tsc`` so ``node_modules/.prisma/client/``
    # is materialised before the compiler sees ``import { PrismaClient }
    # from '@prisma/client'`` (the re-export stub points at
    # ``.prisma/client/default``). The 5.6c host strict-compile profile
    # historically ran ``npx tsc --noEmit --project ...`` directly, with
    # no Prisma pre-step, so a clean smoke surface looked like:
    #
    #   src/database/prisma.service.ts:2 TS2305 Module '"@prisma/client"'
    #     has no exported member 'PrismaClient'.
    #   src/database/prisma.service.ts:10 TS2339 Property '$connect' does
    #     not exist on type 'PrismaService'.
    #
    # 5.6b on the same artifact passed cleanly. The asymmetry is the
    # signal: not bad Codex output, but a missing builder pre-step on
    # the host strict-compile path. See
    # ``v18 test runs/phase-5-8a-stage-2b-rerun3-clean-20260501-231647-daa0e90-01-20260501-231704/``
    # for the canonical evidence (BUILD_LOG line ~512 + new
    # wave_B_self_verify_error.txt artifact).
    #
    # When ``prisma generate`` itself fails (real schema error), we
    # surface a synthesised ``PRISMA_GENERATE_FAILED`` error in the
    # CompileResult and SKIP the tsc commands — without the generated
    # client they would all cascade with the same TS2305 noise, drowning
    # the real diagnostic. Env-unavailability (missing ``npx`` /
    # ``MISSING_COMMAND``) flows through verbatim so
    # :func:`unified_build_gate.is_compile_env_unavailable` still classifies
    # it as ``tsc_env_unavailable`` rather than a wave failure.
    prisma_errors, prisma_outputs = await _run_prisma_generate_if_needed(root)
    if prisma_errors:
        return CompileResult(
            passed=False,
            error_count=len(prisma_errors),
            errors=prisma_errors,
            raw_output="\n".join(part for part in prisma_outputs if part),
        )

    all_errors: list[dict[str, Any]] = []
    raw_outputs: list[str] = list(prisma_outputs)

    for cmd in profile.commands:
        try:
            # When --project points to a sub-directory tsconfig, run npx
            # from that directory so it finds node_modules/.bin/tsc there
            # instead of failing at the monorepo root.
            cmd_cwd = Path(cwd)
            if "--project" in cmd:
                proj_idx = cmd.index("--project")
                if proj_idx + 1 < len(cmd):
                    tsconfig_path = Path(cwd) / cmd[proj_idx + 1]
                    tsconfig_dir = tsconfig_path.parent if tsconfig_path.is_file() else tsconfig_path
                    if tsconfig_dir.is_dir():
                        cmd_cwd = tsconfig_dir
                        cmd = [c for i, c in enumerate(cmd) if i not in (proj_idx, proj_idx + 1)]
            returncode, combined = await _run_command(cmd, cmd_cwd)
            raw_outputs.append(combined)
            if returncode == 0:
                continue

            # Defensive: catch the Windows App Execution Alias placeholder
            # BEFORE the tsc-error parser runs. Without this, the fix
            # loop burns iterations trying to "repair" Wave B source for
            # a failure that lives in the compile harness environment
            # (TypeScript not installed locally). The dedicated
            # ENV_NOT_READY code tells the agent (and the log reader)
            # exactly what happened so the right fix can be applied
            # out-of-loop — typically running ``pnpm install`` to
            # populate ``node_modules/``.
            if _WINDOWS_AEP_SENTINEL_RE.search(combined):
                all_errors.append({
                    "file": "",
                    "line": 0,
                    "code": "ENV_NOT_READY",
                    "message": (
                        "TypeScript is not installed locally — ``npx tsc`` "
                        "hit the Windows App Execution Alias placeholder. "
                        "Run ``pnpm install`` (or ``npm install``) to "
                        "populate ``node_modules/`` before compile-check."
                    ),
                })
                continue

            parsed_errors = _parse_profile_errors(profile, combined, cmd)
            if not parsed_errors:
                parsed_errors = [_fallback_error(cmd, combined)]
            all_errors.extend(parsed_errors)
        except asyncio.TimeoutError:
            message = f"Compile timed out after 120s: {' '.join(cmd)}"
            all_errors.append({"file": "", "line": 0, "code": "TIMEOUT", "message": message})
            raw_outputs.append(message)
        except FileNotFoundError:
            message = f"Command not found: {cmd[0]}"
            all_errors.append({"file": "", "line": 0, "code": "MISSING_COMMAND", "message": message})
            raw_outputs.append(message)

    all_errors = _dedupe_errors(all_errors)
    return CompileResult(
        passed=not all_errors,
        error_count=len(all_errors),
        errors=all_errors,
        raw_output="\n".join(part for part in raw_outputs if part),
    )


def _resolve_command(cmd: list[str]) -> list[str]:
    exe = cmd[0]
    resolved = shutil.which(exe)
    if resolved:
        return [resolved] + cmd[1:]

    if sys.platform == "win32":
        resolved = shutil.which(f"{exe}.cmd")
        if resolved:
            return [resolved] + cmd[1:]

    return cmd


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


async def _run_command(
    cmd: list[str],
    cwd: Path,
    timeout: int = 120,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str]:
    resolved = _resolve_command(cmd)
    env = {
        **os.environ,
        "NO_COLOR": "1",
        "FORCE_COLOR": "0",
        **(extra_env or {}),
    }
    process = await create_subprocess_exec_compat(
        *resolved,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    output = (stdout or b"").decode("utf-8", errors="replace")
    err_output = (stderr or b"").decode("utf-8", errors="replace")
    combined = "\n".join(part for part in (output, err_output) if part).strip()
    # Strip ANSI escape codes that leak through on Windows even with --pretty false
    combined = _ANSI_RE.sub("", combined)
    return (process.returncode or 0, combined)


def _parse_profile_errors(
    profile: CompileProfile,
    output: str,
    command: list[str] | None = None,
) -> list[dict[str, Any]]:
    profile_name = profile.name.lower()
    command_text = " ".join((command or [])).lower()
    if "dotnet" in profile_name or "solution" in profile_name or "dotnet " in command_text:
        errors = _parse_dotnet_errors(output)
        return errors or _parse_tsc_errors(output)
    if "dart" in profile_name or "dart analyze" in command_text:
        return _parse_dart_errors(output)
    return _parse_tsc_errors(output)


def _parse_tsc_errors(output: str) -> list[dict[str, Any]]:
    """Parse TypeScript compiler errors into structured dicts."""

    errors: list[dict[str, Any]] = []
    patterns = (
        re.compile(
            r"^(?P<file>.+?)\((?P<line>\d+),(?P<column>\d+)\):\s*error\s+"
            r"(?P<code>TS\d+):\s*(?P<message>.+)$",
            re.MULTILINE,
        ),
        re.compile(
            r"^(?P<file>.+?):(?P<line>\d+):(?P<column>\d+)\s*-\s*error\s+"
            r"(?P<code>TS\d+):\s*(?P<message>.+)$",
            re.MULTILINE,
        ),
    )

    for pattern in patterns:
        for match in pattern.finditer(output):
            errors.append(
                {
                    "file": match.group("file").strip(),
                    "line": int(match.group("line")),
                    "column": int(match.group("column")),
                    "code": match.group("code"),
                    "message": match.group("message").strip(),
                }
            )

    return _dedupe_errors(errors)


def _parse_dart_errors(output: str) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    patterns = (
        re.compile(
            r"^(?:error|warning)\s*-\s*(?P<message>.+?)\s*-\s*(?P<file>.+?):"
            r"(?P<line>\d+):(?P<column>\d+)\s*-\s*(?P<code>[\w.]+)$",
            re.MULTILINE,
        ),
        re.compile(
            r"^(?P<file>.+?):(?P<line>\d+):(?P<column>\d+):\s*Error:\s*(?P<message>.+)$",
            re.MULTILINE,
        ),
    )

    for pattern in patterns:
        for match in pattern.finditer(output):
            errors.append(
                {
                    "file": match.group("file").strip(),
                    "line": int(match.group("line")),
                    "column": int(match.group("column")),
                    "code": match.groupdict().get("code", "dart"),
                    "message": match.group("message").strip(),
                }
            )

    return _dedupe_errors(errors)


def _parse_dotnet_errors(output: str) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    pattern = re.compile(
        r"^(?P<file>.+?)\((?P<line>\d+),(?P<column>\d+)\):\s*error\s+"
        r"(?P<code>[A-Z]{2,}\d+):\s*(?P<message>.+?)(?:\s+\[.+\])?$",
        re.MULTILINE,
    )

    for match in pattern.finditer(output):
        errors.append(
            {
                "file": match.group("file").strip(),
                "line": int(match.group("line")),
                "column": int(match.group("column")),
                "code": match.group("code"),
                "message": match.group("message").strip(),
            }
        )

    return _dedupe_errors(errors)


def _fallback_error(cmd: list[str], output: str) -> dict[str, Any]:
    message = ""
    for line in output.splitlines():
        stripped = line.strip()
        if stripped:
            message = stripped
            break
    if not message:
        message = f"Compile failed for command: {' '.join(cmd)}"
    return {"file": "", "line": 0, "code": "", "message": message}


def _dedupe_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int, str, str]] = set()
    for error in errors:
        key = (
            str(error.get("file", "")),
            int(error.get("line", 0) or 0),
            int(error.get("column", 0) or 0),
            str(error.get("code", "")),
            str(error.get("message", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(error)
    return deduped


def format_compile_errors_for_prompt(errors: list[dict[str, Any]], max_errors: int = 20) -> str:
    """Format compile errors for injection into a fix sub-agent prompt."""

    if not errors:
        return ""

    shown = min(len(errors), max_errors)
    lines = [f"[COMPILE ERRORS - {len(errors)} total, showing first {shown}]", ""]
    for error in errors[:max_errors]:
        file_path = error.get("file") or "?"
        line = error.get("line", "?")
        column = error.get("column")
        code = error.get("code", "")
        location = f"{file_path}:{line}"
        if isinstance(column, int) and column > 0:
            location = f"{location}:{column}"
        suffix = f" {code}" if code else ""
        lines.append(f"- {location}{suffix} {error.get('message', '?')}".rstrip())

    if len(errors) > max_errors:
        lines.append(f"- ... and {len(errors) - max_errors} more errors")

    lines.extend(
        [
            "",
            "Fix ALL compile errors. Read each file before editing.",
            "Do NOT delete code to silence the compiler.",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "CompileCheckResult",
    "CompileProfile",
    "CompileResult",
    "format_compile_errors_for_prompt",
    "get_compile_profile",
    "run_wave_compile_check",
    "_PRISMA_GENERATE_TIMEOUT_S",
    "_discover_prisma_schemas",
    "_get_compile_profile",
    "_parse_tsc_errors",
    "_run_prisma_generate_if_needed",
]
