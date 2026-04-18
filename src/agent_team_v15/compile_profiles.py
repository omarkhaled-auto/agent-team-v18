"""Wave-specific compile profiles for scoped inter-wave verification.

The wave engine should not compile the full workspace after every wave.
This module resolves the smallest useful compile target per wave and stack,
executes those commands, and returns structured compiler errors for fix prompts.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    paths: list[Path] = []
    for path in root.rglob(pattern):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        paths.append(path)
    return paths


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

    all_errors: list[dict[str, Any]] = []
    raw_outputs: list[str] = []

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


async def _run_command(cmd: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str]:
    resolved = _resolve_command(cmd)
    env = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0"}
    process = await asyncio.create_subprocess_exec(
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
    "_get_compile_profile",
    "_parse_tsc_errors",
]
