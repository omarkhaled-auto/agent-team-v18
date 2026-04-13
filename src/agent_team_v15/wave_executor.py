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
class WaveFinding:
    """Lightweight finding emitted by wave-level deterministic checks.

    The audit loop converts these to full :class:`audit_agent.Finding`
    records. Used by V18.2 post-Wave-E scanner adapters, the probe →
    findings bridge, and Wave T TEST-FAIL records.
    """

    code: str
    severity: str = "MEDIUM"
    file: str = ""
    line: int = 0
    message: str = ""


@dataclass
class WaveResult:
    """Result of a single wave execution."""

    wave: str
    cost: float = 0.0
    success: bool = True
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    compile_passed: bool = False
    compile_skipped: bool = False
    compile_iterations: int = 0
    compile_errors_initial: int = 0
    compile_fix_cost: float = 0.0
    rolled_back: bool = False
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
    # --- V18.2 deterministic wave findings (scanners, probes, Wave T TEST-FAIL) ---
    findings: list[WaveFinding] = field(default_factory=list)
    # --- V18.2 Wave T telemetry ---
    tests_written: int = 0
    tests_passed_initial: int = 0
    tests_failed_initial: int = 0
    tests_passed_final: int = 0
    tests_failed_final: int = 0
    fix_iterations: int = 0
    app_code_fixes: int = 0
    test_code_fixes: int = 0
    structural_findings_logged: int = 0
    # --- V18.2 post-Wave-E deterministic test runners ---
    backend_tests_passed: int = 0
    backend_tests_failed: int = 0
    playwright_tests_passed: int = 0
    playwright_tests_failed: int = 0


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
class _DeterministicGuardResult:
    """Result of a bounded deterministic scan fix loop inside a wave."""

    passed: bool = True
    compile_passed: bool = True
    iterations: int = 1
    compile_iterations: int = 0
    initial_issue_count: int = 0
    fix_cost: float = 0.0
    findings: list[WaveFinding] = field(default_factory=list)
    error_message: str = ""


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
    "full_stack": ["A", "B", "C", "D", "D5", "E"],
    "backend_only": ["A", "B", "C", "E"],
    "frontend_only": ["A", "D", "D5", "E"],
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


def _wave_t_enabled(config: Any | None) -> bool:
    # V18.2: wave_t_enabled defaults to True in V18Config. The fallback here
    # stays False so legacy ad-hoc configs (e.g. tests passing SimpleNamespace
    # with no v18 attribute) keep the old sequence [A,B,C,D,D5,E]. Real
    # AgentTeamConfig instances return the V18Config attribute value (True).
    value = _get_v18_value(config, "wave_t_enabled", False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _wave_sequence(template: str, config: Any | None = None) -> list[str]:
    waves = list(WAVE_SEQUENCES.get(template, WAVE_SEQUENCES["full_stack"]))
    if "D5" in waves and not _wave_d5_enabled(config):
        waves = [wave for wave in waves if wave != "D5"]
    # V18.2 Wave T: inserted just before Wave E when enabled.
    if _wave_t_enabled(config) and "T" not in waves and "E" in waves:
        e_index = waves.index("E")
        waves.insert(e_index, "T")
    return waves


def _get_resume_wave(milestone_id: str, template: str, cwd: str, config: Any | None = None) -> str:
    """Return the next incomplete wave for a milestone."""

    state = _load_state_dict(cwd)
    progress = state.get("wave_progress", {}).get(milestone_id, {})
    completed = set(progress.get("completed_waves", []))
    waves = _wave_sequence(template, config)
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
        "compile_skipped": wave_result.compile_skipped,
        "files_created": len(wave_result.files_created),
        "files_modified": len(wave_result.files_modified),
        "rolled_back": wave_result.rolled_back,
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
        # V18.2 deterministic findings (scanners, probes, Wave T TEST-FAIL)
        "findings": [
            {
                "code": f.code,
                "severity": f.severity,
                "file": f.file,
                "line": f.line,
                "message": f.message,
            }
            for f in wave_result.findings
        ],
        # V18.2 Wave T telemetry — zero for non-T waves
        "tests_written": wave_result.tests_written,
        "tests_passed_initial": wave_result.tests_passed_initial,
        "tests_failed_initial": wave_result.tests_failed_initial,
        "tests_passed_final": wave_result.tests_passed_final,
        "tests_failed_final": wave_result.tests_failed_final,
        "fix_iterations": wave_result.fix_iterations,
        "app_code_fixes": wave_result.app_code_fixes,
        "test_code_fixes": wave_result.test_code_fixes,
        "structural_findings_logged": wave_result.structural_findings_logged,
        # V18.2 post-Wave-E deterministic test runners — zero for non-E waves
        "backend_tests_passed": wave_result.backend_tests_passed,
        "backend_tests_failed": wave_result.backend_tests_failed,
        "playwright_tests_passed": wave_result.playwright_tests_passed,
        "playwright_tests_failed": wave_result.playwright_tests_failed,
    }
    path = telemetry_dir / f"{milestone_id}-wave-{wave_result.wave}.json"
    path.write_text(json.dumps(telemetry, indent=2, ensure_ascii=False), encoding="utf-8")


