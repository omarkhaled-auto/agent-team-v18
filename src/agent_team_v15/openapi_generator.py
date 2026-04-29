"""OpenAPI contract generation and client packaging for Wave C.

This module is intentionally standalone from the wave executor. It owns:

1. OpenAPI spec generation
2. Milestone-local scoping from Wave B module artifacts
3. Cumulative-vs-previous diffing for breaking changes
4. Client generation from the cumulative spec
5. Degraded regex extraction artifacts when canonical generation is unavailable

Phase 2 scope only:
- No live endpoint probing
- No Docker startup
- No evidence gating
- No Phase 3/4 runtime behavior
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")
_SCRIPT_CANDIDATES = (
    "scripts/generate-openapi.ts",
    "scripts/generate-openapi.js",
    "scripts/generate-openapi.mjs",
)


@dataclass
class ContractResult:
    """Wave C contract generation result."""

    success: bool = True
    milestone_spec_path: str = ""
    cumulative_spec_path: str = ""
    client_exports: list[str] = field(default_factory=list)
    client_manifest: list[dict[str, Any]] = field(default_factory=list)
    breaking_changes: list[str] = field(default_factory=list)
    endpoints_summary: list[dict[str, Any]] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    error_message: str = ""
    contract_source: str = ""
    contract_fidelity: str = ""
    degradation_reason: str = ""
    client_generator: str = ""
    client_fidelity: str = ""
    client_degradation_reason: str = ""
    # Phase 5.8a §K.1 — advisory cross-package diagnostic. Populated when
    # ``_generate_client_package`` succeeds (canonical openapi-ts path)
    # and ``cross_package_diagnostic.compute_divergences`` runs cleanly.
    # Each entry is a finding-dict consumed by
    # ``wave_executor._execute_wave_c`` to emit a ``WaveFinding`` and to
    # write ``PHASE_5_8A_DIAGNOSTIC.json``. Crash-isolated: any diagnostic
    # exception leaves these fields empty + does NOT fail Wave C.
    diagnostic_findings: list[dict[str, Any]] = field(default_factory=list)
    diagnostic_metrics: dict[str, Any] = field(default_factory=dict)
    diagnostic_tooling: dict[str, Any] = field(default_factory=dict)
    diagnostic_unsupported_polymorphic_schemas: list[str] = field(
        default_factory=list,
    )


def generate_openapi_contracts(cwd: str, milestone: Any) -> ContractResult:
    """Generate milestone-local and cumulative OpenAPI artifacts for Wave C."""

    result = ContractResult()
    project_root = Path(cwd)
    contracts_dir = project_root / "contracts" / "openapi"
    contracts_dir.mkdir(parents=True, exist_ok=True)

    spec_result = _generate_openapi_specs(project_root, milestone, contracts_dir)
    if not spec_result.get("success"):
        degradation_reason = str(spec_result.get("error", "OpenAPI generation failed"))
        logger.warning(
            "OpenAPI script generation unavailable for %s: %s. Writing degraded regex artifacts and failing Wave C.",
            getattr(milestone, "id", ""),
            degradation_reason,
        )
        canonical_error = (
            f"Canonical OpenAPI generation failed; regex extraction is degraded "
            f"and cannot feed Wave D: {degradation_reason}"
        )
        result.error_message = canonical_error
        result.contract_source = "regex-extraction"
        result.contract_fidelity = "degraded"
        result.degradation_reason = degradation_reason
        degraded_result = _fallback_to_regex_extraction(cwd, milestone, result)
        degraded_result.success = False
        degraded_result.error_message = canonical_error
        degraded_result.contract_source = "regex-extraction"
        degraded_result.contract_fidelity = "degraded"
        degraded_result.degradation_reason = degradation_reason
        return degraded_result

    result.milestone_spec_path = str(spec_result.get("milestone_spec_path", "") or "")
    result.cumulative_spec_path = str(spec_result.get("cumulative_spec_path", "") or "")
    result.files_created.extend(list(spec_result.get("files", []) or []))
    result.contract_source = "openapi-script"
    result.contract_fidelity = "canonical"

    validation_errors = _validate_cumulative_spec(
        Path(result.cumulative_spec_path) if result.cumulative_spec_path else contracts_dir / "current.json"
    )
    if validation_errors:
        result.success = False
        result.error_message = "; ".join(validation_errors)
        result.endpoints_summary = _extract_endpoints_from_spec(contracts_dir / "current.json")
        result.files_created = sorted({path for path in result.files_created if path})
        return result

    result.breaking_changes = _diff_cumulative_specs(contracts_dir)

    cumulative_spec = (
        Path(result.cumulative_spec_path)
        if result.cumulative_spec_path
        else contracts_dir / "current.json"
    )
    client_result = _generate_client_package(project_root, cumulative_spec)
    result.client_exports = list(client_result.get("exports", []) or [])
    result.client_manifest = list(client_result.get("manifest", []) or [])
    result.client_generator = str(client_result.get("generator", "") or "")
    result.client_fidelity = str(client_result.get("fidelity", "") or "")
    result.client_degradation_reason = str(client_result.get("degradation_reason", "") or "")
    result.files_created.extend(list(client_result.get("files", []) or []))

    if not client_result.get("success", True):
        result.success = False
        result.error_message = str(client_result.get("error", "Client generation failed"))
    elif result.client_fidelity.lower() == "degraded":
        result.success = False
        reason = result.client_degradation_reason or "typed client generator fell back to minimal output"
        result.error_message = (
            f"Generated client fidelity is degraded and cannot feed Wave D: {reason}"
        )

    summary_spec = _summary_spec_path(result, contracts_dir)
    result.endpoints_summary = _extract_endpoints_from_spec(summary_spec)
    _run_regex_crosscheck(project_root, milestone, result)

    if result.success and not cumulative_spec.exists():
        result.success = False
        result.error_message = "Cumulative spec not generated"

    # Phase 5.8a §K.1 — advisory cross-package diagnostic. Runs only on the
    # canonical openapi-ts client path (``client_generator == "openapi-ts"``)
    # since the minimal-ts fallback emits a different shape that the
    # OpenAPI-vs-TS diagnostic was not designed to compare. Crash-isolated:
    # any diagnostic exception is logged but never fails Wave C (per scope
    # check-in Q2 — no kill switch needed because the diagnostic is
    # timeout-bounded, crash-isolated, and cannot fail Wave C).
    if result.success and (
        str(result.client_generator or "").lower() == "openapi-ts"
    ):
        try:
            from .cross_package_diagnostic import (
                compute_divergences,
                divergences_to_finding_dicts,
            )

            client_dir = project_root / "packages" / "api-client"
            diagnostic_outcome = compute_divergences(
                spec_path=cumulative_spec,
                client_dir=client_dir,
                project_root=project_root,
            )
            result.diagnostic_findings = divergences_to_finding_dicts(
                diagnostic_outcome,
            )
            result.diagnostic_metrics = dict(diagnostic_outcome.metrics)
            result.diagnostic_tooling = dict(diagnostic_outcome.tooling)
            result.diagnostic_unsupported_polymorphic_schemas = list(
                diagnostic_outcome.unsupported_polymorphic_schemas,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Phase 5.8a diagnostic crashed for milestone %s: %s; Wave C continues unaffected",
                getattr(milestone, "id", ""),
                exc,
            )
            result.diagnostic_findings = []
            result.diagnostic_metrics = {
                "schemas_in_spec": 0,
                "exports_in_client": 0,
                "divergences_detected_total": 0,
                "unique_divergence_classes": [],
            }
            result.diagnostic_tooling = {
                "ts_parser": "unavailable",
                "ts_parser_version": "",
                "error": f"diagnostic_crashed: {exc}",
            }
            result.diagnostic_unsupported_polymorphic_schemas = []

    result.files_created = sorted({path for path in result.files_created if path})
    return result


def _generate_openapi_specs(
    project_root: Path,
    milestone: Any,
    contracts_dir: Path,
) -> dict[str, Any]:
    """Prefer the project-level script; callers decide how to handle failures."""

    script_path = _find_generation_script(project_root)
    if script_path is None:
        return {"success": False, "error": "generate-openapi script not found"}

    # Prisma's @prisma/client is a stub until `prisma generate` writes the
    # runtime/types from schema.prisma. The NestJS app imports PrismaClient
    # at module-load time (PrismaService extends PrismaClient), so the
    # OpenAPI script cannot boot NestFactory without a generated client —
    # the import resolves to the stub and Nest fails silently.
    prisma_error = _ensure_prisma_generate(project_root)
    if prisma_error:
        return {"success": False, "error": prisma_error}

    module_files = _load_wave_b_module_files(project_root, getattr(milestone, "id", ""))
    env = _get_process_env(
        MILESTONE_ID=str(getattr(milestone, "id", "")),
        OUTPUT_DIR=str(contracts_dir),
        MILESTONE_MODULE_FILES=",".join(module_files),
        SKIP_PRISMA_CONNECT="1",
    )

    # D-03: resolve launcher via shutil.which FIRST so a missing npx/node
    # surfaces as a legible ``OpenAPILauncherNotFound`` — not the cryptic
    # Windows ``[WinError 2] The system cannot find the file specified``
    # seen in build-j. The workspace-walk extension (D-03 v2) further
    # prefers project-local ts-node over npx-mediated lookup, eliminating
    # the "'ts-node' is not recognized" class for pnpm workspaces where
    # the binary lives in apps/<pkg>/node_modules/.bin.
    try:
        command = _script_command(script_path, project_root)
    except OpenAPILauncherNotFound as exc:
        logger.warning(
            "OpenAPI launcher unavailable; falling back to regex extraction — %s",
            exc,
        )
        return {"success": False, "error": str(exc)}

    try:
        proc = subprocess.run(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "OpenAPI generation timed out (60s)"}
    except OSError as exc:
        # Belt-and-suspenders: even after _resolve_launcher, a race
        # between path resolution and spawn can still surface a bare
        # OSError. Keep the existing structured return.
        return {"success": False, "error": str(exc)}

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        return {
            "success": False,
            "error": stderr[:500] or stdout[:500] or "OpenAPI generation failed",
        }

    cumulative_spec_path = contracts_dir / "current.json"
    milestone_spec_path = contracts_dir / f"{getattr(milestone, 'id', '')}.json"

    if not cumulative_spec_path.exists():
        return {"success": False, "error": "Cumulative spec not generated"}

    files_written = [_rel(project_root, cumulative_spec_path)]

    milestone_path_str = ""
    if module_files and milestone_spec_path.exists():
        milestone_path_str = str(milestone_spec_path)
        files_written.append(_rel(project_root, milestone_spec_path))
    elif not module_files and milestone_spec_path.exists():
        # Phase 2C rule: no Wave B module artifact -> cumulative-only output.
        try:
            milestone_spec_path.unlink()
        except OSError:
            logger.warning("Unable to remove unscoped milestone spec %s", milestone_spec_path)

    return {
        "success": True,
        "milestone_spec_path": milestone_path_str,
        "cumulative_spec_path": str(cumulative_spec_path),
        "files": files_written,
    }


def _find_generation_script(project_root: Path) -> Path | None:
    for candidate in _SCRIPT_CANDIDATES:
        path = project_root / candidate
        if path.exists():
            return path
    return None


class OpenAPILauncherNotFound(RuntimeError):
    """Raised when the OpenAPI launcher command cannot be resolved on PATH.

    D-03: build-j surfaced ``[WinError 2] The system cannot find the file
    specified`` because ``subprocess.run(["npx", ...])`` on Windows
    cannot resolve ``npx.cmd`` without ``shell=True`` or an explicit
    extension. This exception is the structured replacement — the
    message names the command we looked for and the extensions we tried
    so the fallback to regex extraction becomes a deliberate
    degradation, not a cryptic WinError.
    """

    def __init__(self, command: str, extensions_tried: tuple[str, ...] = ()) -> None:
        self.command = command
        self.extensions_tried = extensions_tried
        tried = ("|".join(extensions_tried)) if extensions_tried else "none"
        super().__init__(
            f"OpenAPI launcher {command!r} not found on PATH "
            f"(checked extensions: {tried})"
        )


# D-03: Windows launcher-resolution extensions. Tried in order after the
# bare name (which covers POSIX + any non-Windows platform already).
_WINDOWS_LAUNCHER_EXTENSIONS: tuple[str, ...] = (".cmd", ".exe", ".bat")


def _resolve_launcher(command: str) -> str:
    """D-03: resolve ``command`` to an absolute path via ``shutil.which``.

    On POSIX ``shutil.which("npx")`` typically returns a valid path and
    we use it directly. On Windows the base name usually does NOT
    resolve (``npx`` is actually ``npx.cmd``); we then try the
    ``.cmd`` / ``.exe`` / ``.bat`` suffixes explicitly. Raises
    :class:`OpenAPILauncherNotFound` if every attempt returns ``None``.

    The caller (``_generate_openapi_specs``) catches the exception and
    surfaces a legible message — regex extraction fallback runs as
    before. No subprocess is spawned inside this helper.
    """
    if not command:
        raise OpenAPILauncherNotFound(command, ())

    resolved = shutil.which(command)
    if resolved:
        return resolved

    # Suffix-aware fallback. Trying these on non-Windows is harmless —
    # they virtually never resolve, and the result is the same
    # exception with the full extension trail recorded.
    tried: list[str] = []
    for ext in _WINDOWS_LAUNCHER_EXTENSIONS:
        tried.append(ext)
        candidate = shutil.which(command + ext)
        if candidate:
            return candidate
    raise OpenAPILauncherNotFound(command, tuple(tried))


def _resolve_local_bin(project_root: Path, name: str) -> str | None:
    """D-03 (workspace walk): resolve ``name`` from the scaffold's own
    ``node_modules/.bin`` rather than relying on system PATH or
    ``npx``-mediated lookup.

    pnpm workspaces (the scaffold's default layout) put binaries in
    ``apps/<pkg>/node_modules/.bin`` and ``packages/<pkg>/node_modules/.bin``,
    NOT in the workspace root. ``npx`` walks node_modules from the
    invocation cwd upwards but does not search sibling workspaces, so a
    bare ``npx ts-node`` from the scaffold root surfaces as
    ``'ts-node' is not recognized`` even though pnpm clearly installed
    it. Resolving from the project's own bin dirs eliminates the npx
    intermediary and the system-PATH dependency entirely — correct as
    soon as the dev tool is in any workspace's node_modules/.bin.

    On Windows, ``node_modules/.bin`` typically contains BOTH a POSIX
    shell shim (``ts-node``) and a Windows launcher shim
    (``ts-node.cmd`` / ``.exe`` / ``.bat``). Returning the bare
    extensionless file causes ``subprocess.run([path, ...])`` to raise
    ``[WinError 193] %1 is not a valid Win32 application`` because the
    file starts with ``#!/bin/sh`` and is not directly spawnable via
    CreateProcess. We therefore skip the extensionless candidate on
    Windows and only return a Windows-native launcher there.

    Returns ``None`` when the binary genuinely isn't installed; the
    caller falls through to the npx branch for back-compat with hosts
    that have ``ts-node`` on PATH globally.
    """
    if not name:
        return None
    candidates: list[Path] = [project_root / "node_modules" / ".bin"]
    for ws_parent in ("apps", "packages"):
        ws_dir = project_root / ws_parent
        if not ws_dir.is_dir():
            continue
        try:
            children = list(ws_dir.iterdir())
        except OSError:
            continue
        for child in children:
            bins_dir = child / "node_modules" / ".bin"
            if bins_dir.is_dir():
                candidates.append(bins_dir)
    suffixes = (
        _WINDOWS_LAUNCHER_EXTENSIONS
        if os.name == "nt"
        else ("", *_WINDOWS_LAUNCHER_EXTENSIONS)
    )
    for bins_dir in candidates:
        for ext in suffixes:
            candidate = bins_dir / f"{name}{ext}"
            if candidate.is_file():
                return str(candidate)
    return None


def _script_command(script_path: Path, project_root: Path) -> list[str]:
    suffix = script_path.suffix.lower()
    if suffix == ".ts":
        # D-03 (workspace walk): prefer the project's own ts-node binary
        # over npx-on-PATH. Eliminates the WinError 2 / "not recognized"
        # class entirely when pnpm has installed ts-node into a workspace
        # node_modules/.bin (the common scaffold layout).
        local_ts_node = _resolve_local_bin(project_root, "ts-node")
        # The OpenAPI script lives at ``scripts/`` at the workspace root —
        # ts-node's tsconfig walk-up from that directory finds no root-level
        # ``tsconfig.json`` (only ``tsconfig.base.json``, which ts-node
        # does not auto-discover). Without explicit compiler options the
        # default target depends on the host Node version and may treat
        # ``.ts`` as ESM on Node 22+ (breaking ``__dirname``), drop
        # decorator metadata (breaking NestJS/Swagger), or fail type
        # checks on the pre-``prisma generate`` ``@prisma/client`` stub.
        # Pass the options explicitly so Wave C produces canonical output
        # regardless of workspace layout or Node release.
        ts_node_flags = [
            "--transpile-only",
            "-O",
            (
                '{"module":"commonjs","target":"ES2022",'
                '"esModuleInterop":true,"experimentalDecorators":true,'
                '"emitDecoratorMetadata":true,"skipLibCheck":true,'
                '"resolveJsonModule":true}'
            ),
        ]
        if local_ts_node:
            return [local_ts_node, *ts_node_flags, str(script_path)]
        # Back-compat: hosts with ts-node on global PATH still work via npx.
        launcher = _resolve_launcher("npx")
        return [launcher, "ts-node", *ts_node_flags, str(script_path)]
    launcher = _resolve_launcher("node")
    return [launcher, str(script_path)]


def _ensure_prisma_generate(project_root: Path) -> str:
    """Run ``prisma generate`` so ``@prisma/client`` has its runtime/types.

    Returns an empty string on success (or when no Prisma schema is
    present) and a short error message otherwise. Idempotent: a second
    call is a no-op if Prisma's generated output is already fresh.
    """
    schema = project_root / "apps" / "api" / "prisma" / "schema.prisma"
    if not schema.is_file():
        return ""
    pnpm = shutil.which("pnpm") or shutil.which("pnpm.cmd") or shutil.which("pnpm.exe")
    if not pnpm:
        return "pnpm not found on PATH; cannot run prisma generate"
    try:
        proc = subprocess.run(
            [pnpm, "--filter", "api", "exec", "prisma", "generate"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return "prisma generate timed out (180s)"
    except OSError as exc:
        return f"prisma generate failed to spawn: {exc}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-500:]
        return f"prisma generate returned {proc.returncode}: {tail}"
    return ""


def _get_process_env(**extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update({key: value for key, value in extra.items() if value is not None})
    return env


def _load_wave_b_module_files(project_root: Path, milestone_id: str) -> list[str]:
    """Load actual module file paths from the Wave B artifact, not feature refs."""

    artifact_path = (
        project_root / ".agent-team" / "artifacts" / f"{milestone_id}-wave-B.json"
    )
    if not artifact_path.exists():
        return []

    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        logger.warning("Invalid Wave B artifact at %s", artifact_path)
        return []

    module_files = [
        _posix(path)
        for path in artifact.get("files_created", [])
        if isinstance(path, str)
        and path.endswith(".module.ts")
        and "app.module" not in path.replace("\\", "/").lower()
    ]
    return sorted(dict.fromkeys(module_files))


def _diff_cumulative_specs(contracts_dir: Path) -> list[str]:
    """Diff current cumulative spec against the previous cumulative version."""

    current_path = contracts_dir / "current.json"
    previous_path = contracts_dir / "previous.json"
    if not current_path.exists():
        return []

    if not previous_path.exists():
        try:
            shutil.copy2(current_path, previous_path)
        except OSError as exc:
            logger.warning("Unable to seed previous OpenAPI spec: %s", exc)
        return []

    try:
        old_spec = json.loads(previous_path.read_text(encoding="utf-8"))
        new_spec = json.loads(current_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logger.warning("Contract diff failed while reading specs: %s", exc)
        return []

    old_ops = _extract_operation_map(old_spec)
    new_ops = _extract_operation_map(new_spec)
    breaking_changes: list[str] = []

    for key in sorted(old_ops):
        if key not in new_ops:
            path, method = key
            breaking_changes.append(f"REMOVED: {method} {path}")

    for key in sorted(set(old_ops) & set(new_ops)):
        if _operation_signature(old_ops[key]) != _operation_signature(new_ops[key]):
            path, method = key
            breaking_changes.append(f"CHANGED: {method} {path}")

    try:
        shutil.copy2(current_path, previous_path)
    except OSError as exc:
        logger.warning("Unable to update previous OpenAPI spec: %s", exc)

    return breaking_changes


def _extract_operation_map(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    operations: dict[tuple[str, str], dict[str, Any]] = {}
    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            operations[(str(path), method.upper())] = operation
    return operations


def _operation_signature(operation: dict[str, Any]) -> str:
    stable_bits = {
        "parameters": operation.get("parameters", []),
        "requestBody": operation.get("requestBody", {}),
        "responses": operation.get("responses", {}),
    }
    return json.dumps(stable_bits, sort_keys=True, separators=(",", ":"))


def _generate_client_package(project_root: Path, spec_path: Path) -> dict[str, Any]:
    """Generate a typed client from the cumulative spec."""

    if not spec_path.exists():
        return {"success": False, "exports": [], "files": [], "error": "Spec not found"}

    orval_config = _find_orval_config(project_root)
    openapi_ts_result = _generate_openapi_ts_client(project_root, spec_path)
    if openapi_ts_result.get("success"):
        return openapi_ts_result
    if openapi_ts_result.get("attempted"):
        logger.warning("openapi-ts generation failed: %s", openapi_ts_result.get("error", "unknown error"))

    orval_config = _find_orval_config(project_root)
    if orval_config:
        try:
            npx_launcher = _resolve_launcher("npx")
            proc = subprocess.run(
                [npx_launcher, "orval", "--config", str(orval_config)],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode == 0:
                client_dir = project_root / "packages" / "api-client"
                exports = _scan_client_exports(client_dir)
                files = _scan_client_files(project_root, client_dir)
                if exports or files:
                    return {
                        "success": True,
                        "exports": exports,
                        "manifest": _build_client_manifest_from_spec(
                            spec_path,
                            available_exports=exports,
                        ),
                        "files": files,
                        "generator": "orval",
                        "fidelity": "canonical",
                        "degradation_reason": "",
                    }
                logger.warning("Orval completed without producing client files; using minimal client fallback")
            logger.warning("Orval generation failed: %s", (proc.stderr or "")[:500])
        except OpenAPILauncherNotFound as exc:
            logger.warning("Orval launcher unavailable; using minimal client fallback: %s", exc)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Orval generation failed: %s", exc)

    minimal = _generate_minimal_ts_client(project_root, spec_path)
    minimal["fidelity"] = "degraded"
    minimal["degradation_reason"] = (
        openapi_ts_result.get("error")
        if openapi_ts_result.get("attempted")
        else "official OpenAPI client generator unavailable; used minimal-ts fallback"
    )
    return minimal


def _generate_openapi_ts_client(project_root: Path, spec_path: Path) -> dict[str, Any]:
    """Generate the typed client with the scaffolded @hey-api/openapi-ts tool."""

    config_path = _find_openapi_ts_config(project_root)
    local_launcher = _resolve_local_bin(project_root, "openapi-ts")
    if config_path is None:
        return {
            "success": False,
            "attempted": False,
            "error": "openapi-ts config not found",
        }
    if local_launcher is None:
        return {
            "success": False,
            "attempted": True,
            "error": "project-local openapi-ts launcher not found; run pnpm install from the workspace root",
        }

    client_dir = project_root / "packages" / "api-client"
    command = [
        local_launcher,
        "-i",
        str(spec_path),
        "-o",
        str(client_dir),
        "-c",
        "@hey-api/client-fetch",
    ]

    try:
        proc = subprocess.run(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"success": False, "attempted": True, "error": str(exc)}

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        return {
            "success": False,
            "attempted": True,
            "error": stderr[:500] or stdout[:500] or "openapi-ts generation failed",
        }

    exports = _scan_client_exports(client_dir)
    files = _scan_client_files(project_root, client_dir)
    ts_files = [path for path in files if path.endswith(".ts")]
    if not (exports or ts_files):
        return {
            "success": False,
            "attempted": True,
            "error": "openapi-ts completed without producing TypeScript client files",
        }

    package_file = _write_api_client_package_json(project_root, client_dir)
    files = sorted({*files, package_file})
    return {
        "success": True,
        "exports": exports,
        "manifest": _build_client_manifest_from_spec(spec_path, available_exports=exports),
        "files": files,
        "generator": "openapi-ts",
        "fidelity": "canonical",
        "degradation_reason": "",
    }


def _find_orval_config(project_root: Path) -> Path | None:
    for name in ("orval.config.ts", "orval.config.js", "orval.config.cjs", "orval.config.mjs"):
        path = project_root / name
        if path.exists():
            return path
    return None


def _find_openapi_ts_config(project_root: Path) -> Path | None:
    for relative in (
        "openapi-ts.config.ts",
        "openapi-ts.config.js",
        "openapi-ts.config.mjs",
        "apps/web/openapi-ts.config.ts",
        "apps/web/openapi-ts.config.js",
        "apps/web/openapi-ts.config.mjs",
    ):
        path = project_root / relative
        if path.exists():
            return path
    return None


# Pinned by ``scaffold_runner`` for ``apps/web``; if the scaffold's
# version changes and we cannot read the workspace pin, fall back to
# this default. Keep in sync with the web pin.
_DEFAULT_HEY_API_CLIENT_FETCH_VERSION = "^0.8.0"


def _read_web_hey_api_client_fetch_version(project_root: Path) -> str:
    """Return the ``@hey-api/client-fetch`` version pinned in ``apps/web``.

    Falls back to ``_DEFAULT_HEY_API_CLIENT_FETCH_VERSION`` if the file
    cannot be read or the dep is absent.
    """
    web_pkg = project_root / "apps" / "web" / "package.json"
    try:
        data = json.loads(web_pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return _DEFAULT_HEY_API_CLIENT_FETCH_VERSION
    deps = data.get("dependencies") or {}
    pinned = deps.get("@hey-api/client-fetch")
    if isinstance(pinned, str) and pinned.strip():
        return pinned
    return _DEFAULT_HEY_API_CLIENT_FETCH_VERSION


def _write_api_client_package_json(project_root: Path, client_dir: Path) -> str:
    client_dir.mkdir(parents=True, exist_ok=True)
    # The openapi-ts canonical generator emits ``client.gen.ts`` /
    # ``sdk.gen.ts`` that ``import { ... } from '@hey-api/client-fetch'``.
    # The hosting package must declare that dep explicitly — pnpm does
    # not hoist it across workspace packages, so without this the api-
    # client TS files fail with TS2307 ("Cannot find module
    # '@hey-api/client-fetch'") when ``apps/web``'s tsc resolves the
    # api-client source. Smoke
    # ``v18 test runs/m1-hardening-smoke-20260425-192650`` reproduced
    # this — Wave D's compile-fix loop exhausted 3 attempts because the
    # api-client itself didn't compile.
    hey_api_version = _read_web_hey_api_client_fetch_version(project_root)
    package_json = {
        "name": "@taskflow/api-client",
        "private": True,
        "version": "0.0.0",
        "type": "module",
        "main": "./index.ts",
        "types": "./index.ts",
        "dependencies": {
            "@hey-api/client-fetch": hey_api_version,
        },
    }
    return _write_text(
        project_root,
        client_dir / "package.json",
        json.dumps(package_json, indent=2) + "\n",
    )


def _generate_minimal_ts_client(project_root: Path, spec_path: Path) -> dict[str, Any]:
    """Write a small generated TypeScript client when Orval is unavailable."""

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return {"success": False, "exports": [], "files": [], "error": str(exc)}

    client_dir = project_root / "packages" / "api-client"
    client_dir.mkdir(parents=True, exist_ok=True)

    types_path = client_dir / "types.ts"
    index_path = client_dir / "index.ts"

    type_lines = _render_types_file(spec)
    client_lines, exports, manifest = _render_client_file(spec)
    files = [
        _write_text(project_root, types_path, "\n".join(type_lines) + "\n"),
        _write_text(project_root, index_path, "\n".join(client_lines) + "\n"),
        _write_api_client_package_json(project_root, client_dir),
    ]

    return {
        "success": True,
        "exports": exports,
        "manifest": manifest,
        "files": files,
        "generator": "minimal-ts",
    }


def _render_types_file(spec: dict[str, Any]) -> list[str]:
    schemas = (((spec.get("components") or {}).get("schemas")) or {})
    known_schema_names = set(schemas)
    lines = [
        "// Generated by agent_team_v15.openapi_generator",
        "",
        "export type QueryValue = string | number | boolean | null | undefined;",
        "",
    ]
    for name in sorted(schemas):
        schema = schemas[name]
        if not isinstance(schema, dict):
            continue
        if schema.get("enum"):
            values = " | ".join(json.dumps(value) for value in schema.get("enum", []))
            lines.append(f"export type {name} = {values or 'string'};")
            lines.append("")
            continue

        if schema.get("type") == "object" or schema.get("properties"):
            lines.append(f"export interface {name} {{")
            required = set(schema.get("required", []) or [])
            properties = schema.get("properties", {}) or {}
            for prop_name, prop_schema in properties.items():
                ts_type = _schema_to_ts_type(prop_schema, known_schema_names)
                optional = "" if prop_name in required else "?"
                lines.append(f"  {prop_name}{optional}: {ts_type};")
            # Query-parameter interfaces need an index signature so they can be
            # passed where Record<string, QueryValue> is expected.  Detect by
            # naming convention: anything ending in "Query" or "Params".
            if name.endswith(("Query", "Params")):
                lines.append("  [key: string]: QueryValue;")
            lines.append("}")
            lines.append("")
            continue

        lines.append(f"export type {name} = {_schema_to_ts_type(schema, known_schema_names)};")
        lines.append("")

    if len(lines) == 2:
        lines.append("export type ApiClientNever = never;")
    return lines


def _render_client_file(spec: dict[str, Any]) -> tuple[list[str], list[str], list[dict[str, str]]]:
    exports: list[str] = []
    manifest: list[dict[str, str]] = []
    known_schema_names = set((((spec.get("components") or {}).get("schemas")) or {}).keys())
    used_export_names: set[str] = set()
    lines = [
        "// Generated by agent_team_v15.openapi_generator",
        "export * from './types';",
        "",
        "export interface RequestOptions {",
        "  baseUrl?: string;",
        "  init?: RequestInit;",
        "}",
        "",
        "async function request<T>(",
        "  method: string,",
        "  path: string,",
        "  args: { query?: Record<string, unknown>; body?: unknown } = {},",
        "  options: RequestOptions = {},",
        "): Promise<T> {",
        "  const baseUrl = (options.baseUrl || '').replace(/\\/$/, '');",
        "  const url = new URL(baseUrl + path, typeof window !== 'undefined' ? window.location.origin : 'http://localhost');",
        "  if (args.query) {",
        "    for (const [key, value] of Object.entries(args.query)) {",
        "      if (value !== undefined && value !== null) {",
        "        url.searchParams.set(key, String(value));",
        "      }",
        "    }",
        "  }",
        "  const response = await fetch(url.toString(), {",
        "    method,",
        "    headers: args.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,",
        "    body: args.body !== undefined ? JSON.stringify(args.body) : undefined,",
        "    ...(options.init || {}),",
        "  });",
        "  if (!response.ok) {",
        "    throw new Error(`API request failed: ${response.status} ${response.statusText}`);",
        "  }",
        "  if (response.status === 204) {",
        "    return undefined as T;",
        "  }",
        "  return (await response.json()) as T;",
        "}",
        "",
    ]

    paths = spec.get("paths") or {}
    for path in sorted(paths):
        path_item = paths[path]
        if not isinstance(path_item, dict):
            continue
        for method in _HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            export_name = _unique_operation_name(
                path,
                method.upper(),
                operation,
                used_export_names,
            )
            exports.append(export_name)

            path_params = _path_parameter_names(path)
            query_params = _query_parameter_names(operation)
            has_body = "requestBody" in operation
            response_type = _response_ts_type(operation, known_schema_names)
            request_type = _request_manifest_type(
                operation,
                path,
                known_schema_names,
            )
            operation_id = str(operation.get("operationId", "") or "").strip()

            arg_lines = ["{"]
            for param in path_params:
                arg_lines.append(f"  {param}: string;")
            if query_params:
                arg_lines.append("  query?: {")
                for param in query_params:
                    arg_lines.append(f"    {param}?: string | number | boolean;")
                arg_lines.append("  };")
            if has_body:
                arg_lines.append("  body?: unknown;")
            arg_lines.append("}")
            args_type = "\n".join(arg_lines)

            path_expr = _render_path_expression(path, path_params)
            lines.append(f"export async function {export_name}(")
            lines.append(f"  args: {args_type},")
            lines.append("  options: RequestOptions = {},")
            lines.append(f"): Promise<{response_type}> {{")
            lines.append(f"  return request<{response_type}>(")
            lines.append(f"    '{method.upper()}',")
            lines.append(f"    {path_expr},")
            lines.append("    {")
            if query_params:
                lines.append("      query: args.query,")
            if has_body:
                lines.append("      body: args.body,")
            lines.append("    },")
            lines.append("    options,")
            lines.append("  );")
            lines.append("}")
            lines.append("")
            manifest.append(
                {
                    "symbol": export_name,
                    "method": method.upper(),
                    "path": path,
                    "request_type": request_type,
                    "response_type": response_type,
                    "operation_id": operation_id,
                    "source_file": "packages/api-client/index.ts",
                }
            )

    return lines, exports, manifest


def _build_client_manifest_from_spec(
    spec_path: Path,
    *,
    available_exports: list[str] | None = None,
) -> list[dict[str, str]]:
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []

    known_schema_names = set((((spec.get("components") or {}).get("schemas")) or {}).keys())
    used_export_names: set[str] = set()
    available = set(available_exports or [])
    manifest: list[dict[str, str]] = []

    paths = spec.get("paths") or {}
    for path in sorted(paths):
        path_item = paths[path]
        if not isinstance(path_item, dict):
            continue
        for method in _HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            export_name = _unique_operation_name(
                path,
                method.upper(),
                operation,
                used_export_names,
            )
            operation_id = str(operation.get("operationId", "") or "").strip()
            symbol = export_name
            operation_symbol = _safe_identifier(operation_id) if operation_id else ""
            if available:
                if export_name in available:
                    symbol = export_name
                elif operation_symbol and operation_symbol in available:
                    symbol = operation_symbol
            manifest.append(
                {
                    "symbol": symbol,
                    "method": method.upper(),
                    "path": path,
                    "request_type": _request_manifest_type(
                        operation,
                        path,
                        known_schema_names,
                    ),
                    "response_type": _response_ts_type(operation, known_schema_names),
                    "operation_id": operation_id,
                    "source_file": "packages/api-client/index.ts",
                }
            )

    return manifest


def _request_body_ts_type(
    operation: dict[str, Any],
    known_schema_names: set[str] | None = None,
) -> str:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return ""

    content = request_body.get("content") or {}
    for content_type in ("application/json", "application/x-www-form-urlencoded", "multipart/form-data"):
        payload = content.get(content_type)
        if isinstance(payload, dict) and isinstance(payload.get("schema"), dict):
            return _schema_to_ts_type(payload["schema"], known_schema_names)
    return "unknown"


def _request_manifest_type(
    operation: dict[str, Any],
    path: str,
    known_schema_names: set[str] | None = None,
) -> str:
    path_params = _path_parameter_names(path)
    query_params = _query_parameter_names(operation)
    body_type = _request_body_ts_type(operation, known_schema_names)

    if not path_params and not query_params and not body_type:
        return "void"
    if body_type and not path_params and not query_params:
        return body_type

    members: list[str] = []
    for param in path_params:
        members.append(f"{param}: string")
    if query_params:
        query_shape = "{ " + "; ".join(
            f"{param}?: string | number | boolean" for param in query_params
        ) + " }"
        members.append(f"query?: {query_shape}")
    if body_type:
        members.append(f"body?: {body_type}")
    return "{ " + "; ".join(members) + " }"


def _path_parameter_names(path: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(r"\{([^}]+)\}", path):
        names.append(match.group(1))
    return names


def _query_parameter_names(operation: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for parameter in operation.get("parameters", []) or []:
        if not isinstance(parameter, dict):
            continue
        if parameter.get("in") == "query" and parameter.get("name"):
            names.append(str(parameter["name"]))
    return names


def _render_path_expression(path: str, path_params: list[str]) -> str:
    if not path_params:
        return json.dumps(path)

    expression = path
    for param in path_params:
        expression = expression.replace("{" + param + "}", "${args." + param + "}")
    return "`" + expression + "`"


def _response_ts_type(
    operation: dict[str, Any],
    known_schema_names: set[str] | None = None,
) -> str:
    responses = operation.get("responses") or {}
    for status_code in ("200", "201", "202", "204", "default"):
        response = responses.get(status_code)
        if not isinstance(response, dict):
            continue
        schema = _response_schema(response)
        if schema:
            return _schema_to_ts_type(schema, known_schema_names)
        if status_code == "204":
            return "void"
    return "unknown"


def _response_schema(response: dict[str, Any]) -> dict[str, Any] | None:
    content = response.get("content") or {}
    app_json = content.get("application/json")
    if isinstance(app_json, dict) and isinstance(app_json.get("schema"), dict):
        return app_json["schema"]
    return None


def _operation_name(path: str, method: str, operation: dict[str, Any]) -> str:
    operation_id = str(operation.get("operationId", "") or "").strip()
    if operation_id:
        return _safe_identifier(operation_id)

    segments = [
        segment
        for segment in re.split(r"[/{}/_-]+", path)
        if segment and not segment.startswith(":")
    ]
    title = "".join(part[:1].upper() + part[1:] for part in segments)
    return _safe_identifier(method.lower() + title or method.lower() + "Request")


def _operation_suffix_from_path(path: str) -> str:
    segments = [
        part[:1].upper() + part[1:]
        for part in re.split(r"[/{}/_-]+", path)
        if part and part.lower() != "api" and not part.startswith(":")
    ]
    return "".join(segments)


def _unique_operation_name(
    path: str,
    method: str,
    operation: dict[str, Any],
    used_names: set[str],
) -> str:
    base_name = _operation_name(path, method, operation)
    if base_name not in used_names:
        used_names.add(base_name)
        return base_name

    suffix = _operation_suffix_from_path(path)
    for candidate in (
        _safe_identifier(f"{base_name}{suffix}"),
        _safe_identifier(f"{method.lower()}{suffix}"),
    ):
        if candidate and candidate not in used_names:
            used_names.add(candidate)
            return candidate

    counter = 2
    while True:
        candidate = _safe_identifier(f"{base_name}{counter}")
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        counter += 1


def _safe_identifier(value: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z_]", "", value)
    if not sanitized:
        sanitized = "apiRequest"
    if sanitized[0].isdigit():
        sanitized = "api_" + sanitized
    return sanitized


def _schema_to_ts_type(
    schema: dict[str, Any] | None,
    known_schema_names: set[str] | None = None,
) -> str:
    if not isinstance(schema, dict):
        return "unknown"

    ref = schema.get("$ref")
    if isinstance(ref, str) and ref:
        ref_name = ref.rsplit("/", 1)[-1]
        if known_schema_names is not None and ref_name not in known_schema_names:
            return "unknown"
        return ref_name

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return " | ".join(json.dumps(value) for value in enum_values)

    schema_type = schema.get("type")
    if schema_type == "array":
        return f"{_schema_to_ts_type(schema.get('items'), known_schema_names)}[]"
    if schema_type in {"integer", "number"}:
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "string":
        return "string"
    if schema_type == "object":
        properties = schema.get("properties") or {}
        required = set(schema.get("required", []) or [])
        if not properties:
            return "Record<string, unknown>"
        members = []
        for name, prop_schema in properties.items():
            optional = "" if name in required else "?"
            members.append(f"{name}{optional}: {_schema_to_ts_type(prop_schema, known_schema_names)}")
        return "{ " + "; ".join(members) + " }"
    return "unknown"


def _scan_client_exports(client_dir: Path) -> list[str]:
    # Safe walker — prunes node_modules / .pnpm at descent. packages/api-client/
    # can carry its own node_modules when installed independently
    # (project_walker.py post smoke #9/#10).
    from .project_walker import iter_project_files

    if not client_dir.exists():
        return []
    pattern = re.compile(
        r"export\s+(?:async\s+)?function\s+([A-Za-z_]\w*)|export\s+const\s+([A-Za-z_]\w*)\s*=",
    )
    exports: list[str] = []
    for path in sorted(iter_project_files(client_dir, patterns=("*.ts",))):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in pattern.finditer(text):
            name = match.group(1) or match.group(2)
            if name and name not in exports:
                exports.append(name)
    return exports


def _scan_client_files(project_root: Path, client_dir: Path) -> list[str]:
    # Safe walker — prunes node_modules / .pnpm at descent. packages/api-client/
    # can carry its own node_modules when installed independently
    # (project_walker.py post smoke #9/#10).
    from .project_walker import iter_project_files

    if not client_dir.exists():
        return []
    return sorted(
        _rel(project_root, path)
        for path in iter_project_files(client_dir)
    )


def _fallback_to_regex_extraction(
    cwd: str,
    milestone: Any,
    result: ContractResult,
) -> ContractResult:
    """Fallback path when a project OpenAPI script is missing or fails."""

    try:
        bundle = _extract_api_bundle(Path(cwd), getattr(milestone, "id", ""))
    except Exception as exc:  # pragma: no cover - guarded for runtime safety
        result.success = False
        result.error_message = (
            f"{result.error_message}; regex extraction failed: {exc}".strip("; ")
        )
        return result

    project_root = Path(cwd)
    contracts_dir = project_root / "contracts" / "openapi"
    contracts_dir.mkdir(parents=True, exist_ok=True)

    cumulative_spec = _bundle_to_openapi(
        bundle,
        title=f"{getattr(milestone, 'title', getattr(milestone, 'id', 'Project'))} API",
        version="1.0.0",
    )
    current_path = contracts_dir / "current.json"
    result.files_created.append(_write_json(project_root, current_path, cumulative_spec))
    result.cumulative_spec_path = str(current_path)

    validation_errors = _validate_cumulative_spec(current_path)
    if validation_errors:
        result.success = False
        result.error_message = "; ".join(validation_errors)
        result.endpoints_summary = _extract_endpoints_from_spec(current_path)
        result.files_created = sorted({path for path in result.files_created if path})
        return result

    module_files = _load_wave_b_module_files(project_root, getattr(milestone, "id", ""))
    if module_files:
        scoped_bundle = _scope_bundle_to_modules(bundle, module_files)
        if scoped_bundle.get("endpoints"):
            milestone_spec = _bundle_dict_to_openapi(
                scoped_bundle,
                title=f"{getattr(milestone, 'title', getattr(milestone, 'id', 'Milestone'))} Milestone API",
                version="1.0.0",
            )
            milestone_path = contracts_dir / f"{getattr(milestone, 'id', '')}.json"
            result.files_created.append(_write_json(project_root, milestone_path, milestone_spec))
            result.milestone_spec_path = str(milestone_path)

    result.breaking_changes = _diff_cumulative_specs(contracts_dir)

    client_result = _generate_client_package(project_root, current_path)
    result.client_exports = list(client_result.get("exports", []) or [])
    result.client_manifest = list(client_result.get("manifest", []) or [])
    result.client_generator = str(client_result.get("generator", "") or "")
    result.client_fidelity = str(client_result.get("fidelity", "") or "")
    result.client_degradation_reason = str(client_result.get("degradation_reason", "") or "")
    result.files_created.extend(list(client_result.get("files", []) or []))
    result.endpoints_summary = _extract_endpoints_from_spec(
        _summary_spec_path(result, contracts_dir)
    )
    _run_regex_crosscheck(
        project_root,
        milestone,
        result,
        regex_summary=result.endpoints_summary,
    )

    if not client_result.get("success", True):
        result.success = False
        result.error_message = str(client_result.get("error", result.error_message))
    elif result.client_fidelity.lower() == "degraded":
        result.success = False
        if not result.error_message:
            result.error_message = (
                "Generated client fidelity is degraded and cannot feed Wave D: "
                f"{result.client_degradation_reason or 'typed client generator fell back to minimal output'}"
            )
    else:
        if result.contract_fidelity.lower() != "degraded":
            result.success = True
            result.error_message = ""
    result.files_created = sorted({path for path in result.files_created if path})
    return result


def _extract_api_bundle(project_root: Path, milestone_id: str) -> Any:
    try:
        from .api_contract_extractor import extract_api_contracts
    except ImportError:  # pragma: no cover - standalone import fallback
        from api_contract_extractor import extract_api_contracts

    return extract_api_contracts(project_root, milestone_id=milestone_id)


def _scope_bundle_to_modules(bundle: Any, module_files: list[str]) -> dict[str, Any]:
    """Scope milestone-local output using module file paths from Wave B artifacts."""

    scope_dirs = {str(Path(path).parent).replace("\\", "/") for path in module_files}
    endpoints: list[dict[str, Any]] = []

    for endpoint in getattr(bundle, "endpoints", []) or []:
        controller_file = _posix(getattr(endpoint, "controller_file", ""))
        if any(
            controller_file.startswith(scope_dir + "/") or controller_file == scope_dir
            for scope_dir in scope_dirs
        ):
            endpoints.append(
                {
                    "path": getattr(endpoint, "path", ""),
                    "method": getattr(endpoint, "method", ""),
                    "handler_name": getattr(endpoint, "handler_name", ""),
                    "controller_file": controller_file,
                    "request_params": list(getattr(endpoint, "request_params", []) or []),
                    "request_body_fields": list(
                        getattr(endpoint, "request_body_fields", []) or []
                    ),
                    "response_fields": list(getattr(endpoint, "response_fields", []) or []),
                    "response_type": getattr(endpoint, "response_type", ""),
                }
            )

    return {
        "version": getattr(bundle, "version", "1.0"),
        "extracted_from_milestone": getattr(bundle, "extracted_from_milestone", ""),
        "field_naming_convention": getattr(
            bundle,
            "field_naming_convention",
            "camelCase",
        ),
        "endpoints": endpoints,
        # Keep cumulative models/enums out of the local spec unless specifically scoped.
        "models": [],
        "enums": [],
    }


def _bundle_to_openapi(bundle: Any, *, title: str, version: str) -> dict[str, Any]:
    bundle_dict = {
        "version": getattr(bundle, "version", "1.0"),
        "extracted_from_milestone": getattr(bundle, "extracted_from_milestone", ""),
        "field_naming_convention": getattr(bundle, "field_naming_convention", "camelCase"),
        "endpoints": [
            {
                "path": getattr(endpoint, "path", ""),
                "method": getattr(endpoint, "method", ""),
                "handler_name": getattr(endpoint, "handler_name", ""),
                "controller_file": getattr(endpoint, "controller_file", ""),
                "request_params": list(getattr(endpoint, "request_params", []) or []),
                "request_body_fields": list(
                    getattr(endpoint, "request_body_fields", []) or []
                ),
                "response_fields": list(getattr(endpoint, "response_fields", []) or []),
                "response_type": getattr(endpoint, "response_type", ""),
            }
            for endpoint in getattr(bundle, "endpoints", []) or []
        ],
        "models": [
            {
                "name": getattr(model, "name", ""),
                "fields": list(getattr(model, "fields", []) or []),
            }
            for model in getattr(bundle, "models", []) or []
        ],
        "enums": [
            {
                "name": getattr(enum, "name", ""),
                "values": list(getattr(enum, "values", []) or []),
            }
            for enum in getattr(bundle, "enums", []) or []
        ],
    }
    return _bundle_dict_to_openapi(bundle_dict, title=title, version=version)


def _bundle_dict_to_openapi(
    bundle: dict[str, Any],
    *,
    title: str,
    version: str,
) -> dict[str, Any]:
    components = {"schemas": {}}
    known_schema_names = {
        str(model.get("name", "") or "").strip()
        for model in bundle.get("models", []) or []
        if str(model.get("name", "") or "").strip()
    }
    known_schema_names.update(
        str(enum.get("name", "") or "").strip()
        for enum in bundle.get("enums", []) or []
        if str(enum.get("name", "") or "").strip()
    )

    for model in bundle.get("models", []) or []:
        name = str(model.get("name", "") or "").strip()
        if not name:
            continue
        required: list[str] = []
        properties: dict[str, Any] = {}
        for field in model.get("fields", []) or []:
            field_name = str(field.get("name", "") or "").strip()
            if not field_name:
                continue
            properties[field_name] = _type_to_schema(
                str(field.get("type", "") or "string"),
                known_schema_names,
            )
            if not bool(field.get("nullable", False)):
                required.append(field_name)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        components["schemas"][name] = schema

    for enum in bundle.get("enums", []) or []:
        name = str(enum.get("name", "") or "").strip()
        if not name:
            continue
        components["schemas"][name] = {
            "type": "string",
            "enum": list(enum.get("values", []) or []),
        }

    paths: dict[str, dict[str, Any]] = {}
    canonical_endpoints: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    for endpoint in bundle.get("endpoints", []) or []:
        raw_path = str(endpoint.get("path", "") or "/")
        if _is_placeholder_route(raw_path):
            continue
        normalized_path = _normalize_openapi_path(raw_path)
        method = str(endpoint.get("method", "GET") or "GET").lower()
        canonical_key = (method, _canonical_endpoint_path(normalized_path))
        chosen = canonical_endpoints.get(canonical_key)
        if chosen is not None and not _prefer_endpoint_path(normalized_path, chosen[0]):
            continue
        canonical_endpoints[canonical_key] = (normalized_path, endpoint)

    # Track operationIds across the whole spec so handler-name collisions
    # ("create", "findAll", etc. used in multiple controllers) get
    # disambiguated by path-derived suffix instead of failing the spec
    # validator with "Duplicate operationId".
    _used_op_names: set[str] = set()
    for normalized_path, endpoint in sorted(canonical_endpoints.values(), key=lambda item: item[0]):
        raw_path = str(endpoint.get("path", "") or normalized_path)
        method = str(endpoint.get("method", "GET") or "GET").lower()
        operation = {
            "operationId": _unique_operation_name(
                normalized_path,
                method.upper(),
                {"operationId": endpoint.get("handler_name", "")},
                _used_op_names,
            ),
            "tags": [_tag_for_path(normalized_path)],
            "responses": {
                _success_status_for_method(method.upper()): {
                    "description": "Generated response",
                }
            },
        }

        parameters: list[dict[str, Any]] = []
        for param_name in list(endpoint.get("request_params", []) or []):
            if param_name.startswith("__"):
                continue
            if _is_path_param(raw_path, param_name):
                parameters.append(
                    {
                        "name": param_name,
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                )
            else:
                parameters.append(
                    {
                        "name": param_name,
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                    }
                )
        if parameters:
            operation["parameters"] = parameters

        request_body_fields = list(endpoint.get("request_body_fields", []) or [])
        if request_body_fields:
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": _fields_to_object_schema(
                            request_body_fields,
                            set(components["schemas"]),
                        ),
                    }
                },
            }

        response_schema = _response_schema_for_endpoint(
            endpoint,
            components["schemas"],
        )
        if response_schema:
            status_key = _success_status_for_method(method.upper())
            operation["responses"][status_key]["content"] = {
                "application/json": {"schema": response_schema}
            }

        paths.setdefault(normalized_path, {})[method] = operation

    doc: dict[str, Any] = {
        "openapi": "3.0.0",
        "info": {
            "title": title,
            "version": version,
        },
        "paths": paths,
    }
    if components["schemas"]:
        doc["components"] = components
    return doc


def _normalize_openapi_path(path: str) -> str:
    normalized = path if path.startswith("/") else "/" + path
    normalized = re.sub(r":([A-Za-z_]\w*)", r"{\1}", normalized)
    normalized = re.sub(r"<(?:[^:>]+:)?([A-Za-z_]\w*)>", r"{\1}", normalized)
    normalized = re.sub(r"//+", "/", normalized)
    return normalized.rstrip("/") or "/"


def _is_placeholder_route(path: str) -> bool:
    return any(token in path for token in ("<%=", "%>", "{{", "}}"))


def _canonical_endpoint_path(path: str) -> str:
    canonical = re.sub(r"^/api(?=/|$)", "", path)
    return canonical or "/"


def _prefer_endpoint_path(candidate: str, existing: str) -> bool:
    candidate_has_api = candidate.startswith("/api/")
    existing_has_api = existing.startswith("/api/")
    if candidate_has_api != existing_has_api:
        return candidate_has_api
    return len(candidate) >= len(existing)


def _success_status_for_method(method: str) -> str:
    if method == "POST":
        return "201"
    if method == "DELETE":
        return "204"
    return "200"


def _tag_for_path(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part and not part.startswith("{")]
    return parts[0] if parts else "default"


def _is_path_param(path: str, param_name: str) -> bool:
    return (
        f":{param_name}" in path
        or "{" + param_name + "}" in path
        or re.search(rf"<(?:[^:>]+:)?{re.escape(param_name)}>", path) is not None
    )


def _fields_to_object_schema(
    fields: list[dict[str, Any]],
    known_schema_names: set[str] | None = None,
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in fields:
        name = str(field.get("name", "") or "").strip()
        if not name:
            continue
        properties[name] = _type_to_schema(
            str(field.get("type", "") or "string"),
            known_schema_names,
        )
        required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _response_schema_for_endpoint(
    endpoint: dict[str, Any],
    component_schemas: dict[str, Any],
) -> dict[str, Any] | None:
    response_type = str(endpoint.get("response_type", "") or "").strip()
    if response_type:
        ref_schema = _response_type_ref_schema(response_type, component_schemas)
        if ref_schema is not None:
            return ref_schema

    response_fields = list(endpoint.get("response_fields", []) or [])
    if response_fields:
        return _fields_to_object_schema(response_fields, set(component_schemas))
    return None


def _response_type_ref_schema(
    response_type: str,
    component_schemas: dict[str, Any],
) -> dict[str, Any] | None:
    array_match = re.fullmatch(r"([A-Za-z_]\w*)\[\]", response_type)
    if array_match:
        name = array_match.group(1)
        if name in component_schemas:
            return {"type": "array", "items": {"$ref": f"#/components/schemas/{name}"}}

    promise_match = re.fullmatch(r"Promise<(.+)>", response_type)
    if promise_match:
        return _response_type_ref_schema(promise_match.group(1), component_schemas)

    if response_type in component_schemas:
        return {"$ref": f"#/components/schemas/{response_type}"}

    primitive = _primitive_type_schema(response_type)
    if primitive is not None:
        return primitive

    return None


def _type_to_schema(
    type_name: str,
    known_schema_names: set[str] | None = None,
) -> dict[str, Any]:
    type_name = type_name.strip()
    if type_name.endswith("[]"):
        return {"type": "array", "items": _type_to_schema(type_name[:-2], known_schema_names)}

    primitive = _primitive_type_schema(type_name)
    if primitive is not None:
        return primitive

    union_values = [part.strip().strip("'\"") for part in type_name.split("|")]
    if (
        len(union_values) > 1
        and all(value and re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in union_values)
    ):
        return {"type": "string", "enum": union_values}

    if not type_name:
        return {"type": "string"}
    if known_schema_names is not None and type_name not in known_schema_names:
        return {"type": "object", "additionalProperties": True}
    return {"$ref": f"#/components/schemas/{type_name}"}


def _primitive_type_schema(type_name: str) -> dict[str, Any] | None:
    normalized = type_name.strip().lower()
    if normalized in {"string", "date", "datetime", "uuid"}:
        return {"type": "string"}
    if normalized in {"int", "integer", "float", "double", "number"}:
        return {"type": "number"}
    if normalized in {"bool", "boolean"}:
        return {"type": "boolean"}
    if normalized in {"dict", "object", "record<string,unknown>", "record<string, any>", "json"}:
        return {"type": "object", "additionalProperties": True}
    if normalized in {"any", "unknown"}:
        return {}
    return None


def _extract_endpoints_from_spec(spec_path: Path) -> list[dict[str, Any]]:
    if not spec_path.exists():
        return []
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []

    endpoints: list[dict[str, Any]] = []
    for path, path_item in sorted((spec.get("paths") or {}).items()):
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            endpoints.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operationId": operation.get("operationId", ""),
                    "tag": (operation.get("tags") or [""])[0],
                }
            )
    return endpoints


def _validate_cumulative_spec(spec_path: Path) -> list[str]:
    """Return deterministic cumulative-spec validation errors for Wave C."""

    if not spec_path.exists():
        return ["Cumulative spec validation failed: current.json was not generated"]

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return [f"Cumulative spec validation failed: {exc}"]

    errors: list[str] = []
    if not isinstance(spec, dict):
        return ["Cumulative spec validation failed: root document must be an object"]

    openapi_version = str(spec.get("openapi", "") or "").strip()
    if not openapi_version:
        errors.append("Cumulative spec validation failed: missing required openapi field")

    info = spec.get("info")
    if not isinstance(info, dict):
        errors.append("Cumulative spec validation failed: missing required info object")
    else:
        if not str(info.get("title", "") or "").strip():
            errors.append("Cumulative spec validation failed: missing required info.title")
        if not str(info.get("version", "") or "").strip():
            errors.append("Cumulative spec validation failed: missing required info.version")

    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        errors.append("Cumulative spec validation failed: missing non-empty paths object")
        paths = {}

    operation_locations: dict[str, list[str]] = {}
    canonical_routes: dict[tuple[str, str], list[str]] = {}
    placeholder_routes: list[str] = []

    for raw_path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        normalized_path = _normalize_openapi_path(str(raw_path or "/"))
        if _is_placeholder_route(str(raw_path)):
            placeholder_routes.append(normalized_path)
        for method, operation in path_item.items():
            method_upper = str(method or "").upper()
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            location = f"{method_upper} {normalized_path}"
            operation_id = str(operation.get("operationId", "") or "").strip()
            if operation_id:
                operation_locations.setdefault(operation_id, []).append(location)
            canonical_key = (method_upper, _canonical_endpoint_path(normalized_path))
            canonical_routes.setdefault(canonical_key, []).append(normalized_path)

    for operation_id, locations in sorted(operation_locations.items()):
        unique_locations = sorted(dict.fromkeys(locations))
        if len(unique_locations) > 1:
            errors.append(
                f"Duplicate operationId '{operation_id}' in {', '.join(unique_locations)}"
            )

    for (method, canonical_path), locations in sorted(canonical_routes.items()):
        unique_locations = sorted(dict.fromkeys(locations))
        if len(unique_locations) > 1:
            errors.append(
                f"Duplicate route for {method} {canonical_path}: {', '.join(unique_locations)}"
            )

    if placeholder_routes:
        placeholder_list = ", ".join(sorted(dict.fromkeys(placeholder_routes)))
        errors.append(f"Placeholder routes remain in cumulative spec: {placeholder_list}")

    return errors


def _run_regex_crosscheck(
    project_root: Path,
    milestone: Any,
    result: ContractResult,
    *,
    regex_summary: list[dict[str, Any]] | None = None,
) -> None:
    """Best-effort cross-check between generated spec endpoints and regex extraction."""

    try:
        if regex_summary is None:
            bundle = _extract_api_bundle(project_root, getattr(milestone, "id", ""))
            regex_summary = [
                {"method": getattr(endpoint, "method", ""), "path": getattr(endpoint, "path", "")}
                for endpoint in getattr(bundle, "endpoints", []) or []
            ]
    except Exception as exc:  # pragma: no cover - non-fatal safety net
        logger.warning("Regex cross-check failed for %s: %s", getattr(milestone, "id", ""), exc)
        return

    generated_pairs = {
        (
            str(item.get("method", "")).upper(),
            _normalize_openapi_path(str(item.get("path", "") or "/")),
        )
        for item in result.endpoints_summary
    }
    regex_pairs = {
        (
            str(item.get("method", "")).upper(),
            _normalize_openapi_path(str(item.get("path", "") or "/")),
        )
        for item in regex_summary or []
    }

    missing_from_generated = sorted(regex_pairs - generated_pairs)
    missing_from_regex = sorted(generated_pairs - regex_pairs)
    if missing_from_generated or missing_from_regex:
        logger.info(
            "Wave C regex cross-check for %s: generated-only=%d regex-only=%d",
            getattr(milestone, "id", ""),
            len(missing_from_regex),
            len(missing_from_generated),
        )


def _summary_spec_path(result: ContractResult, contracts_dir: Path) -> Path:
    if result.milestone_spec_path:
        return Path(result.milestone_spec_path)
    if result.cumulative_spec_path:
        return Path(result.cumulative_spec_path)
    return contracts_dir / "current.json"


def _write_json(project_root: Path, path: Path, payload: dict[str, Any]) -> str:
    return _write_text(
        project_root,
        path,
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def _write_text(project_root: Path, path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return _rel(project_root, path)


def _rel(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _posix(path: str) -> str:
    return path.replace("\\", "/")


__all__ = [
    "ContractResult",
    "generate_openapi_contracts",
]
