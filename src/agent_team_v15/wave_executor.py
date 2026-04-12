"""Wave Executor - multi-wave milestone execution engine.

Phase 2 replaces the single SDK call per milestone with multiple
specialized waves. This module owns the orchestration logic only:
wave ordering, checkpoint diffing, state/telemetry persistence,
artifact routing, and compile boundaries.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from .tracking_compat import finalize_phase2_tracking_docs

logger = logging.getLogger(__name__)

_DEFAULT_SKIP_DIRS = {
    ".git",
    ".agent-team",
    ".next",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


@dataclass
class WaveResult:
    """Result of a single wave execution."""

    wave: str
    cost: float = 0.0
    success: bool = True
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    compile_passed: bool = False
    compile_iterations: int = 0
    compile_errors_initial: int = 0
    compile_fix_cost: float = 0.0
    artifact_path: str = ""
    error_message: str = ""
    duration_seconds: float = 0.0
    timestamp: str = ""
    # --- Provider routing (v18.1 multi-provider wave execution) ---
    provider: str = ""
    provider_model: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""
    retry_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass
class WaveCheckpoint:
    """File manifest used to detect wave deltas."""

    wave: str
    timestamp: str
    file_manifest: dict[str, str] = field(default_factory=dict)


@dataclass
class CheckpointDiff:
    """Diff between two checkpoints."""

    created: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


@dataclass
class CompileCheckResult:
    """Compile gate outcome for a wave."""

    passed: bool = True
    iterations: int = 1
    initial_error_count: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    fix_cost: float = 0.0


@dataclass
class MilestoneWaveResult:
    """Aggregate result for an entire milestone."""

    milestone_id: str
    template: str
    waves: list[WaveResult] = field(default_factory=list)
    total_cost: float = 0.0
    success: bool = True
    error_wave: str = ""


WAVE_SEQUENCES = {
    "full_stack": ["A", "B", "C", "D", "E"],
    "backend_only": ["A", "B", "C", "E"],
    "frontend_only": ["D", "E"],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _checkpoint_file_iter(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _DEFAULT_SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def _create_checkpoint(label: str, cwd: str) -> WaveCheckpoint:
    """Snapshot project files for change detection."""

    root = Path(cwd)
    manifest: dict[str, str] = {}

    for file_path in _checkpoint_file_iter(root):
        try:
            digest = hashlib.md5(file_path.read_bytes()).hexdigest()  # noqa: S324
        except (OSError, PermissionError):
            continue
        manifest[file_path.relative_to(root).as_posix()] = digest

    return WaveCheckpoint(
        wave=label,
        timestamp=_now_iso(),
        file_manifest=manifest,
    )


def _diff_checkpoints(before: WaveCheckpoint, after: WaveCheckpoint) -> CheckpointDiff:
    """Return created/modified/deleted files between checkpoints."""

    diff = CheckpointDiff()

    for path, checksum in after.file_manifest.items():
        if path not in before.file_manifest:
            diff.created.append(path)
        elif before.file_manifest[path] != checksum:
            diff.modified.append(path)

    for path in before.file_manifest:
        if path not in after.file_manifest:
            diff.deleted.append(path)

    diff.created.sort()
    diff.modified.sort()
    diff.deleted.sort()
    return diff


def _state_path(cwd: str) -> Path:
    return Path(cwd) / ".agent-team" / "STATE.json"


def _load_state_dict(cwd: str) -> dict[str, Any]:
    state_path = _state_path(cwd)
    if not state_path.is_file():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def _get_resume_wave(milestone_id: str, template: str, cwd: str) -> str:
    """Return the next incomplete wave for a milestone."""

    state = _load_state_dict(cwd)
    progress = state.get("wave_progress", {}).get(milestone_id, {})
    completed = set(progress.get("completed_waves", []))
    waves = WAVE_SEQUENCES.get(template, WAVE_SEQUENCES["full_stack"])
    for wave in waves:
        if wave not in completed:
            return wave
    return waves[-1]


def _artifact_dir(cwd: str) -> Path:
    return Path(cwd) / ".agent-team" / "artifacts"


def load_wave_artifact(cwd: str, milestone_id: str, wave: str) -> dict[str, Any] | None:
    """Load a previously persisted wave artifact."""

    path = _artifact_dir(cwd) / f"{milestone_id}-wave-{wave}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _save_wave_artifact(artifact: dict[str, Any], cwd: str, milestone_id: str, wave: str) -> str:
    """Persist a wave artifact JSON payload."""

    artifact_dir = _artifact_dir(cwd)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"{milestone_id}-wave-{wave}.json"
    path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _load_dependency_artifacts(milestone: Any, cwd: str) -> dict[str, dict[str, Any]]:
    """Load available dependency artifacts for this milestone."""

    dependency_artifacts: dict[str, dict[str, Any]] = {}
    for dep in getattr(milestone, "dependencies", []) or []:
        # Phase 2: milestone-level dependency routing only.
        # Dependencies are loaded as whole-milestone artifacts.
        # Fine-grained routing (for example, "M3:SyncedSaleOrder") is Phase 4.
        # If a dependency string contains ":", strip it to the milestone ID only.
        dep_id = dep.split(":", 1)[0]
        for wave in ("A", "B", "C"):
            artifact = load_wave_artifact(cwd, dep_id, wave)
            if artifact:
                dependency_artifacts[f"{dep_id}-wave-{wave}"] = artifact
    return dependency_artifacts


def save_wave_telemetry(wave_result: WaveResult, cwd: str, milestone_id: str) -> None:
    """Write per-wave telemetry JSON for diagnostics and tuning."""

    telemetry_dir = Path(cwd) / ".agent-team" / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    telemetry = {
        "milestone_id": milestone_id,
        "wave": wave_result.wave,
        "duration_seconds": wave_result.duration_seconds,
        "sdk_cost_usd": wave_result.cost,
        "compile_fix_cost_usd": wave_result.compile_fix_cost,
        "compile_iterations": wave_result.compile_iterations,
        "compile_errors_initial": wave_result.compile_errors_initial,
        "compile_passed": wave_result.compile_passed,
        "files_created": len(wave_result.files_created),
        "files_modified": len(wave_result.files_modified),
        "success": wave_result.success,
        "error_message": wave_result.error_message,
        "timestamp": wave_result.timestamp,
        # Provider routing fields (empty/zero when routing disabled)
        "provider": wave_result.provider,
        "provider_model": wave_result.provider_model,
        "fallback_used": wave_result.fallback_used,
        "fallback_reason": wave_result.fallback_reason,
        "retry_count": wave_result.retry_count,
        "input_tokens": wave_result.input_tokens,
        "output_tokens": wave_result.output_tokens,
        "reasoning_tokens": wave_result.reasoning_tokens,
    }
    path = telemetry_dir / f"{milestone_id}-wave-{wave_result.wave}.json"
    path.write_text(json.dumps(telemetry, indent=2, ensure_ascii=False), encoding="utf-8")


def _call_kwargs(func: Callable[..., Any], **kwargs: Any) -> Any:
    """Call a callback using only supported keyword arguments."""

    signature = inspect.signature(func)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return func(**kwargs)

    supported = {
        name: value
        for name, value in kwargs.items()
        if name in signature.parameters
    }
    return func(**supported)


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _invoke(func: Callable[..., Any], **kwargs: Any) -> Any:
    return await _await_if_needed(_call_kwargs(func, **kwargs))


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return bool(value)


def _coerce_errors(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _coerce_compile_result(result: Any) -> CompileCheckResult:
    if isinstance(result, CompileCheckResult):
        return result
    if isinstance(result, dict):
        return CompileCheckResult(
            passed=_as_bool(result.get("passed"), default=True),
            iterations=int(result.get("iterations", 1) or 1),
            initial_error_count=int(result.get("initial_error_count", result.get("error_count", 0)) or 0),
            errors=_coerce_errors(result.get("errors")),
        )

    return CompileCheckResult(
        passed=_as_bool(getattr(result, "passed", True), default=True),
        iterations=int(getattr(result, "iterations", 1) or 1),
        initial_error_count=int(
            getattr(result, "initial_error_count", getattr(result, "error_count", 0)) or 0
        ),
        errors=_coerce_errors(getattr(result, "errors", [])),
    )


def _coerce_contract_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return dict(result)
    return {
        "success": _as_bool(getattr(result, "success", True), default=True),
        "milestone_spec_path": getattr(result, "milestone_spec_path", ""),
        "cumulative_spec_path": getattr(result, "cumulative_spec_path", ""),
        "client_exports": list(getattr(result, "client_exports", []) or []),
        "breaking_changes": list(getattr(result, "breaking_changes", []) or []),
        "endpoints_summary": list(getattr(result, "endpoints_summary", []) or []),
        "files_created": list(getattr(result, "files_created", []) or []),
        "error_message": getattr(result, "error_message", ""),
    }


def _default_artifact_payload(
    milestone_id: str,
    wave: str,
    template: str,
    changed_files: list[str],
    modified_files: list[str],
) -> dict[str, Any]:
    return {
        "milestone_id": milestone_id,
        "wave": wave,
        "template": template,
        "files_created": changed_files,
        "files_modified": modified_files,
        "timestamp": _now_iso(),
    }


def _product_ir_path(cwd: str) -> Path:
    product_ir_dir = Path(cwd) / ".agent-team" / "product-ir"
    primary = product_ir_dir / "product.ir.json"
    if primary.is_file():
        return primary
    return product_ir_dir / "IR.json"


def _wave_scaffolding_enabled(config: Any) -> bool:
    execution_mode = str(
        getattr(getattr(config, "v18", None), "execution_mode", "single_call") or "single_call"
    ).strip().lower()
    return execution_mode == "wave"


async def _run_pre_wave_scaffolding(
    run_scaffolding: Callable[..., Any] | None,
    ir: dict[str, Any],
    cwd: str,
    milestone: Any,
) -> list[str]:
    if run_scaffolding is None:
        return []
    ir_path = _product_ir_path(cwd)
    if not ir_path.is_file():
        return []
    return list(
        await _invoke(
            run_scaffolding,
            ir_path=ir_path,
            project_root=Path(cwd),
            milestone_id=getattr(milestone, "id", ""),
            milestone_features=list(getattr(milestone, "feature_refs", []) or []),
            stack_target=getattr(milestone, "stack_target", "") or _stack_target_string(ir),
        )
        or []
    )


async def _run_frontend_scaffolding(
    run_scaffolding: Callable[..., Any] | None,
    ir: dict[str, Any],
    cwd: str,
    milestone: Any,
) -> list[str]:
    return await _run_pre_wave_scaffolding(run_scaffolding, ir, cwd, milestone)


def _stack_target_string(ir: dict[str, Any]) -> str:
    stack_target = ir.get("stack_target", {}) if isinstance(ir, dict) else {}
    if not isinstance(stack_target, dict):
        return ""
    return " ".join(
        str(stack_target.get(key, "") or "").strip()
        for key in ("backend", "frontend", "db", "mobile")
        if str(stack_target.get(key, "") or "").strip()
    )


def _get_v18_value(config: Any, key: str, default: Any) -> Any:
    if isinstance(config, dict):
        v18 = config.get("v18")
        if isinstance(v18, dict) and key in v18:
            return v18.get(key, default)
        return config.get(key, default)
    v18 = getattr(config, "v18", None)
    if v18 is not None:
        return getattr(v18, key, default)
    return getattr(config, key, default)


def _evidence_mode(config: Any) -> str:
    return str(_get_v18_value(config, "evidence_mode", "disabled") or "disabled").strip().lower()


def _live_endpoint_check_enabled(config: Any) -> bool:
    value = _get_v18_value(config, "live_endpoint_check", False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _phase2_tracking_compat_enabled(config: Any) -> bool:
    return _evidence_mode(config) in {"disabled", "record_only"} and not _live_endpoint_check_enabled(config)


async def _run_wave_b_probing(
    *,
    milestone: Any,
    ir: dict[str, Any],
    config: Any,
    cwd: str,
    wave_artifacts: dict[str, dict[str, Any]],
    execute_sdk_call: Callable[..., Any],
) -> tuple[bool, str]:
    from .endpoint_prober import (
        collect_db_assertion_evidence,
        collect_probe_evidence,
        collect_simulator_evidence,
        execute_probes,
        format_probe_failures_for_fix,
        generate_probe_manifest,
        load_seed_fixtures,
        reset_db_and_seed,
        save_probe_manifest,
        save_probe_telemetry,
        start_docker_for_probing,
    )

    docker_ctx = await start_docker_for_probing(cwd, config)
    if not docker_ctx.api_healthy:
        reason = docker_ctx.startup_error or "live endpoint probing startup failed"
        # If Docker itself isn't installed/running, gracefully skip the probing
        # gate instead of failing the wave.  The user enabled live_endpoint_check
        # (possibly via a depth preset) but the host can't satisfy it; we'd
        # rather proceed than block the build on infrastructure the user didn't
        # explicitly sign up for.  Genuine probe failures (Docker runs but tests
        # fail) still bubble up below.
        docker_missing_markers = (
            "docker",
            "dockerDesktop",
            "npipe",
            "cannot find",
            "not running",
            "no such host",
        )
        if any(marker.lower() in reason.lower() for marker in docker_missing_markers):
            logger.warning(
                "Wave B probing skipped: Docker is not available on this host "
                "(%s). Set v18.live_endpoint_check=false to silence this warning.",
                reason,
            )
            return True, ""
        return False, reason

    if not await reset_db_and_seed(cwd):
        return False, "DB reset/seed failed before Wave B endpoint probing"

    cumulative_spec_path = Path(cwd) / "contracts" / "openapi" / "current.json"
    manifest = generate_probe_manifest(
        getattr(milestone, "id", ""),
        wave_artifacts.get("B", {}),
        cumulative_spec_path if cumulative_spec_path.is_file() else None,
        ir,
        load_seed_fixtures(cwd),
    )
    manifest = await execute_probes(manifest, docker_ctx, cwd)

    if manifest.failures:
        fix_prompt = format_probe_failures_for_fix(manifest)
        try:
            await _invoke(
                execute_sdk_call,
                prompt=fix_prompt,
                wave="B",
                milestone=milestone,
                config=config,
                cwd=cwd,
                role="probe_fix",
            )
            if not await reset_db_and_seed(cwd):
                return False, "DB reset/seed failed before Wave B probe retry"
            manifest = await execute_probes(manifest, docker_ctx, cwd)
        except Exception as exc:  # pragma: no cover - best effort fallback
            logger.warning("Wave B.1 probe fix sub-agent failed: %s", exc)

    if _evidence_mode(config) != "disabled":
        from .evidence_ledger import EvidenceLedger

        ledger = EvidenceLedger(Path(cwd) / ".agent-team" / "evidence")
        ledger.load_all()
        for ac_id, record in collect_probe_evidence(manifest, cwd):
            ledger.record_evidence(ac_id, record)
        for ac_id, record in await collect_db_assertion_evidence(manifest, docker_ctx, cwd):
            ledger.record_evidence(ac_id, record)
        for ac_id, record in await collect_simulator_evidence(cwd):
            ledger.record_evidence(ac_id, record)

    save_probe_manifest(manifest, cwd, getattr(milestone, "id", ""))
    save_probe_telemetry(manifest, cwd, getattr(milestone, "id", ""))
    if manifest.failures:
        return False, f"{len(manifest.failures)} endpoint probes failed after Wave B verification"
    return True, ""


def _build_compile_fix_prompt(
    errors: list[dict[str, Any]],
    wave_letter: str,
    milestone: Any,
) -> str:
    lines = [
        f"[PHASE: WAVE {wave_letter} COMPILE FIX]",
        f"Milestone: {getattr(milestone, 'id', '')} - {getattr(milestone, 'title', '')}",
        "",
        "Fix the compile errors below without introducing unrelated changes.",
        "Read each referenced file before editing.",
        "Do not delete working code to silence the compiler.",
        "",
        "[ERRORS]",
    ]
    if not errors:
        lines.append("- Compiler failed but no structured errors were provided.")
    else:
        for error in errors[:20]:
            lines.append(
                f"- {error.get('file', '?')}:{error.get('line', '?')} "
                f"{error.get('code', '')} {error.get('message', '?')}".rstrip()
            )
    return "\n".join(lines)


async def _execute_wave_sdk(
    execute_sdk_call: Callable[..., Any],
    wave_letter: str,
    prompt: str,
    config: Any,
    cwd: str,
    milestone: Any,
    *,
    provider_routing: Any | None = None,
) -> WaveResult:
    """Execute a wave via the assigned provider (Claude or Codex).

    When *provider_routing* is ``None`` (the default) the existing
    Claude-only path runs unchanged.  When a dict is supplied it must
    contain ``provider_map``, ``codex_transport``, ``codex_config``,
    ``codex_home``, ``checkpoint_create``, and ``checkpoint_diff``.
    """
    wave_result = WaveResult(wave=wave_letter, timestamp=_now_iso())

    # --- Multi-provider path ---
    if provider_routing is not None:
        try:
            from .provider_router import execute_wave_with_provider

            meta = await execute_wave_with_provider(
                wave_letter=wave_letter,
                prompt=prompt,
                cwd=cwd,
                config=config,
                provider_map=provider_routing["provider_map"],
                claude_callback=execute_sdk_call,
                claude_callback_kwargs={
                    "wave": wave_letter,
                    "milestone": milestone,
                    "config": config,
                    "cwd": cwd,
                    "role": "wave",
                },
                codex_transport_module=provider_routing.get("codex_transport"),
                codex_config=provider_routing.get("codex_config"),
                codex_home=provider_routing.get("codex_home"),
                checkpoint_create=provider_routing.get(
                    "checkpoint_create", _create_checkpoint
                ),
                checkpoint_diff=provider_routing.get(
                    "checkpoint_diff", _diff_checkpoints
                ),
            )
            wave_result.cost = float(meta.get("cost", 0.0))
            wave_result.provider = meta.get("provider", "")
            wave_result.provider_model = meta.get("provider_model", "")
            wave_result.fallback_used = meta.get("fallback_used", False)
            wave_result.fallback_reason = meta.get("fallback_reason", "")
            wave_result.retry_count = meta.get("retry_count", 0)
            wave_result.input_tokens = meta.get("input_tokens", 0)
            wave_result.output_tokens = meta.get("output_tokens", 0)
            wave_result.reasoning_tokens = meta.get("reasoning_tokens", 0)
            # Codex path may report file changes; override only when present.
            if meta.get("files_created"):
                wave_result.files_created = meta["files_created"]
            if meta.get("files_modified"):
                wave_result.files_modified = meta["files_modified"]
        except Exception as exc:
            wave_result.success = False
            wave_result.error_message = str(exc)
            logger.error(
                "Wave %s provider routing failed for %s: %s",
                wave_letter, getattr(milestone, "id", ""), exc,
            )
        return wave_result

    # --- Existing Claude-only path (unchanged) ---
    wave_result.provider = "claude"
    try:
        cost = await _invoke(
            execute_sdk_call,
            prompt=prompt,
            wave=wave_letter,
            milestone=milestone,
            config=config,
            cwd=cwd,
            role="wave",
        )
        wave_result.cost = float(cost or 0.0)
    except Exception as exc:  # pragma: no cover - exercised via tests with stubs
        wave_result.success = False
        wave_result.error_message = str(exc)
        logger.error("Wave %s failed for %s: %s", wave_letter, getattr(milestone, "id", ""), exc)
    return wave_result


async def _execute_wave_c(
    generate_contracts: Callable[..., Any],
    cwd: str,
    milestone: Any,
    wave_artifacts: dict[str, dict[str, Any]],
) -> WaveResult:
    start = datetime.now(timezone.utc)
    result = WaveResult(wave="C", cost=0.0, timestamp=_now_iso())
    try:
        contract_result = _coerce_contract_result(
            await _invoke(generate_contracts, cwd=cwd, milestone=milestone)
        )
        result.success = _as_bool(contract_result.get("success"), default=True)
        result.files_created = list(contract_result.get("files_created", []) or [])
        if not result.success:
            result.error_message = str(contract_result.get("error_message", "Wave C failed"))
        artifact = {
            "milestone_id": getattr(milestone, "id", ""),
            "wave": "C",
            "openapi_spec_path": contract_result.get("milestone_spec_path", ""),
            "cumulative_spec_path": contract_result.get("cumulative_spec_path", ""),
            "client_exports": list(contract_result.get("client_exports", []) or []),
            "breaking_changes": list(contract_result.get("breaking_changes", []) or []),
            "endpoints": list(contract_result.get("endpoints_summary", []) or []),
            "files_created": result.files_created,
            "timestamp": _now_iso(),
        }
        result.artifact_path = _save_wave_artifact(artifact, cwd, getattr(milestone, "id", ""), "C")
        wave_artifacts["C"] = artifact
    except Exception as exc:  # pragma: no cover - exercised via tests with stubs
        result.success = False
        result.error_message = f"Contract generation failed: {exc}"
        logger.error("Wave C failed for %s: %s", getattr(milestone, "id", ""), exc, exc_info=True)

    result.duration_seconds = (datetime.now(timezone.utc) - start).total_seconds()
    return result


async def _run_wave_compile(
    run_compile_check: Callable[..., Any] | None,
    execute_sdk_call: Callable[..., Any] | None,
    wave_letter: str,
    template: str,
    config: Any,
    cwd: str,
    milestone: Any,
) -> CompileCheckResult:
    if run_compile_check is None:
        return CompileCheckResult(passed=True)

    initial_error_count = 0
    fix_cost = 0.0
    for iteration in range(3):
        raw_result = await _invoke(
            run_compile_check,
            cwd=cwd,
            wave=wave_letter,
            template=template,
            config=config,
            milestone=milestone,
            project_root=Path(cwd),
            stack_target=getattr(milestone, "stack_target", ""),
        )
        compile_result = _coerce_compile_result(raw_result)
        if iteration == 0:
            initial_error_count = compile_result.initial_error_count
            if initial_error_count == 0 and compile_result.errors:
                initial_error_count = len(compile_result.errors)
            compile_result.initial_error_count = initial_error_count

        if compile_result.passed:
            compile_result.iterations = iteration + 1
            compile_result.initial_error_count = initial_error_count
            compile_result.fix_cost = fix_cost
            return compile_result

        if execute_sdk_call is None or iteration >= 2:
            compile_result.iterations = iteration + 1
            compile_result.initial_error_count = initial_error_count
            compile_result.fix_cost = fix_cost
            return compile_result

        fix_prompt = _build_compile_fix_prompt(compile_result.errors, wave_letter, milestone)
        try:
            fix_cost += float(
                await _invoke(
                    execute_sdk_call,
                    prompt=fix_prompt,
                    wave=wave_letter,
                    milestone=milestone,
                    config=config,
                    cwd=cwd,
                    role="compile_fix",
                )
                or 0.0
            )
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Compile fix sub-agent failed for wave %s: %s", wave_letter, exc)

    return CompileCheckResult(
        passed=False,
        iterations=3,
        initial_error_count=initial_error_count,
        fix_cost=fix_cost,
    )


async def execute_milestone_waves(
    milestone: Any,
    ir: dict[str, Any],
    config: Any,
    cwd: str,
    build_wave_prompt: Callable[..., Any],
    execute_sdk_call: Callable[..., Any],
    run_compile_check: Callable[..., Any] | None,
    extract_artifacts: Callable[..., Any] | None,
    generate_contracts: Callable[..., Any] | None,
    run_scaffolding: Callable[..., Any] | None,
    save_wave_state: Callable[..., Any] | None,
    on_wave_complete: Callable[..., Any] | None = None,
    provider_routing: Any | None = None,
) -> MilestoneWaveResult:
    """Execute one milestone through its ordered wave sequence.

    ``cwd`` is the execution root for all reads and writes. It may point to
    the main project root or any isolated project directory used for execution.
    """

    template = getattr(milestone, "template", "full_stack") or "full_stack"
    waves = WAVE_SEQUENCES.get(template, WAVE_SEQUENCES["full_stack"])
    if not _wave_scaffolding_enabled(config):
        run_scaffolding = None
    result = MilestoneWaveResult(
        milestone_id=getattr(milestone, "id", ""),
        template=template,
    )

    wave_artifacts: dict[str, dict[str, Any]] = {}
    dependency_artifacts = _load_dependency_artifacts(milestone, cwd)

    resume_wave = _get_resume_wave(result.milestone_id, template, cwd)
    start_index = waves.index(resume_wave) if resume_wave in waves else 0

    for completed_wave in waves[:start_index]:
        prior_artifact = load_wave_artifact(cwd, result.milestone_id, completed_wave)
        if prior_artifact:
            wave_artifacts[completed_wave] = prior_artifact

    for wave_letter in waves[start_index:]:
        wave_start = datetime.now(timezone.utc)
        if save_wave_state is not None:
            await _invoke(
                save_wave_state,
                milestone_id=result.milestone_id,
                wave=wave_letter,
                status="IN_PROGRESS",
            )

        scaffolded_files: list[str] = []
        if wave_letter == "A" and template != "frontend_only":
            scaffolded_files = await _run_pre_wave_scaffolding(run_scaffolding, ir, cwd, milestone)
        elif wave_letter == "D" and template != "backend_only":
            scaffolded_files = await _run_frontend_scaffolding(run_scaffolding, ir, cwd, milestone)

        checkpoint_before = _create_checkpoint(wave_letter, cwd)

        if wave_letter == "C":
            if generate_contracts is None:
                wave_result = WaveResult(
                    wave="C",
                    success=False,
                    error_message="generate_contracts callback not provided",
                    timestamp=_now_iso(),
                )
            else:
                wave_result = await _execute_wave_c(generate_contracts, cwd, milestone, wave_artifacts)
        else:
            prompt = await _invoke(
                build_wave_prompt,
                wave=wave_letter,
                milestone=milestone,
                wave_artifacts=wave_artifacts,
                dependency_artifacts=dependency_artifacts,
                ir=ir,
                config=config,
                scaffolded_files=scaffolded_files,
            )
            wave_result = await _execute_wave_sdk(
                execute_sdk_call=execute_sdk_call,
                wave_letter=wave_letter,
                prompt=str(prompt or ""),
                config=config,
                cwd=cwd,
                milestone=milestone,
                provider_routing=provider_routing,
            )

        if wave_result.success and wave_letter == "E" and _phase2_tracking_compat_enabled(config):
            finalize_phase2_tracking_docs(
                cwd=cwd,
                milestone_id=result.milestone_id,
                completed_waves=[*result.waves, wave_result],
            )

        checkpoint_after = _create_checkpoint(f"{wave_letter}_post", cwd)
        changed_files = _diff_checkpoints(checkpoint_before, checkpoint_after)
        wave_result.files_created = changed_files.created
        wave_result.files_modified = changed_files.modified

        if wave_result.success and wave_letter in {"A", "B", "D"}:
            compile_result = await _run_wave_compile(
                run_compile_check=run_compile_check,
                execute_sdk_call=execute_sdk_call,
                wave_letter=wave_letter,
                template=template,
                config=config,
                cwd=cwd,
                milestone=milestone,
            )
            wave_result.compile_passed = compile_result.passed
            wave_result.compile_iterations = compile_result.iterations
            wave_result.compile_errors_initial = compile_result.initial_error_count
            wave_result.compile_fix_cost = compile_result.fix_cost
            wave_result.cost += compile_result.fix_cost
            if not compile_result.passed:
                wave_result.success = False
                wave_result.error_message = (
                    f"Compile failed after {compile_result.iterations} attempt(s)"
                )

        if wave_result.success and wave_letter != "C":
            artifact = None
            changed_for_extract = wave_result.files_created + [
                path for path in wave_result.files_modified
                if path not in wave_result.files_created
            ]
            if extract_artifacts is not None:
                artifact = await _invoke(
                    extract_artifacts,
                    cwd=cwd,
                    milestone_id=result.milestone_id,
                    wave=wave_letter,
                    changed_files=changed_for_extract,
                    files_created=wave_result.files_created,
                    files_modified=wave_result.files_modified,
                    milestone=milestone,
                    template=template,
                )
            if not isinstance(artifact, dict):
                artifact = _default_artifact_payload(
                    result.milestone_id,
                    wave_letter,
                    template,
                    wave_result.files_created,
                    wave_result.files_modified,
                )
            wave_result.artifact_path = _save_wave_artifact(
                artifact,
                cwd,
                result.milestone_id,
                wave_letter,
            )
            wave_artifacts[wave_letter] = artifact

        if (
            wave_result.success
            and wave_letter == "B"
            and _live_endpoint_check_enabled(config)
        ):
            probe_ok, probe_error = await _run_wave_b_probing(
                milestone=milestone,
                ir=ir,
                config=config,
                cwd=cwd,
                wave_artifacts=wave_artifacts,
                execute_sdk_call=execute_sdk_call,
            )
            if not probe_ok:
                wave_result.success = False
                wave_result.error_message = probe_error

        wave_result.timestamp = _now_iso()
        wave_result.duration_seconds = (datetime.now(timezone.utc) - wave_start).total_seconds()
        save_wave_telemetry(wave_result, cwd, result.milestone_id)

        result.waves.append(wave_result)
        result.total_cost += wave_result.cost

        final_status = "COMPLETE" if wave_result.success else "FAILED"
        if save_wave_state is not None:
            await _invoke(
                save_wave_state,
                milestone_id=result.milestone_id,
                wave=wave_letter,
                status=final_status,
            )

        if on_wave_complete is not None:
            await _invoke(
                on_wave_complete,
                wave=wave_letter,
                result=wave_result,
                milestone=milestone,
            )

        if not wave_result.success:
            result.success = False
            result.error_wave = wave_letter
            break

    return result


__all__ = [
    "CheckpointDiff",
    "CompileCheckResult",
    "MilestoneWaveResult",
    "WaveCheckpoint",
    "WaveResult",
    "WAVE_SEQUENCES",
    "_create_checkpoint",
    "_diff_checkpoints",
    "execute_milestone_waves",
    "load_wave_artifact",
    "save_wave_telemetry",
]