def persist_wave_findings_for_audit(
    cwd: str,
    milestone_id: str,
    waves: list[WaveResult],
) -> Path | None:
    """Persist aggregated wave findings to a milestone-scoped JSON file.

    The audit loop reads the resulting ``WAVE_FINDINGS.json`` under the
    milestone directory to surface probe failures, post-Wave-E scan
    violations, and Wave T TEST-FAIL records to auditors. Without this
    bridge those findings would only live in per-wave telemetry and would
    never reach the scorer.

    Returns the path that was written, or ``None`` when there is nothing
    to persist (no milestone id, no findings across any wave).
    """

    milestone = str(milestone_id or "").strip()
    if not milestone:
        return None

    entries: list[dict[str, Any]] = []
    for wave_result in waves:
        for finding in wave_result.findings:
            entries.append(
                {
                    "wave": wave_result.wave,
                    "code": finding.code,
                    "severity": finding.severity,
                    "file": finding.file,
                    "line": finding.line,
                    "message": finding.message,
                }
            )

    milestone_dir = Path(cwd) / ".agent-team" / "milestones" / milestone
    path = milestone_dir / "WAVE_FINDINGS.json"
    if not entries:
        # Write an empty record so the audit loop can distinguish "no wave
        # findings" from "milestone did not run waves" — and remove any
        # stale record from previous runs.
        try:
            milestone_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {"milestone_id": milestone, "findings": [], "generated_at": _now_iso()},
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover - best effort
            logger.warning("Failed to write empty WAVE_FINDINGS.json for %s: %s", milestone, exc)
            return None
        return path

    try:
        milestone_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "milestone_id": milestone,
                    "findings": entries,
                    "generated_at": _now_iso(),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - best effort
        logger.warning("Failed to write WAVE_FINDINGS.json for %s: %s", milestone, exc)
        return None
    return path


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
        "client_manifest": list(getattr(result, "client_manifest", []) or []),
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
    scaffold_enabled = bool(getattr(getattr(config, "v18", None), "scaffold_enabled", False))
    return execution_mode == "wave" and scaffold_enabled


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


def _scaffolding_start_wave(template: str) -> str | None:
    if template == "frontend_only":
        return "D"
    if template in {"full_stack", "backend_only"}:
        return "B"
    return None


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


def _wave_d5_enabled(config: Any | None) -> bool:
    value = _get_v18_value(config, "wave_d5_enabled", True)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _wave_t_max_fix_iterations(config: Any | None) -> int:
    value = _get_v18_value(config, "wave_t_max_fix_iterations", 2)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 2


# ---------------------------------------------------------------------------
# V18.2 shell helpers — only used by Wave T + post-Wave-E test runners.
# Guarded to be import-safe on hosts without Node/Playwright installed.
# ---------------------------------------------------------------------------


def _resolve_shell_command(cmd: list[str]) -> list[str]:
    """Resolve *cmd[0]* via ``shutil.which`` with a Windows ``.cmd`` fallback.

    On Windows, ``npm``/``npx`` ship as ``.cmd`` wrappers that
    ``asyncio.create_subprocess_exec`` cannot locate without explicit
    resolution. This helper mirrors ``compile_profiles._resolve_command``.
    Returns the original argv unchanged if nothing resolves (callers still
    handle FileNotFoundError defensively).
    """

    import shutil as _shutil
    import sys as _sys

    if not cmd:
        return cmd
    exe = cmd[0]
    resolved = _shutil.which(exe)
    if resolved:
        return [resolved] + cmd[1:]
    if _sys.platform == "win32":
        resolved = _shutil.which(f"{exe}.cmd")
        if resolved:
            return [resolved] + cmd[1:]
    return cmd


async def _run_shell_command(
    cmd: list[str],
    cwd: str,
    timeout: float,
) -> tuple[int, str, str]:
    """Run *cmd* in *cwd* with a timeout. Returns (returncode, stdout, stderr).

    Never raises for process failure — the caller decides how to act on
    non-zero exits. Infrastructure errors (command not found, timeout)
    are returned as returncode != 0 with a descriptive stderr. On Windows,
    ``npm``/``npx`` are resolved through ``shutil.which`` with a ``.cmd``
    fallback so Node-based runners work without falling back to
    ``shell=True`` (which would drag in quoting pitfalls).
    """

    import asyncio as _asyncio

    resolved_cmd = _resolve_shell_command(cmd)

    try:
        proc = await _asyncio.create_subprocess_exec(
            *resolved_cmd,
            cwd=cwd,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        return 127, "", f"command not found: {exc}"
    except OSError as exc:
        return 126, "", f"failed to spawn {cmd[0]}: {exc}"

    try:
        stdout_b, stderr_b = await _asyncio.wait_for(proc.communicate(), timeout=timeout)
    except _asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return 124, "", f"timeout after {timeout}s running {cmd[0]}"

    stdout = (stdout_b or b"").decode("utf-8", errors="replace")
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")
    return int(proc.returncode or 0), stdout, stderr


_JEST_SUMMARY_RE = None  # compiled lazily


def _parse_jest_summary(text: str) -> tuple[int, int]:
    """Return (passed, failed) counts parsed from Jest/Vitest output.

    Scans for the stock ``Tests: X failed, Y passed, Z total`` line Jest
    and Vitest both emit. Returns (0, 0) if no recognizable summary is
    found — the caller should treat that as inconclusive.
    """

    global _JEST_SUMMARY_RE
    import re as _re

    if _JEST_SUMMARY_RE is None:
        _JEST_SUMMARY_RE = _re.compile(
            r"Tests?:\s*(?:(\d+)\s+failed[,\s]*)?(?:(\d+)\s+passed[,\s]*)?(?:(\d+)\s+total)?",
            _re.IGNORECASE,
        )

    passed = 0
    failed = 0
    for match in _JEST_SUMMARY_RE.finditer(text):
        failed_group = match.group(1)
        passed_group = match.group(2)
        if failed_group is not None:
            try:
                failed = max(failed, int(failed_group))
            except ValueError:
                pass
        if passed_group is not None:
            try:
                passed = max(passed, int(passed_group))
            except ValueError:
                pass
    return passed, failed


def _package_has_test_script(package_json_path: Path) -> bool:
    """Best-effort check for a ``scripts.test`` entry in package.json.

    Returns True on any parse error to preserve the previous behaviour of
    letting ``npm run test`` decide — this helper only short-circuits when
    we can prove no test script exists, so we do not wrongly skip real
    suites.
    """

    try:
        data = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return True
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return True
    return bool(scripts.get("test"))


async def _run_node_tests(
    cwd: str,
    subdir: str,
    timeout: float,
) -> tuple[bool, int, int, str]:
    """Run ``npm test`` in *cwd*/*subdir*.

    Returns ``(ran, passed, failed, message)`` where ``ran`` is False when
    the subdir, package manifest, or required tool is missing — the caller
    should treat those as a graceful skip. Stays runner-agnostic: ``npm
    test`` is the universal entry point and the project's package.json
    decides whether Jest, Vitest, Mocha, or anything else runs.
    """

    target = Path(cwd) / subdir
    pkg_path = target / "package.json"
    if not target.is_dir() or not pkg_path.is_file():
        return False, 0, 0, f"{subdir}/package.json not found — skipping"
    if not _package_has_test_script(pkg_path):
        return False, 0, 0, f"{subdir} has no scripts.test — skipping"

    returncode, stdout, stderr = await _run_shell_command(
        ["npm", "test", "--silent"],
        cwd=str(target),
        timeout=timeout,
    )
    combined = stdout + "\n" + stderr
    passed, failed = _parse_jest_summary(combined)
    message = ""
    # Returncodes 124 (timeout), 126 (spawn failed), 127 (command not found)
    # mean the test runner never produced a usable summary. Surface those
    # as "not ran" so the caller can warn+skip without recording 0/0 as a
    # real measurement.
    if returncode in {124, 126, 127}:
        snippet = stderr.strip().splitlines()[-3:] if stderr else []
        return False, 0, 0, f"npm test unavailable ({returncode}): " + " | ".join(snippet)
    if returncode != 0 and (passed + failed) == 0:
        snippet = stderr.strip().splitlines()[-3:] if stderr else []
        message = f"npm test exited {returncode}: " + " | ".join(snippet)
    elif returncode != 0:
        message = f"{failed} test(s) failed in {subdir}"
    return True, passed, failed, message


async def _run_playwright_tests(
    cwd: str,
    milestone_id: str,
    timeout: float,
) -> tuple[bool, int, int, str]:
    """Run Playwright tests for a milestone's test directory, if present."""

    test_dir = Path(cwd) / "e2e" / "tests" / str(milestone_id or "")
    if not test_dir.is_dir() or not any(test_dir.glob("*.spec.*")):
        return False, 0, 0, f"e2e/tests/{milestone_id} not found — skipping"

    returncode, stdout, stderr = await _run_shell_command(
        ["npx", "--no-install", "playwright", "test", str(test_dir), "--reporter=line"],
        cwd=str(cwd),
        timeout=timeout,
    )
    combined = stdout + "\n" + stderr

    # Playwright summary line: "  3 passed (9.2s)" / "  1 failed"
    import re as _re

    passed_match = _re.search(r"(\d+)\s+passed", combined)
    failed_match = _re.search(r"(\d+)\s+failed", combined)
    passed = int(passed_match.group(1)) if passed_match else 0
    failed = int(failed_match.group(1)) if failed_match else 0

    # Infrastructure failures mean Playwright never ran — surface as skip
    # so callers don't mis-record the milestone as having zero e2e tests.
    if returncode in {124, 126, 127} and (passed + failed) == 0:
        snippet = stderr.strip().splitlines()[-3:] if stderr else []
        return False, 0, 0, f"playwright unavailable ({returncode}): " + " | ".join(snippet)

    message = ""
    if returncode != 0 and (passed + failed) == 0:
        snippet = stderr.strip().splitlines()[-3:] if stderr else []
        message = f"playwright exited {returncode}: " + " | ".join(snippet)
    elif returncode != 0:
        message = f"{failed} Playwright test(s) failed for milestone {milestone_id}"
    return True, passed, failed, message


def _run_post_wave_e_scans(cwd: str) -> list[WaveFinding]:
    """Run the deterministic scanners that used to only live in the audit loop.

    V18.2: after Wave E's LLM agent returns, run the existing Python scanners
    from :mod:`quality_checks` so that wiring/i18n/UI-compliance findings are
    emitted regardless of whether the LLM decided to surface them. The scans
    themselves already exist — we only wire them into the wave pipeline here.
    Runs independently of evidence_mode; failures collected into WaveFinding.
    """

    findings: list[WaveFinding] = []
    root = Path(cwd)

    # --- Generated-client wiring scans (imports + local shadow type drift) ---
    try:
        from .quality_checks import (
            scan_generated_client_field_alignment,
            scan_generated_client_import_usage,
        )

        for v in scan_generated_client_import_usage(root) or []:
            findings.append(_violation_to_finding(v))
        for v in scan_generated_client_field_alignment(root) or []:
            findings.append(_violation_to_finding(v))
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Post-Wave-E generated-client scan failed: %s", exc)

    # --- UI compliance (SLOP / UI-001..004) ---
    try:
        from .quality_checks import run_ui_compliance_scan

        for v in run_ui_compliance_scan(root) or []:
            findings.append(_violation_to_finding(v))
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Post-Wave-E UI compliance scan failed: %s", exc)

    # --- I18N-HARDCODED-001 (hardcoded JSX strings) ---
    try:
        from .quality_checks import _check_i18n_hardcoded_strings, _iter_source_files

        for src_path in _iter_source_files(root):
            try:
                content = src_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = src_path.relative_to(root).as_posix()
            for v in _check_i18n_hardcoded_strings(content, rel, src_path.suffix) or []:
                findings.append(_violation_to_finding(v))
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Post-Wave-E i18n scan failed: %s", exc)

    return findings


def _violation_to_finding(violation: Any) -> WaveFinding:
    """Convert a :class:`quality_checks.Violation` to a :class:`WaveFinding`."""

    severity_map = {"error": "HIGH", "warning": "MEDIUM", "info": "LOW", "critical": "HIGH"}
    raw_sev = str(getattr(violation, "severity", "warning") or "warning").strip().lower()
    return WaveFinding(
        code=str(getattr(violation, "check", "") or ""),
        severity=severity_map.get(raw_sev, "MEDIUM"),
        file=str(getattr(violation, "file_path", "") or ""),
        line=int(getattr(violation, "line", 0) or 0),
        message=str(getattr(violation, "message", "") or ""),
    )


def _count_wave_t_test_files(created: list[str], modified: list[str]) -> int:
    """Count test files produced by Wave T based on checkpoint diff."""

    total = 0
    for path in list(created) + list(modified):
        name = path.lower()
        if name.endswith((".spec.ts", ".spec.tsx", ".spec.js", ".test.ts", ".test.tsx", ".test.js")):
            total += 1
    return total


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
        # V18.2: live_endpoint_check=True is ON by default. When the host lacks
        # the infrastructure to probe (Docker not installed, no compose file,
        # no healthy external app), we log a warning and skip gracefully rather
        # than failing the build. Genuine probe failures (Docker runs but
        # endpoints return wrong status) still bubble up below.
        infra_missing_markers = (
            "docker",
            "dockerDesktop",
            "npipe",
            "cannot find",
            "not running",
            "no such host",
            "no compose file",
            "compose file was found",
            "no healthy external app",
            "never became healthy",
        )
        if any(marker.lower() in reason.lower() for marker in infra_missing_markers):
            logger.warning(
                "Wave B probing skipped: runtime verification infrastructure is "
                "not available on this host (%s). Set v18.live_endpoint_check=false "
                "to silence this warning.",
                reason,
            )
            return True, "", []
        return False, reason, []

    if not await reset_db_and_seed(cwd):
        return False, "DB reset/seed failed before Wave B endpoint probing", []

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
                return False, "DB reset/seed failed before Wave B probe retry", []
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

    # V18.2 Step 8: emit probe-failure findings so the audit loop also sees
    # them (in addition to the in-wave fix sub-agent retry above). Each
    # failure becomes a HIGH-severity PROBE-<status> finding.
    probe_findings: list[WaveFinding] = []
    for failure in manifest.failures:
        status = getattr(failure, "status_code", None) or getattr(failure, "actual_status", "UNKNOWN")
        method = getattr(failure, "method", "")
        path = getattr(failure, "path", "") or getattr(failure, "endpoint", "")
        expected = getattr(failure, "expected_status", "")
        file_ref = getattr(failure, "endpoint_file", "") or ""
        msg = (
            f"Endpoint {method} {path} returned {status}"
            + (f", expected {expected}" if expected else "")
        ).strip()
        probe_findings.append(
            WaveFinding(
                code=f"PROBE-{status}",
                severity="HIGH",
                file=str(file_ref),
                line=0,
                message=msg or f"Probe failure for {method} {path}",
            )
        )

    if manifest.failures:
        return False, f"{len(manifest.failures)} endpoint probes failed after Wave B verification", probe_findings
    return True, "", probe_findings


async def _execute_wave_t(
    *,
    execute_sdk_call: Callable[..., Any],
    build_wave_prompt: Callable[..., Any],
    run_compile_check: Callable[..., Any] | None,
    milestone: Any,
    ir: dict[str, Any],
    config: Any,
    cwd: str,
    template: str,
    wave_artifacts: dict[str, dict[str, Any]],
    dependency_artifacts: dict[str, dict[str, Any]],
    scaffolded_files: list[str],
) -> WaveResult:
    """Execute Wave T — comprehensive test writing + bounded fix loop.

    Wave T ALWAYS routes to Claude (bypasses provider_map entirely — Claude
    is stronger at test writing per the competition data). Takes a checkpoint
    before running; if the fix iterations break compilation the checkpoint is
    restored and Wave T logs findings but does not fail the milestone.
    """

    from .provider_router import rollback_from_snapshot, snapshot_for_rollback

    start = datetime.now(timezone.utc)
    wave_result = WaveResult(
        wave="T",
        provider="claude",
        provider_model="",
        timestamp=_now_iso(),
    )

    # --- Checkpoint + rollback snapshot (rollback if fixes break compile) ---
    checkpoint_before = _create_checkpoint("T", cwd)
    rollback_snapshot = snapshot_for_rollback(cwd, checkpoint_before)

    # --- Initial Wave T SDK call (always Claude) ---
    try:
        prompt = await _invoke(
            build_wave_prompt,
            wave="T",
            milestone=milestone,
            wave_artifacts=wave_artifacts,
            dependency_artifacts=dependency_artifacts,
            ir=ir,
            config=config,
            scaffolded_files=list(scaffolded_files),
            cwd=cwd,
        )
        cost = await _invoke(
            execute_sdk_call,
            prompt=str(prompt or ""),
            wave="T",
            milestone=milestone,
            config=config,
            cwd=cwd,
            role="wave",
        )
        wave_result.cost = float(cost or 0.0)
    except Exception as exc:  # pragma: no cover - exercised via tests with stubs
        wave_result.success = False
        wave_result.error_message = f"Wave T SDK call failed: {exc}"
        logger.error("Wave T failed for %s: %s", getattr(milestone, "id", ""), exc)
        wave_result.duration_seconds = (datetime.now(timezone.utc) - start).total_seconds()
        return wave_result

    # --- Diff to count written test files ---
    checkpoint_after = _create_checkpoint("T_post", cwd)
    changed = _diff_checkpoints(checkpoint_before, checkpoint_after)
    wave_result.files_created = list(changed.created)
    wave_result.files_modified = list(changed.modified)
    wave_result.tests_written = _count_wave_t_test_files(changed.created, changed.modified)

    # --- Initial test run (backend + frontend) ---
    backend_ran_initial, backend_passed, backend_failed, backend_msg = await _run_node_tests(
        cwd, "apps/api", timeout=120.0
    )
    frontend_ran_initial, frontend_passed, frontend_failed, frontend_msg = await _run_node_tests(
        cwd, "apps/web", timeout=120.0
    )

    wave_result.tests_passed_initial = backend_passed + frontend_passed
    wave_result.tests_failed_initial = backend_failed + frontend_failed
    wave_result.tests_passed_final = wave_result.tests_passed_initial
    wave_result.tests_failed_final = wave_result.tests_failed_initial

    # --- Bounded fix loop (at most wave_t_max_fix_iterations) ---
    max_iterations = _wave_t_max_fix_iterations(config)
    try:
        from .agents import build_wave_t_fix_prompt
    except Exception:  # pragma: no cover - import safety
        build_wave_t_fix_prompt = None  # type: ignore[assignment]

    if (wave_result.tests_failed_final > 0) and max_iterations > 0 and build_wave_t_fix_prompt is not None:
        failures: list[dict[str, Any]] = []
        if backend_ran_initial and backend_failed:
            failures.append({"file": "apps/api", "test": "backend suite", "message": backend_msg or f"{backend_failed} failed"})
        if frontend_ran_initial and frontend_failed:
            failures.append({"file": "apps/web", "test": "frontend suite", "message": frontend_msg or f"{frontend_failed} failed"})

        for iteration in range(max_iterations):
            fix_prompt = build_wave_t_fix_prompt(
                milestone=milestone,
                failures=failures,
                iteration=iteration,
                max_iterations=max_iterations,
                ir=ir,
            )

            pre_fix_checkpoint = _create_checkpoint(f"T_pre_fix_{iteration}", cwd)
            try:
                cost = await _invoke(
                    execute_sdk_call,
                    prompt=fix_prompt,
                    wave="T",
                    milestone=milestone,
                    config=config,
                    cwd=cwd,
                    role="test_fix",
                )
                wave_result.cost += float(cost or 0.0)
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning("Wave T fix iteration %s failed: %s", iteration + 1, exc)
                break

            wave_result.fix_iterations = iteration + 1
            post_fix_checkpoint = _create_checkpoint(f"T_post_fix_{iteration}", cwd)
            fix_diff = _diff_checkpoints(pre_fix_checkpoint, post_fix_checkpoint)
            for rel_path in list(fix_diff.created) + list(fix_diff.modified):
                name = rel_path.lower()
                if name.endswith((".spec.ts", ".spec.tsx", ".spec.js", ".test.ts", ".test.tsx", ".test.js")):
                    wave_result.test_code_fixes += 1
                else:
                    wave_result.app_code_fixes += 1

            backend_ran, backend_passed, backend_failed, backend_msg = await _run_node_tests(
                cwd, "apps/api", timeout=120.0
            )
            frontend_ran, frontend_passed, frontend_failed, frontend_msg = await _run_node_tests(
                cwd, "apps/web", timeout=120.0
            )
            wave_result.tests_passed_final = backend_passed + frontend_passed
            wave_result.tests_failed_final = backend_failed + frontend_failed

            if wave_result.tests_failed_final == 0:
                break

            failures = []
            if backend_ran and backend_failed:
                failures.append({"file": "apps/api", "test": "backend suite", "message": backend_msg or f"{backend_failed} failed"})
            if frontend_ran and frontend_failed:
                failures.append({"file": "apps/web", "test": "frontend suite", "message": frontend_msg or f"{frontend_failed} failed"})

    # --- Compile check after fixes. Rollback if the fixes broke the build. ---
    checkpoint_post_all = _create_checkpoint("T_post_all", cwd)
    diff_post_all = _diff_checkpoints(checkpoint_before, checkpoint_post_all)
    wave_result.files_created = list(diff_post_all.created)
    wave_result.files_modified = list(diff_post_all.modified)

    if run_compile_check is not None and wave_result.fix_iterations > 0:
        compile_result = await _run_wave_compile(
            run_compile_check=run_compile_check,
            execute_sdk_call=None,  # no compile-fix sub-agent for Wave T
            wave_letter="T",
            template=template,
            config=config,
            cwd=cwd,
            milestone=milestone,
        )
        if not compile_result.passed:
            rollback_from_snapshot(
                cwd,
                rollback_snapshot,
                checkpoint_before,
                checkpoint_post_all,
                _diff_checkpoints,
            )
            checkpoint_after_rollback = _create_checkpoint("T_rollback", cwd)
            diff_after_rollback = _diff_checkpoints(checkpoint_before, checkpoint_after_rollback)
            wave_result.files_created = list(diff_after_rollback.created)
            wave_result.files_modified = list(diff_after_rollback.modified)
            wave_result.rolled_back = True
            wave_result.error_message = (
                f"Wave T rolled back — fix iterations broke compilation after "
                f"{compile_result.iterations} attempt(s)."
            )
            wave_result.findings.append(
                WaveFinding(
                    code="WAVE-T-ROLLBACK",
                    severity="MEDIUM",
                    file="",
                    line=0,
                    message=wave_result.error_message,
                )
            )
            # Re-measure tests after rollback (pre-T state).
            _, backend_passed, backend_failed, _ = await _run_node_tests(cwd, "apps/api", timeout=120.0)
            _, frontend_passed, frontend_failed, _ = await _run_node_tests(cwd, "apps/web", timeout=120.0)
            wave_result.tests_passed_final = backend_passed + frontend_passed
            wave_result.tests_failed_final = backend_failed + frontend_failed

    # --- Remaining failures → TEST-FAIL findings for the audit loop ---
    if wave_result.tests_failed_final > 0:
        wave_result.findings.append(
            WaveFinding(
                code="TEST-FAIL",
                severity="HIGH",
                file="",
                line=0,
                message=(
                    f"{wave_result.tests_failed_final} test(s) still failing after "
                    f"{wave_result.fix_iterations} Wave T fix iteration(s). "
                    "Likely structural — audit loop should investigate."
                ),
            )
        )
        wave_result.structural_findings_logged = 1

    # Wave T does NOT fail the milestone when tests still fail — it logs
    # findings and lets the audit loop decide.
    wave_result.success = True
    wave_result.duration_seconds = (datetime.now(timezone.utc) - start).total_seconds()
    return wave_result


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


def _build_dto_contract_fix_prompt(
    violations: list[Any],
    milestone: Any,
) -> str:
    lines = [
        "[PHASE: WAVE B DTO CONTRACT FIX]",
        f"Milestone: {getattr(milestone, 'id', '')} - {getattr(milestone, 'title', '')}",
        "",
        "Fix the DTO contract violations below before Wave C generates OpenAPI and the typed client.",
        "Read the referenced DTO files before editing.",
        "Do not change generated client files or unrelated frontend code.",
        "",
        "[VIOLATIONS]",
    ]
    for violation in violations[:20]:
        lines.append(
            f"- [{getattr(violation, 'check', '?')}] "
            f"{getattr(violation, 'file_path', '?')}:{getattr(violation, 'line', '?')} "
            f"{getattr(violation, 'message', '?')}"
        )
    lines.extend([
        "",
        "[INSTRUCTIONS]",
        "- For DTO-PROP-001: add Swagger field metadata to every DTO field.",
        "- Required fields should use @ApiProperty(...).",
        "- Optional fields may use @ApiPropertyOptional(...) or @ApiProperty({ required: false, ... }).",
        "- For DTO-CASE-001: rename snake_case DTO fields to camelCase and update same-class references.",
        "- Preserve existing validation decorators and DTO types.",
    ])
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
    result = WaveResult(
        wave="C",
        cost=0.0,
        timestamp=_now_iso(),
        compile_passed=True,
        compile_skipped=True,
        provider="python",
    )
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
            "client_manifest": list(contract_result.get("client_manifest", []) or []),
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


async def _run_wave_b_dto_contract_guard(
    *,
    run_compile_check: Callable[..., Any] | None,
    execute_sdk_call: Callable[..., Any] | None,
    template: str,
    config: Any,
    cwd: str,
    milestone: Any,
) -> _DeterministicGuardResult:
    """Run DTO contract scans after Wave B compiles and auto-fix if needed."""
    try:
        from .quality_checks import run_dto_contract_scan
    except Exception as exc:  # pragma: no cover - defensive import safety
        logger.warning("Wave B DTO contract scan unavailable: %s", exc)
        return _DeterministicGuardResult()

    fix_cost = 0.0
    compile_iterations = 0
    initial_issue_count = 0

    for iteration in range(3):
        violations = run_dto_contract_scan(Path(cwd))
        if iteration == 0:
            initial_issue_count = len(violations)

        if not violations:
            return _DeterministicGuardResult(
                passed=True,
                compile_passed=True,
                iterations=iteration + 1,
                compile_iterations=compile_iterations,
                initial_issue_count=initial_issue_count,
                fix_cost=fix_cost,
            )

        if execute_sdk_call is None or iteration >= 2:
            return _DeterministicGuardResult(
                passed=False,
                compile_passed=True,
                iterations=iteration + 1,
                compile_iterations=compile_iterations,
                initial_issue_count=initial_issue_count,
                fix_cost=fix_cost,
                findings=[_violation_to_finding(v) for v in violations],
                error_message=(
                    f"Wave B DTO contract guard found {len(violations)} persistent violation(s) "
                    f"after {iteration + 1} attempt(s). Wave C is blocked until DTO Swagger "
                    "metadata and camelCase field names are fixed."
                ),
            )

        try:
            fix_cost += float(
                await _invoke(
                    execute_sdk_call,
                    prompt=_build_dto_contract_fix_prompt(violations, milestone),
                    wave="B",
                    milestone=milestone,
                    config=config,
                    cwd=cwd,
                    role="compile_fix",
                )
                or 0.0
            )
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Wave B DTO contract fix sub-agent failed: %s", exc)

        recompile = await _run_wave_compile(
            run_compile_check=run_compile_check,
            execute_sdk_call=execute_sdk_call,
            wave_letter="B",
            template=template,
            config=config,
            cwd=cwd,
            milestone=milestone,
        )
        compile_iterations += recompile.iterations
        fix_cost += recompile.fix_cost
        if not recompile.passed:
            return _DeterministicGuardResult(
                passed=False,
                compile_passed=False,
                iterations=iteration + 1,
                compile_iterations=compile_iterations,
                initial_issue_count=initial_issue_count,
                fix_cost=fix_cost,
                error_message=(
                    f"Compile failed after DTO contract fix attempt {iteration + 1}. "
                    "Wave C is blocked until Wave B compiles cleanly again."
                ),
            )

    return _DeterministicGuardResult(
        passed=False,
        compile_passed=True,
        iterations=3,
        compile_iterations=compile_iterations,
        initial_issue_count=initial_issue_count,
        fix_cost=fix_cost,
        error_message="Wave B DTO contract guard exhausted its retry budget.",
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
    waves = _wave_sequence(template, config)
    if not _wave_scaffolding_enabled(config):
        run_scaffolding = None
    result = MilestoneWaveResult(
        milestone_id=getattr(milestone, "id", ""),
        template=template,
    )

    wave_artifacts: dict[str, dict[str, Any]] = {}
    dependency_artifacts = _load_dependency_artifacts(milestone, cwd)
    scaffold_artifact = load_wave_artifact(cwd, result.milestone_id, "SCAFFOLD") or {}
    milestone_scaffolded_files = list(scaffold_artifact.get("scaffolded_files", []) or scaffold_artifact.get("files_created", []) or [])
    scaffolding_completed = bool(scaffold_artifact)
    scaffolding_start_wave = _scaffolding_start_wave(template)

    resume_wave = _get_resume_wave(result.milestone_id, template, cwd, config)
    start_index = waves.index(resume_wave) if resume_wave in waves else 0

    for completed_wave in waves[:start_index]:
        prior_artifact = load_wave_artifact(cwd, result.milestone_id, completed_wave)
        if prior_artifact:
            wave_artifacts[completed_wave] = prior_artifact

    for wave_letter in waves[start_index:]:
        wave_start = datetime.now(timezone.utc)
        if (
            run_scaffolding is not None
            and scaffolding_start_wave == wave_letter
            and not scaffolding_completed
        ):
            milestone_scaffolded_files = await _run_pre_wave_scaffolding(run_scaffolding, ir, cwd, milestone)
            scaffolding_completed = True
            scaffold_artifact = {
                "milestone_id": result.milestone_id,
                "wave": "SCAFFOLD",
                "template": template,
                "scaffolded_files": milestone_scaffolded_files,
                "files_created": list(milestone_scaffolded_files),
                "timestamp": _now_iso(),
            }
            _save_wave_artifact(scaffold_artifact, cwd, result.milestone_id, "SCAFFOLD")

        if save_wave_state is not None:
            await _invoke(
                save_wave_state,
                milestone_id=result.milestone_id,
                wave=wave_letter,
                status="IN_PROGRESS",
            )

        scaffolded_files = list(milestone_scaffolded_files)

        checkpoint_before = _create_checkpoint(wave_letter, cwd)
        rollback_snapshot: dict[str, bytes] | None = None
        if wave_letter == "D5":
            from .provider_router import snapshot_for_rollback

            rollback_snapshot = snapshot_for_rollback(cwd, checkpoint_before)

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
        elif wave_letter == "T":
            # V18.2: Wave T ALWAYS routes to Claude — bypass provider_routing
            # entirely regardless of the user's provider_map. Claude is
            # stronger at writing tests that encode intent; Codex tends to
            # write tests that follow the code, which inverts Wave T's purpose.
            wave_result = await _execute_wave_t(
                execute_sdk_call=execute_sdk_call,
                build_wave_prompt=build_wave_prompt,
                run_compile_check=run_compile_check,
                milestone=milestone,
                ir=ir,
                config=config,
                cwd=cwd,
                template=template,
                wave_artifacts=wave_artifacts,
                dependency_artifacts=dependency_artifacts,
                scaffolded_files=scaffolded_files,
            )
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
                cwd=cwd,
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

        if wave_result.success and wave_letter in {"A", "B", "D", "D5"}:
            compile_result = await _run_wave_compile(
                run_compile_check=run_compile_check,
                execute_sdk_call=execute_sdk_call,
                wave_letter=wave_letter,
                template=template,
                config=config,
                cwd=cwd,
                milestone=milestone,
            )
            dto_guard = _DeterministicGuardResult()
            if wave_letter == "B" and compile_result.passed:
                dto_guard = await _run_wave_b_dto_contract_guard(
                    run_compile_check=run_compile_check,
                    execute_sdk_call=execute_sdk_call,
                    template=template,
                    config=config,
                    cwd=cwd,
                    milestone=milestone,
                )
                if dto_guard.findings:
                    wave_result.findings.extend(dto_guard.findings)
                compile_result.iterations += dto_guard.compile_iterations
                compile_result.fix_cost += dto_guard.fix_cost

            wave_result.compile_passed = compile_result.passed and dto_guard.compile_passed
            wave_result.compile_iterations = compile_result.iterations
            wave_result.compile_errors_initial = compile_result.initial_error_count
            wave_result.compile_fix_cost = compile_result.fix_cost
            wave_result.cost += compile_result.fix_cost
            if not compile_result.passed or not dto_guard.passed:
                if wave_letter == "D5" and rollback_snapshot is not None:
                    from .provider_router import rollback_from_snapshot

                    rollback_from_snapshot(
                        cwd,
                        rollback_snapshot,
                        checkpoint_before,
                        checkpoint_after,
                        _diff_checkpoints,
                    )
                    checkpoint_after = _create_checkpoint(f"{wave_letter}_rollback", cwd)
                    changed_files = _diff_checkpoints(checkpoint_before, checkpoint_after)
                    wave_result.files_created = changed_files.created
                    wave_result.files_modified = changed_files.modified
                    wave_result.rolled_back = True
                    wave_result.error_message = (
                        f"Compile failed after {compile_result.iterations} attempt(s); "
                        "restored the pre-D5 checkpoint."
                    )
                else:
                    wave_result.success = False
                    if not compile_result.passed:
                        wave_result.error_message = (
                            f"Compile failed after {compile_result.iterations} attempt(s)"
                        )
                    else:
                        wave_result.error_message = dto_guard.error_message

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
            probe_return = await _run_wave_b_probing(
                milestone=milestone,
                ir=ir,
                config=config,
                cwd=cwd,
                wave_artifacts=wave_artifacts,
                execute_sdk_call=execute_sdk_call,
            )
            # V18.2: _run_wave_b_probing now returns (ok, error, findings).
            # Older test stubs may still return a 2-tuple — tolerate both.
            probe_findings: list[WaveFinding] = []
            if isinstance(probe_return, tuple):
                if len(probe_return) == 3:
                    probe_ok, probe_error, probe_findings = probe_return
                elif len(probe_return) == 2:
                    probe_ok, probe_error = probe_return
                else:
                    probe_ok, probe_error = True, ""
            else:
                probe_ok, probe_error = True, ""
            if probe_findings:
                wave_result.findings.extend(probe_findings)
            if not probe_ok:
                wave_result.success = False
                wave_result.error_message = probe_error

        # V18.2 post-Wave-E: deterministic scanners + test runners. Runs
        # regardless of whether the Wave E LLM agent remembered to invoke
        # them. The scans are Python-only (no LLM cost) and the runners
        # only spawn subprocesses if the target directories exist.
        if wave_letter == "E":
            scan_findings = _run_post_wave_e_scans(cwd)
            if scan_findings:
                wave_result.findings.extend(scan_findings)

            backend_passed = 0
            backend_failed = 0
            for subdir in ("apps/api", "apps/web"):
                ran, p, f, _ = await _run_node_tests(cwd, subdir, timeout=120.0)
                if ran:
                    backend_passed += p
                    backend_failed += f
            wave_result.backend_tests_passed = backend_passed
            wave_result.backend_tests_failed = backend_failed

            pw_ran, pw_passed, pw_failed, _ = await _run_playwright_tests(
                cwd, result.milestone_id, timeout=180.0
            )
            if pw_ran:
                wave_result.playwright_tests_passed = pw_passed
                wave_result.playwright_tests_failed = pw_failed

            # Test failures surface as findings but DO NOT fail the build.
            if backend_failed > 0:
                wave_result.findings.append(
                    WaveFinding(
                        code="TEST-FAIL-UNIT",
                        severity="HIGH",
                        file="apps/api|apps/web",
                        line=0,
                        message=f"{backend_failed} unit test(s) failing post-Wave-E.",
                    )
                )
            if pw_ran and pw_failed > 0:
                wave_result.findings.append(
                    WaveFinding(
                        code="TEST-FAIL-E2E",
                        severity="HIGH",
                        file=f"e2e/tests/{result.milestone_id}",
                        line=0,
                        message=f"{pw_failed} Playwright test(s) failing post-Wave-E.",
                    )
                )

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

    # Bridge wave findings (probes, post-Wave-E scans, Wave T TEST-FAIL,
    # rollbacks) to the audit loop. Without this the audit scorer never
    # sees probe/scan/test findings produced by the wave pipeline.
    persist_wave_findings_for_audit(cwd, result.milestone_id, result.waves)

    return result


__all__ = [
    "CheckpointDiff",
    "CompileCheckResult",
    "MilestoneWaveResult",
    "WaveCheckpoint",
    "WaveFinding",
    "WaveResult",
    "WAVE_SEQUENCES",
    "_create_checkpoint",
    "_diff_checkpoints",
    "execute_milestone_waves",
    "load_wave_artifact",
    "persist_wave_findings_for_audit",
    "save_wave_telemetry",
]
