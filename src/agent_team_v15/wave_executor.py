"""Wave Executor - multi-wave milestone execution engine.

Phase 2 replaces the single SDK call per milestone with multiple
specialized waves. This module owns the orchestration logic only:
wave ordering, checkpoint diffing, state/telemetry persistence,
artifact routing, and compile boundaries.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import json
import logging
import re
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from .display import print_info
from .milestone_scope import (
    MilestoneScope,
    apply_scope_if_enabled,
    build_scope_for_milestone,
    files_outside_scope,
)
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
    # --- V18.3 watchdog / deterministic frontend scans ---
    wave_timed_out: bool = False
    wave_watchdog_fired_at: str = ""
    last_sdk_message_type: str = ""
    last_sdk_tool_name: str = ""
    hang_report_path: str = ""
    stack_contract_violations: list[dict[str, Any]] = field(default_factory=list)
    stack_contract_retry_count: int = 0
    stack_contract: dict[str, Any] = field(default_factory=dict)
    # --- A-09 milestone scope enforcement ---
    # Files created during this wave that fell outside the milestone's
    # allowed_file_globs. Populated by the post-wave validator in
    # wave_executor when MilestoneScope enforcement is on. Flag-only —
    # does not delete the files or fail the wave.
    scope_violations: list[str] = field(default_factory=list)


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
class _WaveWatchdogState:
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_progress_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_monotonic: float = field(default_factory=time.monotonic)
    last_progress_monotonic: float = field(default_factory=time.monotonic)
    last_message_type: str = "sdk_call_started"
    last_tool_name: str = ""
    recent_events: list[dict[str, str]] = field(default_factory=list)
    progress_event_count: int = 0
    sdk_call_count: int = 0
    # tool_id -> {tool_name, started_at, started_monotonic}. Codex emits explicit
    # item.started / item.completed pairs; orphan starts (no matching complete)
    # name the wedged shell when the watchdog later fires.
    pending_tool_starts: dict[str, dict[str, Any]] = field(default_factory=dict)
    # ClaudeSDKClient reference for interrupt-based wedge recovery (Step 3).
    # Set by _execute_single_wave_sdk after opening the client.
    client: Any = None
    # Count of interrupts fired in this wave session; second orphan -> hard timeout.
    interrupt_count: int = 0

    def record_progress(
        self,
        *,
        message_type: str = "",
        tool_name: str = "",
        tool_id: str = "",
        event_kind: str = "other",
    ) -> None:
        now_iso = _now_iso()
        self.last_progress_at = now_iso
        self.last_progress_monotonic = time.monotonic()
        self.progress_event_count += 1
        if message_type:
            self.last_message_type = str(message_type)
            if message_type == "sdk_call_started":
                self.sdk_call_count += 1
        if tool_name:
            self.last_tool_name = str(tool_name)
        self.recent_events.append(
            {
                "timestamp": now_iso,
                "message_type": self.last_message_type,
                "tool_name": self.last_tool_name,
            }
        )
        if len(self.recent_events) > 20:
            self.recent_events = self.recent_events[-20:]

        if tool_id:
            if event_kind == "start":
                self.pending_tool_starts[tool_id] = {
                    "tool_name": self.last_tool_name,
                    "started_at": now_iso,
                    "started_monotonic": self.last_progress_monotonic,
                }
            elif event_kind == "complete":
                self.pending_tool_starts.pop(tool_id, None)

    async def interrupt_oldest_orphan(self, threshold_seconds: float) -> dict[str, Any] | None:
        """Check pending tools; if any exceeds *threshold_seconds*, call client.interrupt().

        Returns orphan info dict ``{tool_use_id, tool_name, age_seconds}`` when an
        interrupt was fired, or ``None`` if no orphans exceed the threshold or no
        client reference is available.
        """
        if not self.client or not self.pending_tool_starts:
            return None
        now = time.monotonic()
        for tool_id, info in self.pending_tool_starts.items():
            age = now - info.get("started_monotonic", now)
            if age > threshold_seconds:
                logger.warning(
                    "Orphan tool detected: %s (age=%.0fs) — calling client.interrupt()",
                    info.get("tool_name", "unknown"),
                    age,
                )
                await self.client.interrupt()
                self.interrupt_count += 1
                return {
                    "tool_use_id": tool_id,
                    "tool_name": info.get("tool_name", ""),
                    "age_seconds": age,
                }
        return None


class WaveWatchdogTimeoutError(RuntimeError):
    def __init__(
        self,
        wave: str,
        state: _WaveWatchdogState,
        timeout_seconds: int,
        *,
        role: str = "wave",
        include_role_in_message: bool = False,
        timeout_kind: str = "wave-idle",
        orphan_tool_id: str = "",
        orphan_tool_name: str = "",
    ) -> None:
        self.wave = wave
        self.state = state
        self.timeout_seconds = timeout_seconds
        self.role = role
        self.include_role_in_message = include_role_in_message
        self.timeout_kind = timeout_kind
        self.orphan_tool_id = str(orphan_tool_id or "")
        self.orphan_tool_name = str(orphan_tool_name or "")
        self.fired_at = datetime.now(timezone.utc).isoformat()
        idle_seconds = int(max(0, time.monotonic() - state.last_progress_monotonic))
        self.idle_seconds = idle_seconds
        subject = f"Wave {wave} role {role}" if include_role_in_message else f"Wave {wave}"
        if self.timeout_kind == "orphan-tool" and self.orphan_tool_id:
            tool_name = self.orphan_tool_name or "unknown"
            super().__init__(
                f"{subject} detected orphan-tool wedge on {tool_name} "
                f"(item_id={self.orphan_tool_id}) after {idle_seconds}s idle "
                f"(budget: {timeout_seconds}s)."
            )
        else:
            super().__init__(
                f"{subject} exceeded idle timeout of {timeout_seconds}s after {idle_seconds}s "
                f"without SDK progress (last message: {state.last_message_type or 'unknown'})."
            )


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
    "full_stack": ["A", "A5", "Scaffold", "B", "C", "D", "T", "T5", "E"],
    "backend_only": ["A", "A5", "Scaffold", "B", "C", "T", "T5", "E"],
    "frontend_only": ["A", "Scaffold", "D", "T", "T5", "E"],
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
    # Phase G Slice 3b: WAVE_SEQUENCES now carries A5/Scaffold/T/T5 slots by
    # default (merged-D is the design target, so D5 is absent by default).
    # Strip each new slot when its Phase G flag is OFF, and re-insert D5
    # when the merged-D flag is OFF, so the flag-off pipeline remains
    # byte-identical to pre-Phase-G behavior.
    if "A5" in waves and not _get_v18_value(config, "wave_a5_enabled", False):
        waves = [wave for wave in waves if wave != "A5"]
    if "Scaffold" in waves and not _get_v18_value(config, "scaffold_verifier_enabled", False):
        waves = [wave for wave in waves if wave != "Scaffold"]
    if "T5" in waves and not _get_v18_value(config, "wave_t5_enabled", False):
        waves = [wave for wave in waves if wave != "T5"]
    # V18.2 Wave T: strip when wave_t_enabled is False (Phase G now carries T
    # by default in WAVE_SEQUENCES; previously it was inserted just-in-time).
    if "T" in waves and not _wave_t_enabled(config):
        waves = [wave for wave in waves if wave != "T"]
    # D5 re-insertion: when merged-D is OFF (default), restore the legacy
    # D -> D5 pair so flag-off behavior matches pre-Phase-G.
    if (
        "D" in waves
        and "D5" not in waves
        and not _get_v18_value(config, "wave_d_merged_enabled", False)
        and _wave_d5_enabled(config)
    ):
        d_index = waves.index("D")
        waves.insert(d_index + 1, "D5")
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


def _load_milestone_scope(
    milestone: Any,
    cwd: str,
) -> MilestoneScope | None:
    """Build a :class:`MilestoneScope` for *milestone* from on-disk artefacts.

    Returns ``None`` if either MASTER_PLAN.json or the milestone's
    REQUIREMENTS.md cannot be read — the caller keeps the pre-fix
    behaviour in that case.
    """
    milestone_id = str(getattr(milestone, "id", "") or "").strip()
    if not milestone_id:
        return None

    root = Path(cwd)
    master_plan_path = root / ".agent-team" / "MASTER_PLAN.json"
    requirements_path = (
        root / ".agent-team" / "milestones" / milestone_id / "REQUIREMENTS.md"
    )
    if not requirements_path.is_file():
        return None

    master_plan: dict[str, Any] = {"milestones": []}
    if master_plan_path.is_file():
        try:
            master_plan = json.loads(master_plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "MilestoneScope: failed to parse MASTER_PLAN.json at %s: %s",
                master_plan_path, exc,
            )
            master_plan = {"milestones": []}

    try:
        return build_scope_for_milestone(
            master_plan=master_plan,
            milestone_id=milestone_id,
            requirements_md_path=str(requirements_path),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "MilestoneScope: failed to build scope for %s: %s",
            milestone_id, exc,
        )
        return None


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
        "wave_timed_out": wave_result.wave_timed_out,
        "wave_watchdog_fired_at": wave_result.wave_watchdog_fired_at,
        "last_sdk_message_type": wave_result.last_sdk_message_type,
        "last_sdk_tool_name": wave_result.last_sdk_tool_name,
        "hang_report_path": wave_result.hang_report_path,
        "stack_contract_violations": list(wave_result.stack_contract_violations),
        "stack_contract_retry_count": wave_result.stack_contract_retry_count,
        "stack_contract": dict(wave_result.stack_contract),
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


def _derive_wave_t_status(
    waves: list[WaveResult],
    *,
    wave_t_expected: bool,
    failing_wave: str | None,
) -> tuple[str, str | None]:
    """D-11: decide the ``wave_t_status`` / ``skip_reason`` pair.

    Returns ``(status, reason)`` where ``status`` is one of
    ``completed``, ``skipped``, or ``disabled`` and ``reason`` is a
    short human-readable string (``None`` when Wave T completed).
    """
    wave_t_results = [w for w in waves if getattr(w, "wave", None) == "T"]
    wave_t_ran_ok = any(getattr(w, "success", False) for w in wave_t_results)
    if wave_t_ran_ok:
        return "completed", None
    if wave_t_results:
        # Wave T executed but did not succeed — still "ran"; surface a
        # reason so the auditor sees it is not a raw skip.
        err = (wave_t_results[0].error_message or "Wave T did not succeed").strip()
        return "completed_with_failure", err
    if not wave_t_expected:
        return "disabled", "Wave T disabled via configuration"
    if failing_wave:
        return (
            "skipped",
            f"Wave {failing_wave} failed — Wave T cannot run E2E against failing wave output",
        )
    return "skipped", "Wave T did not execute (upstream did not reach T)"


def persist_wave_findings_for_audit(
    cwd: str,
    milestone_id: str,
    waves: list[WaveResult],
    *,
    wave_t_expected: bool = False,
    failing_wave: str | None = None,
) -> Path | None:
    """Persist aggregated wave findings to a milestone-scoped JSON file.

    The audit loop reads the resulting ``WAVE_FINDINGS.json`` under the
    milestone directory to surface probe failures, post-Wave-E scan
    violations, and Wave T TEST-FAIL records to auditors. Without this
    bridge those findings would only live in per-wave telemetry and would
    never reach the scorer.

    D-11: the file is now ALWAYS written with a structured Wave T
    marker — ``wave_t_status`` and (when not completed) ``skip_reason``
    — so downstream gates can distinguish "Wave T ran and found nothing"
    from "Wave T never ran". ``wave_t_expected`` tells us whether the
    milestone's wave sequence included T at plan time; ``failing_wave``
    is the letter of the upstream wave that caused the early break (if
    any) so the reason string names the actual blocker.

    Returns the path that was written, or ``None`` when no milestone id
    is provided.
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

    wave_t_status, skip_reason = _derive_wave_t_status(
        waves,
        wave_t_expected=wave_t_expected,
        failing_wave=failing_wave,
    )

    record: dict[str, Any] = {
        "milestone_id": milestone,
        "generated_at": _now_iso(),
        "wave_t_status": wave_t_status,
        "findings": entries,
    }
    if skip_reason is not None:
        record["skip_reason"] = skip_reason

    milestone_dir = Path(cwd) / ".agent-team" / "milestones" / milestone
    path = milestone_dir / "WAVE_FINDINGS.json"
    try:
        milestone_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False),
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
    scaffold_cfg: Any | None = None,
) -> list[str]:
    if run_scaffolding is None:
        return []
    ir_path = _product_ir_path(cwd)
    if not ir_path.is_file():
        return []
    kwargs: dict[str, Any] = dict(
        ir_path=ir_path,
        project_root=Path(cwd),
        milestone_id=getattr(milestone, "id", ""),
        milestone_features=list(getattr(milestone, "feature_refs", []) or []),
        stack_target=getattr(milestone, "stack_target", "") or _stack_target_string(ir),
    )
    if scaffold_cfg is not None:
        kwargs["scaffold_cfg"] = scaffold_cfg
    return list(await _invoke(run_scaffolding, **kwargs) or [])


def _scaffolding_start_wave(template: str) -> str | None:
    if template == "frontend_only":
        return "D"
    if template in {"full_stack", "backend_only"}:
        return "B"
    return None


def _maybe_run_spec_reconciliation(
    *,
    cwd: str,
    milestone_id: str,
) -> Any | None:
    """N-12 hook: reconcile REQUIREMENTS + PRD into a per-run ``ScaffoldConfig``.

    Returns a ``ScaffoldConfig`` on success, ``None`` when required inputs are
    absent (defensive — pipeline continues with defaults). Persists SPEC.md,
    resolved_manifest.json, and (if applicable) RECONCILIATION_CONFLICTS.md
    under ``.agent-team/milestones/<milestone_id>/``.
    """

    try:
        from .scaffold_runner import load_ownership_contract
        from .milestone_spec_reconciler import reconcile_milestone_spec
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("spec reconciler imports failed: %s", exc)
        return None

    cwd_path = Path(cwd)
    milestone_dir = cwd_path / ".agent-team" / "milestones" / milestone_id
    requirements_path = milestone_dir / "REQUIREMENTS.md"
    if not requirements_path.is_file():
        logger.info("spec reconciler: REQUIREMENTS.md absent at %s", requirements_path)
        return None

    prd_candidates = [
        cwd_path / ".agent-team" / "PRD.md",
        cwd_path / "PRD.md",
    ]
    prd_path = next((p for p in prd_candidates if p.is_file()), None)

    try:
        ownership_contract = load_ownership_contract()
    except Exception as exc:
        logger.warning("spec reconciler: could not load ownership contract: %s", exc)
        return None

    stack_contract: dict[str, Any] = {}
    try:
        from .stack_contract import load_stack_contract

        loaded = load_stack_contract(cwd)
        if loaded is not None:
            stack_contract = loaded.to_dict()
    except Exception:
        stack_contract = {}

    result = reconcile_milestone_spec(
        requirements_path=requirements_path,
        prd_path=prd_path,
        stack_contract=stack_contract,
        ownership_contract=ownership_contract,
        milestone_id=milestone_id,
        output_dir=milestone_dir,
    )
    return result.resolved_scaffold_config


def _maybe_run_scaffold_verifier(
    *,
    cwd: str,
    milestone_scope: "MilestoneScope | None" = None,
    scope_aware: bool = False,
) -> str | None:
    """N-13 hook: verify scaffold emission. Returns an error message on FAIL.

    When *scope_aware* is True and *milestone_scope* carries concrete
    ``allowed_file_globs``, the verifier filters out ownership rows
    belonging to later milestones (e.g. M2 users/projects/tasks modules
    during M1 Wave A) so the gate matches the vertical_slice plan. The
    flag is driven by ``v18.scaffold_verifier_scope_aware`` at the caller.

    N-11: also persists a structured report to ``.agent-team/
    scaffold_verifier_report.json`` so the cli.py cascade-consolidation
    post-processor can replay root-cause clustering without re-running the
    verifier (no coupling between wave_executor and audit modules).
    """

    try:
        from .scaffold_runner import load_ownership_contract
        from .scaffold_verifier import run_scaffold_verifier
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("scaffold verifier imports failed: %s", exc)
        return None

    try:
        ownership_contract = load_ownership_contract()
    except Exception as exc:
        logger.warning("scaffold verifier: could not load ownership contract: %s", exc)
        return None

    scope_for_verifier: "MilestoneScope | None" = (
        milestone_scope if scope_aware else None
    )

    try:
        report = run_scaffold_verifier(
            workspace=Path(cwd),
            ownership_contract=ownership_contract,
            milestone_scope=scope_for_verifier,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("scaffold verifier raised: %s", exc)
        return None

    try:
        report_path = Path(cwd) / ".agent-team" / "scaffold_verifier_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        workspace_root = Path(cwd)
        report_path.write_text(
            json.dumps(
                {
                    "verdict": report.verdict,
                    "missing": [
                        _relative_to_workspace(p, workspace_root) for p in report.missing
                    ],
                    "malformed": [
                        [_relative_to_workspace(p, workspace_root), diag]
                        for (p, diag) in report.malformed
                    ],
                    "deprecated_emitted": [
                        _relative_to_workspace(p, workspace_root)
                        for p in report.deprecated_emitted
                    ],
                    "summary_lines": list(report.summary_lines),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("scaffold verifier report persistence failed: %s", exc)

    if report.verdict == "FAIL":
        return f"Scaffold-verifier FAIL: {report.summary()}"
    return None


def _relative_to_workspace(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


# NEW-1 duplicate Prisma cleanup — the scaffold relocated Prisma wiring
# from ``apps/api/src/prisma/`` to ``apps/api/src/database/`` (N-04).
# Older Wave-B emissions occasionally regenerate the deprecated path; this
# hook removes the stale directory AFTER Wave B completes, provided the
# canonical location carries both prisma.module.ts + prisma.service.ts.
_DUPLICATE_PRISMA_REQUIRED_CANONICAL_FILES: tuple[str, ...] = (
    "prisma.module.ts",
    "prisma.service.ts",
)


def _duplicate_prisma_cleanup_enabled(config: Any) -> bool:
    value = _get_v18_value(config, "duplicate_prisma_cleanup_enabled", False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _maybe_cleanup_duplicate_prisma(*, cwd: str, config: Any) -> list[str]:
    """NEW-1: remove stale ``apps/api/src/prisma/`` when canonical is populated.

    Returns a list of removed relative paths (for logging). Empty when:
      * the flag is off;
      * the canonical ``apps/api/src/database/`` is missing a required file;
      * the stale directory does not exist.

    Safety: NEVER removes without first confirming that
    ``src/database/prisma.module.ts`` AND ``src/database/prisma.service.ts``
    both exist (and are non-empty) in the canonical location.
    """
    if not _duplicate_prisma_cleanup_enabled(config):
        return []

    workspace = Path(cwd)
    stale_dir = workspace / "apps" / "api" / "src" / "prisma"
    canonical_dir = workspace / "apps" / "api" / "src" / "database"
    if not stale_dir.exists():
        return []
    if not canonical_dir.is_dir():
        return []

    for required in _DUPLICATE_PRISMA_REQUIRED_CANONICAL_FILES:
        candidate = canonical_dir / required
        if not candidate.is_file():
            return []
        try:
            if candidate.stat().st_size == 0:
                return []
        except OSError:
            return []

    removed: list[str] = []
    try:
        import shutil

        for entry in sorted(stale_dir.rglob("*")):
            if entry.is_file():
                try:
                    rel = entry.relative_to(workspace)
                    removed.append(str(rel).replace("\\", "/"))
                except ValueError:  # pragma: no cover — defensive
                    removed.append(str(entry).replace("\\", "/"))
        shutil.rmtree(stale_dir)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("NEW-1 duplicate Prisma cleanup failed: %s", exc)
        return []

    if removed:
        logger.info(
            "NEW-1 duplicate Prisma cleanup removed %d file(s) under %s: %s",
            len(removed),
            "apps/api/src/prisma",
            removed[:5] + (["..."] if len(removed) > 5 else []),
        )
    return removed


def _maybe_sanitize_wave_b_outputs(
    *,
    cwd: str,
    config: Any,
    wave_result: Any,
) -> None:
    """Phase F N-19: post-Wave-B scaffold-ownership sanitization.

    Compares the files Wave B wrote (``wave_result.files_created`` and
    ``files_modified``) against ``docs/SCAFFOLD_OWNERSHIP.md``. Any
    emission at a non-wave-b-owned path becomes an orphan candidate;
    the candidate's OrphanFinding is serialised into an audit finding
    and appended to ``wave_result.findings`` so downstream scorers see
    the encroachment. Report-only (remove_orphans=False) by default —
    orphans surface as MEDIUM/PARTIAL findings, not silent deletions.

    Short-circuits when the flag
    ``v18.wave_b_output_sanitization_enabled`` is False or the
    ownership contract cannot be parsed. Every action is logged.
    """
    try:
        from .wave_b_sanitizer import (
            build_orphan_findings,
            sanitize_wave_b_outputs,
            wave_b_output_sanitization_enabled,
        )
        from .scaffold_runner import load_ownership_contract
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("N-19 sanitizer imports failed: %s", exc)
        return

    if not wave_b_output_sanitization_enabled(config):
        return

    try:
        contract = load_ownership_contract()
    except Exception as exc:
        logger.warning(
            "N-19 sanitizer: could not load ownership contract (%s); "
            "skipping post-Wave-B sanitization.",
            exc,
        )
        return

    created = list(getattr(wave_result, "files_created", []) or [])
    modified = list(getattr(wave_result, "files_modified", []) or [])
    # Some callsites store absolute paths; normalise to workspace-relative
    # so the sanitizer's grep-based consumer scan lines up.
    workspace = Path(cwd)
    emitted: list[str] = []
    for raw in created + modified:
        try:
            path_obj = Path(raw)
            if path_obj.is_absolute():
                try:
                    rel = path_obj.relative_to(workspace)
                    emitted.append(str(rel).replace("\\", "/"))
                    continue
                except ValueError:
                    pass
            emitted.append(str(raw).replace("\\", "/"))
        except Exception:  # pragma: no cover — defensive
            continue

    if not emitted:
        return

    try:
        report = sanitize_wave_b_outputs(
            cwd=cwd,
            contract=contract,
            wave_b_files=emitted,
            config=config,
            remove_orphans=False,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("N-19 sanitizer raised: %s", exc)
        return

    if not report.orphan_findings:
        return

    findings_dicts = build_orphan_findings(report)

    # Append serialised orphan findings to wave_result.findings so the
    # existing audit-report flow picks them up.
    try:
        wave_findings = list(getattr(wave_result, "findings", []) or [])
        wave_findings.extend(findings_dicts)
        wave_result.findings = wave_findings
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "N-19 sanitizer: could not attach orphan findings to "
            "wave_result (%s)",
            exc,
        )

    logger.info(
        "N-19 sanitizer flagged %d orphan Wave-B emission(s)", report.orphan_count,
    )


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


def _wave_idle_timeout_seconds(config: Any | None) -> int:
    value = _get_v18_value(config, "wave_idle_timeout_seconds", 1800)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1800


def _orphan_tool_idle_timeout_seconds(config: Any | None) -> int:
    value = _get_v18_value(config, "orphan_tool_idle_timeout_seconds", 600)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 600


def _wave_watchdog_poll_seconds(config: Any | None) -> int:
    value = _get_v18_value(config, "wave_watchdog_poll_seconds", 30)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 30


def _wave_watchdog_max_retries(config: Any | None) -> int:
    value = _get_v18_value(config, "wave_watchdog_max_retries", 1)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 1


def _sub_agent_idle_timeout_seconds(config: Any | None) -> int:
    value = _get_v18_value(config, "sub_agent_idle_timeout_seconds", 600)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 600


def _orchestrator_model(config: Any | None) -> str:
    orchestrator = getattr(config, "orchestrator", None)
    return str(getattr(orchestrator, "model", "") or "")


def _write_hang_report(
    *,
    cwd: str,
    milestone_id: str,
    wave: str,
    timeout: WaveWatchdogTimeoutError,
) -> str:
    reports_dir = Path(cwd) / ".agent-team" / "hang_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"wave-{wave}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    pending_tool_starts: list[dict[str, Any]] = []
    now_mono = time.monotonic()
    for tool_id, info in timeout.state.pending_tool_starts.items():
        idle_for = max(0, int(now_mono - float(info.get("started_monotonic", now_mono))))
        pending_tool_starts.append({
            "tool_id": tool_id,
            "tool_name": info.get("tool_name", ""),
            "started_at": info.get("started_at", ""),
            "idle_seconds": idle_for,
        })
    payload = {
        "milestone_id": milestone_id,
        "wave": wave,
        "started_at": timeout.state.started_at,
        "last_progress_at": timeout.state.last_progress_at,
        "watchdog_fired_at": timeout.fired_at,
        "idle_timeout_seconds": timeout.timeout_seconds,
        "observed_idle_seconds": timeout.idle_seconds,
        "last_sdk_message_type": timeout.state.last_message_type,
        "last_sdk_tool_name": timeout.state.last_tool_name,
        "recent_sdk_events": timeout.state.recent_events,
        "pending_tool_starts": pending_tool_starts,
        "python_stack": traceback.format_stack(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _oldest_pending_tool_start(
    state: _WaveWatchdogState,
) -> tuple[str, dict[str, Any]] | None:
    if not state.pending_tool_starts:
        return None
    tool_id = min(
        state.pending_tool_starts,
        key=lambda pending_id: float(
            state.pending_tool_starts[pending_id].get("started_monotonic", float("inf"))
        ),
    )
    return tool_id, dict(state.pending_tool_starts[tool_id])


def _effective_wave_idle_timeout_seconds(
    config: Any | None,
    state: _WaveWatchdogState,
) -> int:
    if state.pending_tool_starts:
        return _orphan_tool_idle_timeout_seconds(config)
    return _wave_idle_timeout_seconds(config)


def _build_wave_watchdog_timeout(
    *,
    wave_letter: str,
    state: _WaveWatchdogState,
    config: Any | None,
    role: str = "wave",
    include_role_in_message: bool = False,
) -> WaveWatchdogTimeoutError | None:
    timeout_seconds = _effective_wave_idle_timeout_seconds(config, state)
    idle_seconds = max(0.0, time.monotonic() - state.last_progress_monotonic)
    if idle_seconds < timeout_seconds:
        return None

    pending_tool = _oldest_pending_tool_start(state)
    if pending_tool is not None:
        tool_id, info = pending_tool
        return WaveWatchdogTimeoutError(
            wave_letter,
            state,
            timeout_seconds,
            role=role,
            include_role_in_message=include_role_in_message,
            timeout_kind="orphan-tool",
            orphan_tool_id=tool_id,
            orphan_tool_name=str(info.get("tool_name", "") or state.last_tool_name or ""),
        )

    return WaveWatchdogTimeoutError(
        wave_letter,
        state,
        timeout_seconds,
        role=role,
        include_role_in_message=include_role_in_message,
    )


def _log_orphan_tool_wedge(timeout: WaveWatchdogTimeoutError) -> None:
    if timeout.timeout_kind != "orphan-tool":
        return
    logger.error(
        "[Wave %s] orphan-tool wedge detected on %s (item_id=%s), fail-fast at %ss idle (budget: %ss)",
        timeout.wave,
        timeout.orphan_tool_name or "unknown",
        timeout.orphan_tool_id or "unknown",
        timeout.idle_seconds,
        timeout.timeout_seconds,
    )


def _capture_file_fingerprints(cwd: str) -> dict[str, tuple[int, int]]:
    root = Path(cwd)
    fingerprints: dict[str, tuple[int, int]] = {}
    for file_path in _checkpoint_file_iter(root):
        try:
            stat = file_path.stat()
        except (OSError, PermissionError):
            continue
        fingerprints[file_path.relative_to(root).as_posix()] = (
            int(stat.st_mtime_ns),
            int(stat.st_size),
        )
    return fingerprints


def _count_touched_files(
    baseline_fingerprints: dict[str, tuple[int, int]],
    cwd: str,
) -> int:
    current = _capture_file_fingerprints(cwd)
    touched: set[str] = set()
    for path, fingerprint in current.items():
        if baseline_fingerprints.get(path) != fingerprint:
            touched.add(path)
    for path in baseline_fingerprints:
        if path not in current:
            touched.add(path)
    return len(touched)


async def _log_wave_heartbeats(
    *,
    task: asyncio.Task[Any],
    state: _WaveWatchdogState,
    wave_letter: str,
    cwd: str,
    baseline_fingerprints: dict[str, tuple[int, int]],
) -> None:
    heartbeat_interval_seconds = 60
    summary_interval_seconds = 300
    elapsed_seconds = 0

    while not task.done():
        await asyncio.sleep(heartbeat_interval_seconds)
        if task.done():
            return
        elapsed_seconds += heartbeat_interval_seconds
        idle_seconds = int(max(0, time.monotonic() - state.last_progress_monotonic))
        files_touched = _count_touched_files(baseline_fingerprints, cwd)
        last_activity = state.last_tool_name or state.last_message_type or "unknown"
        message = (
            f"[Wave {wave_letter}] active - last {last_activity} {idle_seconds}s ago, "
            f"{files_touched} files touched so far, cumulative SDK calls: {max(1, state.sdk_call_count)}"
        )
        print_info(message)
        logger.info(
            "[Wave %s] active - last %s %ss ago, %s files touched so far, cumulative SDK calls: %s",
            wave_letter,
            last_activity,
            idle_seconds,
            files_touched,
            max(1, state.sdk_call_count),
        )
        if elapsed_seconds % summary_interval_seconds == 0:
            summary_message = (
                f"[Wave {wave_letter}] summary - last progress={state.last_progress_at}, "
                f"last message={state.last_message_type or 'unknown'}, "
                f"last tool={state.last_tool_name or ''}, files touched={files_touched}, "
                f"cumulative SDK calls={max(1, state.sdk_call_count)}, "
                f"progress events={state.progress_event_count}"
            )
            print_info(summary_message)
            logger.info(
                "[Wave %s] summary - last progress=%s, last message=%s, last tool=%s, files touched=%s, cumulative SDK calls=%s, progress events=%s",
                wave_letter,
                state.last_progress_at,
                state.last_message_type or "unknown",
                state.last_tool_name or "",
                files_touched,
                max(1, state.sdk_call_count),
                state.progress_event_count,
            )


async def _invoke_wave_sdk_with_watchdog(
    *,
    execute_sdk_call: Callable[..., Any],
    prompt: str,
    wave_letter: str,
    config: Any,
    cwd: str,
    milestone: Any,
) -> tuple[float, _WaveWatchdogState]:
    state = _WaveWatchdogState()
    timeout_seconds = _wave_idle_timeout_seconds(config)
    poll_seconds = _wave_watchdog_poll_seconds(config)
    state.record_progress(message_type="sdk_call_started", tool_name="")
    baseline_fingerprints = _capture_file_fingerprints(cwd)

    task = asyncio.create_task(
        _invoke(
            execute_sdk_call,
            prompt=prompt,
            wave=wave_letter,
            milestone=milestone,
            config=config,
            cwd=cwd,
            role="wave",
            progress_callback=state.record_progress,
        )
    )
    heartbeat_task = asyncio.create_task(
        _log_wave_heartbeats(
            task=task,
            state=state,
            wave_letter=wave_letter,
            cwd=cwd,
            baseline_fingerprints=baseline_fingerprints,
        )
    )

    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=poll_seconds)
            if task in done:
                return float(task.result() or 0.0), state
            timeout = _build_wave_watchdog_timeout(
                wave_letter=wave_letter,
                state=state,
                config=config,
            )
            if timeout is not None:
                # Interrupt-based recovery: if client is available and this is the
                # first orphan, attempt client.interrupt() + corrective prompt
                # instead of hard-cancelling the task.
                if state.client and state.interrupt_count == 0:
                    orphan_threshold = float(_orphan_tool_idle_timeout_seconds(config))
                    orphan_info = await state.interrupt_oldest_orphan(orphan_threshold)
                    if orphan_info:
                        logger.warning(
                            "[Wave %s] interrupt fired for orphan tool %s — "
                            "sending corrective prompt and resuming",
                            wave_letter,
                            orphan_info.get("tool_name", "unknown"),
                        )
                        state.record_progress(
                            message_type="interrupt_recovery",
                            tool_name=orphan_info.get("tool_name", ""),
                        )
                        # Let the task continue — the client session survives the
                        # interrupt and _execute_single_wave_sdk will re-iterate.
                        continue
                # Second orphan or no client: hard cancel (containment).
                _log_orphan_tool_wedge(timeout)
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
                raise timeout
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        if not task.done():
            task.cancel()


async def _invoke_provider_wave_with_watchdog(
    *,
    execute_sdk_call: Callable[..., Any],
    prompt: str,
    wave_letter: str,
    config: Any,
    cwd: str,
    milestone: Any,
    provider_routing: dict[str, Any],
    force_claude_fallback_reason: str | None = None,
    retry_count_override: int | None = None,
) -> tuple[dict[str, Any], _WaveWatchdogState]:
    from .provider_router import execute_wave_with_provider

    state = _WaveWatchdogState()
    timeout_seconds = _wave_idle_timeout_seconds(config)
    poll_seconds = _wave_watchdog_poll_seconds(config)
    state.record_progress(message_type="sdk_call_started", tool_name="")
    baseline_fingerprints = _capture_file_fingerprints(cwd)

    task = asyncio.create_task(
        execute_wave_with_provider(
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
            progress_callback=state.record_progress,
            force_claude_fallback_reason=force_claude_fallback_reason,
            retry_count_override=retry_count_override,
        )
    )
    heartbeat_task = asyncio.create_task(
        _log_wave_heartbeats(
            task=task,
            state=state,
            wave_letter=wave_letter,
            cwd=cwd,
            baseline_fingerprints=baseline_fingerprints,
        )
    )

    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=poll_seconds)
            if task in done:
                return dict(task.result() or {}), state
            timeout = _build_wave_watchdog_timeout(
                wave_letter=wave_letter,
                state=state,
                config=config,
            )
            if timeout is not None:
                _log_orphan_tool_wedge(timeout)
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
                raise timeout
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        if not task.done():
            task.cancel()


async def _invoke_sdk_sub_agent_with_watchdog(
    *,
    execute_sdk_call: Callable[..., Any],
    prompt: str,
    wave_letter: str,
    role: str,
    config: Any,
    cwd: str,
    milestone: Any,
) -> tuple[float, _WaveWatchdogState]:
    state = _WaveWatchdogState()
    timeout_seconds = _sub_agent_idle_timeout_seconds(config)
    poll_seconds = _wave_watchdog_poll_seconds(config)
    state.record_progress(message_type="sdk_call_started", tool_name="")

    task = asyncio.create_task(
        _invoke(
            execute_sdk_call,
            prompt=prompt,
            wave=wave_letter,
            milestone=milestone,
            config=config,
            cwd=cwd,
            role=role,
            progress_callback=state.record_progress,
        )
    )

    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=poll_seconds)
            if task in done:
                return float(task.result() or 0.0), state
            if time.monotonic() - state.last_progress_monotonic > timeout_seconds:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
                raise WaveWatchdogTimeoutError(
                    wave_letter,
                    state,
                    timeout_seconds,
                    role=role,
                    include_role_in_message=True,
                )
    finally:
        if not task.done():
            task.cancel()


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


def _stack_violation_to_finding(violation: Any) -> WaveFinding:
    severity_map = {"critical": "HIGH", "high": "HIGH", "warning": "MEDIUM", "info": "LOW"}
    raw_severity = str(getattr(violation, "severity", "HIGH") or "HIGH").strip().lower()
    return WaveFinding(
        code=str(getattr(violation, "code", "") or ""),
        severity=severity_map.get(raw_severity, "HIGH"),
        file=str(getattr(violation, "file_path", "") or ""),
        line=int(getattr(violation, "line", 0) or 0),
        message=str(getattr(violation, "message", "") or ""),
    )


def _wave_contract_conflict_path(cwd: str) -> Path:
    return Path(cwd) / "WAVE_A_CONTRACT_CONFLICT.md"


def _read_wave_a_contract_conflict(cwd: str) -> str:
    path = _wave_contract_conflict_path(cwd)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


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
        # D-02: decide skip-vs-block based on a structural flag set by
        # ``start_docker_for_probing``, NOT on substring matching the error
        # text. The legacy string match leaked: "never became healthy" and
        # the new "host port unbound" diagnostic both classified as
        # infra-missing, silently turning real failures into a green wave.
        #
        # ``infra_missing=True`` is set ONLY when the host genuinely lacks
        # the infrastructure to probe (no Docker, no compose file, no
        # external app). Anything else — containers up but app not healthy,
        # host-port binding conflict, build failure — is a real signal and
        # must block the wave so runtime_verification can record
        # ``health=blocked`` downstream. Set v18.live_endpoint_check=false
        # to opt out entirely.
        if docker_ctx.infra_missing:
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
            await _invoke_sdk_sub_agent_with_watchdog(
                execute_sdk_call=execute_sdk_call,
                prompt=fix_prompt,
                wave_letter="B",
                role="probe_fix",
                milestone=milestone,
                config=config,
                cwd=cwd,
            )
            if not await reset_db_and_seed(cwd):
                return False, "DB reset/seed failed before Wave B probe retry", []
            manifest = await execute_probes(manifest, docker_ctx, cwd)
        except WaveWatchdogTimeoutError as exc:
            hang_report_path = _write_hang_report(
                cwd=cwd,
                milestone_id=str(getattr(milestone, "id", "") or ""),
                wave="B",
                timeout=exc,
            )
            message = f"Wave B probe fix sub-agent timed out: {exc}"
            logger.error("Wave B.1 probe fix sub-agent timed out: %s", exc)
            return (
                False,
                message,
                [
                    WaveFinding(
                        code="PROBE-FIX-TIMEOUT",
                        severity="HIGH",
                        file="",
                        line=0,
                        message=f"{message} Hang report: {hang_report_path}",
                    )
                ],
            )
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
        provider_model=_orchestrator_model(config),
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
        cost, watchdog_state = await _invoke_sdk_sub_agent_with_watchdog(
            execute_sdk_call=execute_sdk_call,
            prompt=str(prompt or ""),
            wave_letter="T",
            role="wave",
            milestone=milestone,
            config=config,
            cwd=cwd,
        )
        wave_result.cost = float(cost or 0.0)
        wave_result.last_sdk_message_type = watchdog_state.last_message_type
        wave_result.last_sdk_tool_name = watchdog_state.last_tool_name
    except WaveWatchdogTimeoutError as exc:
        wave_result.success = False
        wave_result.wave_timed_out = True
        wave_result.wave_watchdog_fired_at = exc.fired_at
        wave_result.last_sdk_message_type = exc.state.last_message_type
        wave_result.last_sdk_tool_name = exc.state.last_tool_name
        wave_result.hang_report_path = _write_hang_report(
            cwd=cwd,
            milestone_id=str(getattr(milestone, "id", "") or ""),
            wave="T",
            timeout=exc,
        )
        wave_result.error_message = f"Wave T SDK call timed out: {exc}"
        wave_result.findings.append(
            WaveFinding(
                code="WAVE-T-TIMEOUT",
                severity="HIGH",
                file="",
                line=0,
                message=wave_result.error_message,
            )
        )
        logger.error("Wave T timed out for %s: %s", getattr(milestone, "id", ""), exc)
        wave_result.duration_seconds = (datetime.now(timezone.utc) - start).total_seconds()
        return wave_result
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
            fix_attempt_status = "completed"
            try:
                cost, _watchdog_state = await _invoke_sdk_sub_agent_with_watchdog(
                    execute_sdk_call=execute_sdk_call,
                    prompt=fix_prompt,
                    wave_letter="T",
                    role="test_fix",
                    milestone=milestone,
                    config=config,
                    cwd=cwd,
                )
                wave_result.cost += float(cost or 0.0)
            except WaveWatchdogTimeoutError as exc:
                fix_attempt_status = "timed out"
                wave_result.wave_timed_out = True
                wave_result.wave_watchdog_fired_at = exc.fired_at
                wave_result.last_sdk_message_type = exc.state.last_message_type
                wave_result.last_sdk_tool_name = exc.state.last_tool_name
                wave_result.hang_report_path = _write_hang_report(
                    cwd=cwd,
                    milestone_id=str(getattr(milestone, "id", "") or ""),
                    wave="T",
                    timeout=exc,
                )
                wave_result.findings.append(
                    WaveFinding(
                        code="WAVE-T-FIX-TIMEOUT",
                        severity="MEDIUM",
                        file="",
                        line=0,
                        message=f"Wave T fix iteration {iteration + 1} timed out: {exc}",
                    )
                )
                logger.warning(
                    "Wave T fix iteration %s %s: %s",
                    iteration + 1,
                    fix_attempt_status,
                    exc,
                )
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


async def _dispatch_codex_compile_fix(
    prompt: str,
    *,
    cwd: str,
    provider_routing: Any,
    v18: Any,
) -> tuple[bool, float, str]:
    """Dispatch a compile-fix prompt to Codex via the shared transport.

    Phase G Slice 2b — mirrors ``cli._dispatch_codex_fix`` but lives in
    wave_executor to avoid a cross-module dependency on cli (which would
    import wave_executor already). Applies the timeout / reasoning-effort
    from ``v18.codex_fix_*`` settings.

    Returns ``(success, cost_usd, error_reason)``. On failure the caller
    MUST fall back to the Claude SDK path (the existing sub-agent
    watchdog call) unchanged.
    """
    from dataclasses import replace as _dc_replace

    codex_mod = provider_routing.get("codex_transport") if isinstance(provider_routing, dict) else None
    base_codex_config = provider_routing.get("codex_config") if isinstance(provider_routing, dict) else None
    codex_home = provider_routing.get("codex_home") if isinstance(provider_routing, dict) else None
    if codex_mod is None or base_codex_config is None:
        return False, 0.0, "provider_routing missing codex_transport/codex_config"

    timeout_s = int(getattr(v18, "codex_fix_timeout_seconds", 900) or 900)
    effort = str(getattr(v18, "codex_fix_reasoning_effort", "high") or "high")
    try:
        fix_codex_config = _dc_replace(
            base_codex_config,
            timeout_seconds=timeout_s,
            reasoning_effort=effort,
        )
    except Exception:
        fix_codex_config = base_codex_config

    try:
        codex_result = await codex_mod.execute_codex(
            prompt,
            cwd,
            config=fix_codex_config,
            codex_home=codex_home,
        )
    except Exception as exc:
        return False, 0.0, f"codex dispatch raised: {exc}"

    cost = float(getattr(codex_result, "cost_usd", 0.0) or 0.0)
    if not getattr(codex_result, "success", False):
        err = (getattr(codex_result, "error", "") or "")[:200]
        return False, cost, f"codex failed (exit={getattr(codex_result, 'exit_code', '?')}): {err}"

    return True, cost, ""


def _build_compile_fix_prompt(
    errors: list[dict[str, Any]],
    wave_letter: str,
    milestone: Any,
    *,
    iteration: int = 0,
    max_iterations: int = 3,
    previous_error_count: int | None = None,
    use_codex_shell: bool = False,
    build_command: str = "",
) -> str:
    """Build the compile-fix prompt.

    Phase G Slice 2b: when ``use_codex_shell=True`` (caller gated on
    ``v18.compile_fix_codex_enabled`` AND provider routing active), emit
    a Codex-native shell prompt per investigation report §5.8 with the
    LOCKED ``_ANTI_BAND_AID_FIX_RULES`` (cli.py:6183-6208) inlined
    verbatim. Default ``use_codex_shell=False`` preserves the legacy
    Claude-shaped prompt byte-for-byte.
    """
    current_count = len(errors)

    if use_codex_shell:
        # Lazy import of _ANTI_BAND_AID_FIX_RULES from cli to avoid a
        # wave_executor → cli circular import at module load. At call
        # time cli is fully loaded. The block is LOCKED — passed into
        # build_codex_compile_fix_prompt verbatim with no mutation.
        from .cli import _ANTI_BAND_AID_FIX_RULES
        from .codex_fix_prompts import build_codex_compile_fix_prompt

        return build_codex_compile_fix_prompt(
            errors=errors,
            wave_letter=wave_letter,
            milestone_id=str(getattr(milestone, "id", "") or ""),
            milestone_title=str(getattr(milestone, "title", "") or ""),
            iteration=iteration,
            max_iterations=max_iterations,
            previous_error_count=previous_error_count,
            current_error_count=current_count,
            build_command=build_command,
            anti_band_aid_rules=_ANTI_BAND_AID_FIX_RULES,
        )

    lines = [
        f"[PHASE: WAVE {wave_letter} COMPILE FIX]",
        f"Milestone: {getattr(milestone, 'id', '')} - {getattr(milestone, 'title', '')}",
    ]
    # A-10: Iteration context
    if iteration > 0:
        progress = ""
        if previous_error_count is not None:
            if current_count < previous_error_count:
                progress = f" Previous iteration had {previous_error_count} errors, now {current_count}."
            elif current_count == previous_error_count:
                progress = f" Previous iteration had {previous_error_count} errors (unchanged). Try a different approach."
            else:
                progress = f" Previous iteration had {previous_error_count} errors, now {current_count} (increased). Revert problematic changes."
        lines.append(f"Compile fix iteration {iteration + 1}/{max_iterations}.{progress}")
        lines.append("")
    lines.extend([
        "",
        "Fix the compile errors below without introducing unrelated changes.",
        "Read each referenced file before editing.",
        "Do not delete working code to silence the compiler.",
        "",
        "[ERRORS]",
    ])
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


def _build_frontend_hallucination_fix_prompt(
    violations: list[Any],
    milestone: Any,
    allowed_locales: list[str],
) -> str:
    lines = [
        "[PHASE: WAVE D FRONTEND HALLUCINATION FIX]",
        f"Milestone: {getattr(milestone, 'id', '')} - {getattr(milestone, 'title', '')}",
        "",
        "Fix the deterministic frontend hallucination violations below before Wave D.5 runs.",
        "Read each referenced frontend file before editing.",
        "Do NOT change API calls, routing, backend contracts, or state-management logic.",
        "",
        "[PROJECT LOCALES]",
        ", ".join(allowed_locales) if allowed_locales else "(not declared)",
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
        "- For LOCALE-HALLUCINATE-001: keep locale unions aligned to the declared locales only.",
        "- For FONT-SUBSET-001: remove invalid Google Font subsets or switch to a font family that actually supports the required script.",
        "- Preserve the existing visual design intent and compile cleanly after the fix.",
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
        max_retries = _wave_watchdog_max_retries(config)
        force_claude_fallback_reason: str | None = None
        for attempt in range(max_retries + 1):
            try:
                meta, watchdog_state = await _invoke_provider_wave_with_watchdog(
                    execute_sdk_call=execute_sdk_call,
                    prompt=prompt,
                    wave_letter=wave_letter,
                    config=config,
                    cwd=cwd,
                    milestone=milestone,
                    provider_routing=provider_routing,
                    force_claude_fallback_reason=force_claude_fallback_reason,
                    retry_count_override=attempt,
                )
                wave_result.cost = float(meta.get("cost", 0.0))
                wave_result.provider = meta.get("provider", "")
                wave_result.provider_model = meta.get("provider_model", "")
                wave_result.fallback_used = meta.get("fallback_used", False)
                wave_result.fallback_reason = meta.get("fallback_reason", "")
                if wave_result.fallback_used and force_claude_fallback_reason is not None:
                    wave_result.retry_count = attempt
                else:
                    wave_result.retry_count = meta.get("retry_count", attempt)
                wave_result.input_tokens = meta.get("input_tokens", 0)
                wave_result.output_tokens = meta.get("output_tokens", 0)
                wave_result.reasoning_tokens = meta.get("reasoning_tokens", 0)
                wave_result.last_sdk_message_type = watchdog_state.last_message_type
                wave_result.last_sdk_tool_name = watchdog_state.last_tool_name
                wave_result.error_message = ""
                # Codex path may report file changes; override only when present.
                if meta.get("files_created"):
                    wave_result.files_created = meta["files_created"]
                if meta.get("files_modified"):
                    wave_result.files_modified = meta["files_modified"]
                return wave_result
            except WaveWatchdogTimeoutError as exc:
                wave_result.wave_timed_out = True
                wave_result.wave_watchdog_fired_at = exc.fired_at
                wave_result.last_sdk_message_type = exc.state.last_message_type
                wave_result.last_sdk_tool_name = exc.state.last_tool_name
                wave_result.retry_count = attempt
                wave_result.hang_report_path = _write_hang_report(
                    cwd=cwd,
                    milestone_id=str(getattr(milestone, "id", "") or ""),
                    wave=wave_letter,
                    timeout=exc,
                )
                wave_result.error_message = str(exc)
                logger.error(
                    "Wave %s timed out for %s: %s",
                    wave_letter,
                    getattr(milestone, "id", ""),
                    exc,
                )
                if attempt >= max_retries:
                    wave_result.success = False
                    return wave_result
                force_claude_fallback_reason = (
                    f"Codex watchdog wedge detected; Claude fallback engaged on retry: {exc}"
                )
            except Exception as exc:
                wave_result.success = False
                if force_claude_fallback_reason is not None:
                    wave_result.error_message = (
                        f"{force_claude_fallback_reason}; Claude fallback failed: {exc}"
                    )
                else:
                    wave_result.error_message = str(exc)
                logger.error(
                    "Wave %s provider routing failed for %s: %s",
                    wave_letter, getattr(milestone, "id", ""), exc,
                )
                return wave_result

    # --- Existing Claude-only path (unchanged) ---
    wave_result.provider = "claude"
    max_retries = _wave_watchdog_max_retries(config)
    for attempt in range(max_retries + 1):
        try:
            cost, watchdog_state = await _invoke_wave_sdk_with_watchdog(
                execute_sdk_call=execute_sdk_call,
                prompt=prompt,
                wave_letter=wave_letter,
                config=config,
                cwd=cwd,
                milestone=milestone,
            )
            wave_result.cost = float(cost or 0.0)
            wave_result.retry_count = attempt
            wave_result.last_sdk_message_type = watchdog_state.last_message_type
            wave_result.last_sdk_tool_name = watchdog_state.last_tool_name
            return wave_result
        except WaveWatchdogTimeoutError as exc:
            wave_result.wave_timed_out = True
            wave_result.wave_watchdog_fired_at = exc.fired_at
            wave_result.last_sdk_message_type = exc.state.last_message_type
            wave_result.last_sdk_tool_name = exc.state.last_tool_name
            wave_result.retry_count = attempt
            wave_result.hang_report_path = _write_hang_report(
                cwd=cwd,
                milestone_id=str(getattr(milestone, "id", "") or ""),
                wave=wave_letter,
                timeout=exc,
            )
            wave_result.error_message = str(exc)
            logger.error(
                "Wave %s timed out for %s: %s",
                wave_letter,
                getattr(milestone, "id", ""),
                exc,
            )
            if attempt >= max_retries:
                wave_result.success = False
                return wave_result
        except Exception as exc:  # pragma: no cover - exercised via tests with stubs
            wave_result.success = False
            wave_result.error_message = str(exc)
            logger.error("Wave %s failed for %s: %s", wave_letter, getattr(milestone, "id", ""), exc)
            return wave_result
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


def _format_plan_review_feedback(findings: list[dict[str, Any]]) -> str:
    """Render A.5 CRITICAL findings as a ``[PLAN REVIEW FEEDBACK]`` block.

    Used by GATE 8 enforcement to thread A.5 findings into the Wave A
    rerun prompt via ``stack_contract_rejection_context``. Returns an
    empty string when *findings* is empty so the Wave A prompt builder
    treats the context slot as "no rejection" and emits the normal
    prompt.
    """
    if not findings:
        return ""
    lines = ["[PLAN REVIEW FEEDBACK]"]
    lines.append(
        "Wave A.5 (plan reviewer) found the following CRITICAL issues in "
        "the plan you previously produced. Address each one in the rewrite "
        "below. Do NOT re-emit the previous plan verbatim."
    )
    for i, finding in enumerate(findings, start=1):
        if not isinstance(finding, dict):
            continue
        category = str(finding.get("category", "") or "").strip() or "uncertain"
        ref = str(finding.get("ref", "") or "").strip() or "(no ref)"
        issue = str(finding.get("issue", "") or "").strip() or "(no issue text)"
        fix = str(finding.get("suggested_fix", "") or "").strip()
        lines.append(f"\n{i}. [{category}] {ref}")
        lines.append(f"   Issue: {issue}")
        if fix:
            lines.append(f"   Suggested fix: {fix}")
    lines.append("")
    return "\n".join(lines)


async def _execute_wave_a5(
    *,
    milestone: Any,
    config: Any,
    cwd: str,
    template: str,
    wave_artifacts: dict[str, dict[str, Any]],
    provider_routing: Any | None = None,
) -> WaveResult:
    """Execute Wave A.5 — plan review (Codex, reasoning_effort=medium).

    Thin WaveResult adapter over ``wave_a5_t5.execute_wave_a5``. Skipped when
    ``v18.wave_a5_enabled=False`` or the milestone is small (§4.8 skip
    conditions). On success, the verdict + findings are persisted to
    ``.agent-team/milestones/{id}/WAVE_A5_REVIEW.json`` and GATE 8 in the
    orchestrator decides whether to loop back to Wave A.
    """
    from . import wave_a5_t5

    out = await wave_a5_t5.execute_wave_a5(
        milestone=milestone,
        config=config,
        cwd=cwd,
        template=template,
        wave_artifacts=wave_artifacts,
        provider_routing=provider_routing,
    )
    result = WaveResult(
        wave="A5",
        provider="codex",
        timestamp=_now_iso(),
        compile_skipped=True,
        compile_passed=True,
        success=bool(out.get("success", True)),
        artifact_path=str(out.get("artifact_path", "") or ""),
        error_message=str(out.get("error_message", "") or ""),
        cost=float(out.get("cost", 0.0) or 0.0),
        input_tokens=int(out.get("input_tokens", 0) or 0),
        output_tokens=int(out.get("output_tokens", 0) or 0),
        reasoning_tokens=int(out.get("reasoning_tokens", 0) or 0),
        duration_seconds=float(out.get("duration_seconds", 0.0) or 0.0),
    )
    return result


async def _execute_wave_t5(
    *,
    milestone: Any,
    config: Any,
    cwd: str,
    wave_artifacts: dict[str, dict[str, Any]],
    provider_routing: Any | None = None,
) -> WaveResult:
    """Execute Wave T.5 — test-gap audit (Codex, reasoning_effort=high).

    Thin WaveResult adapter over ``wave_a5_t5.execute_wave_t5``. Skipped when
    ``v18.wave_t5_enabled=False`` or Wave T produced no test files. Persists
    the gap list to ``.agent-team/milestones/{id}/WAVE_T5_GAPS.json`` for
    GATE 9 (loop back to Wave T iteration 2) + Wave E + TEST_AUDITOR to
    consume.
    """
    from . import wave_a5_t5

    out = await wave_a5_t5.execute_wave_t5(
        milestone=milestone,
        config=config,
        cwd=cwd,
        wave_artifacts=wave_artifacts,
        provider_routing=provider_routing,
    )
    result = WaveResult(
        wave="T5",
        provider="codex",
        timestamp=_now_iso(),
        compile_skipped=True,
        compile_passed=True,
        success=bool(out.get("success", True)),
        artifact_path=str(out.get("artifact_path", "") or ""),
        error_message=str(out.get("error_message", "") or ""),
        cost=float(out.get("cost", 0.0) or 0.0),
        input_tokens=int(out.get("input_tokens", 0) or 0),
        output_tokens=int(out.get("output_tokens", 0) or 0),
        reasoning_tokens=int(out.get("reasoning_tokens", 0) or 0),
        duration_seconds=float(out.get("duration_seconds", 0.0) or 0.0),
    )
    return result


def _detect_structural_issues(cwd: str, wave_letter: str) -> list[dict[str, Any]]:
    """D-15: Inspect package.json and tsconfig.json for structural issues
    that per-file compile-fix diffs cannot resolve.

    Returns a list of issue dicts: [{"type": "missing_dep", "detail": "@types/react", "file": "package.json"}, ...]
    """
    issues: list[dict[str, Any]] = []
    project_root = Path(cwd)

    # Check package.json for referenced but missing type packages
    pkg_path = project_root / "package.json"
    if not pkg_path.is_file():
        # Also check apps/web/package.json, apps/api/package.json
        for sub in ("apps/web", "apps/api", "packages/web", "packages/api"):
            candidate = project_root / sub / "package.json"
            if candidate.is_file():
                pkg_path = candidate
                break

    if pkg_path.is_file():
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
            # Check if package.json is valid
            if not isinstance(pkg, dict):
                issues.append({"type": "invalid_package_json", "detail": "package.json is not a valid JSON object", "file": str(pkg_path.relative_to(project_root))})
        except (json.JSONDecodeError, OSError) as exc:
            issues.append({"type": "invalid_package_json", "detail": str(exc), "file": str(pkg_path.relative_to(project_root))})

    # Check tsconfig.json exists and is valid
    tsconfig_path = project_root / "tsconfig.json"
    if not tsconfig_path.is_file():
        for sub in ("apps/web", "apps/api"):
            candidate = project_root / sub / "tsconfig.json"
            if candidate.is_file():
                tsconfig_path = candidate
                break

    if tsconfig_path.is_file():
        try:
            content = tsconfig_path.read_text(encoding="utf-8")
            # tsconfig allows comments and trailing commas — strip them for validation
            # Just verify it's loadable; detailed path validation is beyond scope
            stripped = re.sub(r'//.*?$|/\*.*?\*/', '', content, flags=re.MULTILINE | re.DOTALL)
            stripped = re.sub(r',\s*([}\]])', r'\1', stripped)
            tsconfig = json.loads(stripped)
            if not isinstance(tsconfig, dict):
                issues.append({"type": "invalid_tsconfig", "detail": "tsconfig.json is not a valid JSON object", "file": str(tsconfig_path.relative_to(project_root))})
        except (json.JSONDecodeError, OSError):
            # tsconfig parsing is best-effort; don't block on comment-stripping failures
            pass

    return issues


def _build_structural_fix_prompt(issues: list[dict[str, Any]], wave_letter: str, milestone: Any) -> str:
    """D-15: Build a prompt for fixing structural issues before per-file compile loop."""
    lines = [
        f"[PHASE: WAVE {wave_letter} STRUCTURAL FIX]",
        f"Milestone: {getattr(milestone, 'id', '')} - {getattr(milestone, 'title', '')}",
        "",
        "Fix the STRUCTURAL issues below BEFORE any per-file compile fixes.",
        "These are project-level configuration problems that per-file diffs cannot resolve.",
        "",
        "[STRUCTURAL ISSUES]",
    ]
    for issue in issues[:10]:
        lines.append(f"- [{issue['type']}] {issue.get('file', '?')}: {issue['detail']}")
    lines.extend([
        "",
        "Fix each structural issue. For missing dependencies, add them to package.json.",
        "For invalid configs, fix the JSON structure.",
        "Do NOT make per-file source code changes — only fix configuration/dependency issues.",
    ])
    return "\n".join(lines)


async def _run_wave_compile(
    run_compile_check: Callable[..., Any] | None,
    execute_sdk_call: Callable[..., Any] | None,
    wave_letter: str,
    template: str,
    config: Any,
    cwd: str,
    milestone: Any,
    *,
    fallback_used: bool = False,
    provider_routing: Any | None = None,
) -> CompileCheckResult:
    """Drive compile-and-fix for a wave.

    Phase G Slice 2b: when ``v18.compile_fix_codex_enabled=True`` AND
    ``provider_routing`` is supplied, fix dispatches route to Codex
    ``reasoning_effort=high`` with a flat Codex shell prompt (LOCKED
    anti-band-aid block inherited verbatim). Claude SDK path remains the
    fallback on Codex failure and the default when the flag is off.
    """
    if run_compile_check is None:
        return CompileCheckResult(passed=True)

    # D-15: Structural triage before per-file loop
    if execute_sdk_call is not None:
        structural_issues = _detect_structural_issues(cwd, wave_letter)
        if structural_issues:
            logger.info(
                "Wave %s compile: %d structural issue(s) detected, fixing before per-file loop",
                wave_letter, len(structural_issues),
            )
            try:
                structural_prompt = _build_structural_fix_prompt(structural_issues, wave_letter, milestone)
                await _invoke_sdk_sub_agent_with_watchdog(
                    execute_sdk_call=execute_sdk_call,
                    prompt=structural_prompt,
                    wave_letter=wave_letter,
                    role="compile_fix",
                    milestone=milestone,
                    config=config,
                    cwd=cwd,
                )
            except Exception as exc:
                logger.warning("Structural fix sub-agent failed for wave %s: %s", wave_letter, exc)

    # A-10: Configurable iteration cap — more iterations for fallback path
    max_iterations = 5 if fallback_used else 3
    # Phase G Slice 3d: merged Wave D enforces a tighter compile-fix cap
    # (wave_d_compile_fix_max_attempts, default 2). When the cap is exhausted
    # the caller falls back to the legacy D+D5 path via the D5 rollback
    # site below — we want fewer retries here so the rollback decision
    # happens faster.
    if wave_letter == "D" and _get_v18_value(config, "wave_d_merged_enabled", False):
        merged_cap = _get_v18_value(config, "wave_d_compile_fix_max_attempts", 2)
        try:
            merged_cap_int = int(merged_cap)
        except (TypeError, ValueError):
            merged_cap_int = 2
        if merged_cap_int > 0:
            max_iterations = merged_cap_int
    initial_error_count = 0
    fix_cost = 0.0
    error_counts: list[int] = []

    for iteration in range(max_iterations):
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
        current_error_count = len(compile_result.errors)
        error_counts.append(current_error_count)

        if iteration == 0:
            initial_error_count = compile_result.initial_error_count
            if initial_error_count == 0 and compile_result.errors:
                initial_error_count = current_error_count
            compile_result.initial_error_count = initial_error_count

        if compile_result.passed:
            compile_result.iterations = iteration + 1
            compile_result.initial_error_count = initial_error_count
            compile_result.fix_cost = fix_cost
            return compile_result

        if execute_sdk_call is None or iteration >= max_iterations - 1:
            compile_result.iterations = iteration + 1
            compile_result.initial_error_count = initial_error_count
            compile_result.fix_cost = fix_cost
            return compile_result

        # A-10: Enhanced prompt with iteration context
        previous_count = error_counts[-2] if len(error_counts) > 1 else None

        # Phase G Slice 2b: route compile-fix to Codex `high` when flag on.
        v18 = getattr(config, "v18", None)
        use_codex = bool(
            v18 is not None
            and getattr(v18, "compile_fix_codex_enabled", False)
            and provider_routing
        )
        codex_ok = False
        if use_codex:
            codex_prompt = _build_compile_fix_prompt(
                compile_result.errors, wave_letter, milestone,
                iteration=iteration,
                max_iterations=max_iterations,
                previous_error_count=previous_count,
                use_codex_shell=True,
                build_command=str(getattr(milestone, "build_command", "") or ""),
            )
            try:
                codex_ok, codex_cost, reason = await _dispatch_codex_compile_fix(
                    codex_prompt,
                    cwd=cwd,
                    provider_routing=provider_routing,
                    v18=v18,
                )
                fix_cost += codex_cost
                if not codex_ok:
                    logger.warning(
                        "Wave %s compile-fix: Codex dispatch failed (%s); falling back to Claude",
                        wave_letter, reason,
                    )
            except Exception as exc:
                logger.warning(
                    "Wave %s compile-fix: Codex path raised (%s); falling back to Claude",
                    wave_letter, exc,
                )
                codex_ok = False

        if not codex_ok:
            fix_prompt = _build_compile_fix_prompt(
                compile_result.errors, wave_letter, milestone,
                iteration=iteration,
                max_iterations=max_iterations,
                previous_error_count=previous_count,
            )
            fix_attempt_status = "completed"
            try:
                fix_cost_delta, _watchdog_state = await _invoke_sdk_sub_agent_with_watchdog(
                    execute_sdk_call=execute_sdk_call,
                    prompt=fix_prompt,
                    wave_letter=wave_letter,
                    role="compile_fix",
                    milestone=milestone,
                    config=config,
                    cwd=cwd,
                )
                fix_cost += float(fix_cost_delta or 0.0)
            except WaveWatchdogTimeoutError as exc:
                fix_attempt_status = "timed out"
                _write_hang_report(
                    cwd=cwd,
                    milestone_id=str(getattr(milestone, "id", "") or ""),
                    wave=wave_letter,
                    timeout=exc,
                )
                logger.warning(
                    "Compile fix sub-agent %s for wave %s: %s",
                    fix_attempt_status,
                    wave_letter,
                    exc,
                )
            except Exception as exc:
                logger.warning("Compile fix sub-agent failed for wave %s: %s", wave_letter, exc)

    return CompileCheckResult(
        passed=False,
        iterations=max_iterations,
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
    provider_routing: Any | None = None,
) -> _DeterministicGuardResult:
    """Run DTO contract scans after Wave B compiles and auto-fix if needed.

    Phase G Slice 2b: ``provider_routing`` is threaded through to the
    downstream ``_run_wave_compile`` recompile so that compile-fix
    dispatches route to Codex when ``v18.compile_fix_codex_enabled=True``.
    The DTO contract fix itself continues to use the Claude sub-agent
    watchdog — DTO violations are deterministic rewrites best handled by
    Claude per Wave 1c §5.
    """
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
            fix_cost_delta, _watchdog_state = await _invoke_sdk_sub_agent_with_watchdog(
                execute_sdk_call=execute_sdk_call,
                prompt=_build_dto_contract_fix_prompt(violations, milestone),
                wave_letter="B",
                role="compile_fix",
                milestone=milestone,
                config=config,
                cwd=cwd,
            )
            fix_cost += float(fix_cost_delta or 0.0)
        except WaveWatchdogTimeoutError as exc:
            _write_hang_report(
                cwd=cwd,
                milestone_id=str(getattr(milestone, "id", "") or ""),
                wave="B",
                timeout=exc,
            )
            logger.warning("Wave B DTO contract fix sub-agent timed out: %s", exc)
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
            provider_routing=provider_routing,
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


async def _run_wave_d_frontend_hallucination_guard(
    *,
    run_compile_check: Callable[..., Any] | None,
    execute_sdk_call: Callable[..., Any] | None,
    template: str,
    config: Any,
    cwd: str,
    milestone: Any,
    ir: dict[str, Any],
) -> _DeterministicGuardResult:
    try:
        from .quality_checks import run_frontend_hallucination_scan
    except Exception as exc:  # pragma: no cover - defensive import safety
        logger.warning("Wave D frontend hallucination scan unavailable: %s", exc)
        return _DeterministicGuardResult()

    allowed_locales = []
    if isinstance(ir, dict):
        i18n = ir.get("i18n", {})
        if isinstance(i18n, dict):
            allowed_locales = [str(locale) for locale in i18n.get("locales", []) if str(locale).strip()]

    fix_cost = 0.0
    compile_iterations = 0
    initial_issue_count = 0

    try:
        from .import_resolvability_scan import run_import_resolvability_scan
    except Exception as exc:  # pragma: no cover - defensive import safety
        logger.warning("Wave D import-resolvability scan unavailable: %s", exc)
        run_import_resolvability_scan = None  # type: ignore[assignment]

    for iteration in range(3):
        violations = run_frontend_hallucination_scan(Path(cwd), allowed_locales=allowed_locales)
        if run_import_resolvability_scan is not None:
            violations.extend(run_import_resolvability_scan(Path(cwd)))
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
                    f"Wave D frontend hallucination guard found {len(violations)} persistent violation(s) "
                    f"after {iteration + 1} attempt(s). Wave D.5 is blocked until invalid locales and "
                    "unsupported Google Font subsets are fixed."
                ),
            )

        try:
            fix_cost_delta, _watchdog_state = await _invoke_sdk_sub_agent_with_watchdog(
                execute_sdk_call=execute_sdk_call,
                prompt=_build_frontend_hallucination_fix_prompt(violations, milestone, allowed_locales),
                wave_letter="D",
                role="compile_fix",
                milestone=milestone,
                config=config,
                cwd=cwd,
            )
            fix_cost += float(fix_cost_delta or 0.0)
        except WaveWatchdogTimeoutError as exc:
            _write_hang_report(
                cwd=cwd,
                milestone_id=str(getattr(milestone, "id", "") or ""),
                wave="D",
                timeout=exc,
            )
            logger.warning("Wave D frontend hallucination fix sub-agent timed out: %s", exc)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Wave D frontend hallucination fix sub-agent failed: %s", exc)

        recompile = await _run_wave_compile(
            run_compile_check=run_compile_check,
            execute_sdk_call=execute_sdk_call,
            wave_letter="D",
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
                    f"Compile failed after frontend hallucination fix attempt {iteration + 1}. "
                    "Wave D.5 is blocked until Wave D compiles cleanly again."
                ),
            )

    return _DeterministicGuardResult(
        passed=False,
        compile_passed=True,
        iterations=3,
        compile_iterations=compile_iterations,
        initial_issue_count=initial_issue_count,
        fix_cost=fix_cost,
        error_message="Wave D frontend hallucination guard exhausted its retry budget.",
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
    stack_contract: dict[str, Any] | None = None,
) -> MilestoneWaveResult:
    """Execute one milestone through its ordered wave sequence.

    ``cwd`` is the execution root for all reads and writes. It may point to
    the main project root or any isolated project directory used for execution.
    """
    return await _execute_milestone_waves_with_stack_contract(
        milestone=milestone,
        ir=ir,
        config=config,
        cwd=cwd,
        build_wave_prompt=build_wave_prompt,
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=extract_artifacts,
        generate_contracts=generate_contracts,
        run_scaffolding=run_scaffolding,
        save_wave_state=save_wave_state,
        on_wave_complete=on_wave_complete,
        provider_routing=provider_routing,
        stack_contract=stack_contract,
    )

    template = getattr(milestone, "template", "full_stack") or "full_stack"
    waves = _wave_sequence(template, config)
    if not _wave_scaffolding_enabled(config):
        run_scaffolding = None
    result = MilestoneWaveResult(
        milestone_id=getattr(milestone, "id", ""),
        template=template,
    )

    resolved_stack_contract = None
    stack_contract_dict: dict[str, Any] = {}
    try:
        from .stack_contract import StackContract, load_stack_contract

        if isinstance(stack_contract, dict) and stack_contract:
            resolved_stack_contract = StackContract.from_dict(stack_contract)
        else:
            resolved_stack_contract = load_stack_contract(cwd)
        if resolved_stack_contract is not None:
            stack_contract_dict = resolved_stack_contract.to_dict()
    except Exception:
        resolved_stack_contract = None
        stack_contract_dict = {}

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
        if wave_letter in {"A", "D5"}:
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
        elif wave_letter == "A5":
            # Phase G Slice 4a: Wave A.5 plan-review (Codex medium). Skipped
            # when v18.wave_a5_enabled=False or milestone is small. GATE 8
            # enforcement lives in the orchestrator (cli._enforce_gate_a5).
            wave_result = await _execute_wave_a5(
                milestone=milestone,
                config=config,
                cwd=cwd,
                template=template,
                wave_artifacts=wave_artifacts,
                provider_routing=provider_routing,
            )
        elif wave_letter == "T5":
            # Phase G Slice 4b: Wave T.5 test-gap audit (Codex high). Skipped
            # when v18.wave_t5_enabled=False or Wave T produced no tests.
            # GATE 9 enforcement lives in the orchestrator
            # (cli._enforce_gate_t5).
            wave_result = await _execute_wave_t5(
                milestone=milestone,
                config=config,
                cwd=cwd,
                wave_artifacts=wave_artifacts,
                provider_routing=provider_routing,
            )
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
                fallback_used=wave_result.fallback_used,
                provider_routing=provider_routing,
            )
            dto_guard = _DeterministicGuardResult()
            frontend_guard = _DeterministicGuardResult()
            if wave_letter == "B" and compile_result.passed:
                dto_guard = await _run_wave_b_dto_contract_guard(
                    run_compile_check=run_compile_check,
                    execute_sdk_call=execute_sdk_call,
                    template=template,
                    config=config,
                    cwd=cwd,
                    milestone=milestone,
                    provider_routing=provider_routing,
                )
                if dto_guard.findings:
                    wave_result.findings.extend(dto_guard.findings)
                compile_result.iterations += dto_guard.compile_iterations
                compile_result.fix_cost += dto_guard.fix_cost
                # NEW-1: remove stale apps/api/src/prisma/ duplicates now
                # that Wave B content has stabilized. Flag-gated, no-op when
                # disabled (default). See _maybe_cleanup_duplicate_prisma.
                _maybe_cleanup_duplicate_prisma(cwd=cwd, config=config)
                # Phase F N-19: sanitize Wave B outputs vs SCAFFOLD_OWNERSHIP
                # contract. Flag-gated; report-only (no removal) by default.
                _maybe_sanitize_wave_b_outputs(
                    cwd=cwd,
                    config=config,
                    wave_result=wave_result,
                )
            if wave_letter == "D" and compile_result.passed:
                frontend_guard = await _run_wave_d_frontend_hallucination_guard(
                    run_compile_check=run_compile_check,
                    execute_sdk_call=execute_sdk_call,
                    template=template,
                    config=config,
                    cwd=cwd,
                    milestone=milestone,
                    ir=ir,
                )
                if frontend_guard.findings:
                    wave_result.findings.extend(frontend_guard.findings)
                compile_result.iterations += frontend_guard.compile_iterations
                compile_result.fix_cost += frontend_guard.fix_cost

            wave_result.compile_passed = (
                compile_result.passed
                and dto_guard.compile_passed
                and frontend_guard.compile_passed
            )
            wave_result.compile_iterations = compile_result.iterations
            wave_result.compile_errors_initial = compile_result.initial_error_count
            wave_result.compile_fix_cost = compile_result.fix_cost
            wave_result.cost += compile_result.fix_cost
            if not compile_result.passed or not dto_guard.passed or not frontend_guard.passed:
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
                    # Preserve upstream-set specific diagnostic (mirror
                    # of the newer block below) instead of clobbering
                    # with the generic "Compile failed" message.
                    existing_specific = (
                        wave_result.error_message
                        and not wave_result.error_message.startswith(
                            "Compile failed after "
                        )
                    )
                    if existing_specific:
                        pass
                    elif not compile_result.passed:
                        wave_result.error_message = (
                            f"Compile failed after {compile_result.iterations} attempt(s)"
                        )
                    elif not dto_guard.passed:
                        wave_result.error_message = dto_guard.error_message
                    else:
                        wave_result.error_message = frontend_guard.error_message

            # Re-snap after compile-fix / DTO / frontend-hallucination guard sub-agents
            # so files they wrote are reflected in wave_result. Without this, telemetry
            # under-reports files_created (build-d-rerun-20260414 showed `files_created: 1`
            # for Wave D despite ~30 files on disk).
            if not wave_result.rolled_back:
                checkpoint_after = _create_checkpoint(f"{wave_letter}_final", cwd)
                changed_files = _diff_checkpoints(checkpoint_before, checkpoint_after)
                wave_result.files_created = changed_files.created
                wave_result.files_modified = changed_files.modified

        if wave_result.success and wave_letter not in {"C", "A5", "T5"}:
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
    persist_wave_findings_for_audit(
        cwd,
        result.milestone_id,
        result.waves,
        wave_t_expected=("T" in _wave_sequence(template, config)),
        failing_wave=result.error_wave,
    )

    return result


async def _execute_milestone_waves_with_stack_contract(
    *,
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
    on_wave_complete: Callable[..., Any] | None,
    provider_routing: Any | None,
    stack_contract: dict[str, Any] | None,
) -> MilestoneWaveResult:
    template = getattr(milestone, "template", "full_stack") or "full_stack"
    waves = _wave_sequence(template, config)
    if not _wave_scaffolding_enabled(config):
        run_scaffolding = None
    result = MilestoneWaveResult(
        milestone_id=getattr(milestone, "id", ""),
        template=template,
    )

    resolved_stack_contract = None
    stack_contract_dict: dict[str, Any] = {}
    try:
        from .stack_contract import StackContract, load_stack_contract

        if isinstance(stack_contract, dict) and stack_contract:
            resolved_stack_contract = StackContract.from_dict(stack_contract)
        else:
            resolved_stack_contract = load_stack_contract(cwd)
        if resolved_stack_contract is not None:
            stack_contract_dict = resolved_stack_contract.to_dict()
    except Exception:
        resolved_stack_contract = None
        stack_contract_dict = {}

    # Phase G Slice 1c: initialize cumulative ARCHITECTURE.md once per project.
    # The writer is idempotent; safe to call for every milestone.
    if getattr(getattr(config, "v18", None), "architecture_md_enabled", False):
        try:
            from . import architecture_writer as _architecture_writer
            _architecture_writer.init_if_missing(cwd, stack_contract=stack_contract_dict)
        except Exception:
            # Cumulative ARCHITECTURE.md is advisory; never block the pipeline.
            pass

    # Phase G Slice 1d: render CLAUDE.md / AGENTS.md / .codex/config.toml
    # from the stack contract. Flag-gated; never blocks the pipeline.
    _v18_cfg = getattr(config, "v18", None)
    if (
        getattr(_v18_cfg, "claude_md_autogenerate", False)
        or getattr(_v18_cfg, "agents_md_autogenerate", False)
    ):
        try:
            from . import constitution_writer as _constitution_writer
            _constitution_writer.write_all_if_enabled(cwd, config)
        except Exception:
            pass

    wave_artifacts: dict[str, dict[str, Any]] = {}
    dependency_artifacts = _load_dependency_artifacts(milestone, cwd)
    # A-09: load the milestone scope once per milestone. ``None`` means the
    # artefacts are not on disk (early-build or test fixtures); the scope
    # wrapper falls through to pre-fix behaviour in that case.
    milestone_scope = _load_milestone_scope(milestone, cwd)
    scaffold_artifact = load_wave_artifact(cwd, result.milestone_id, "SCAFFOLD") or {}
    milestone_scaffolded_files = list(
        scaffold_artifact.get("scaffolded_files", [])
        or scaffold_artifact.get("files_created", [])
        or []
    )
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
            # N-12: reconcile REQUIREMENTS + PRD + stack contract into a resolved
            # ScaffoldConfig before scaffolding runs. Flag-OFF = fall through with
            # scaffold_cfg=None so scaffold_runner uses DEFAULT_SCAFFOLD_CONFIG.
            resolved_scaffold_cfg = None
            if _get_v18_value(config, "spec_reconciliation_enabled", False):
                try:
                    resolved_scaffold_cfg = _maybe_run_spec_reconciliation(
                        cwd=cwd,
                        milestone_id=result.milestone_id,
                    )
                except Exception as exc:  # pragma: no cover — defensive
                    logger.warning(
                        "spec reconciliation failed for %s: %s; falling back to defaults",
                        result.milestone_id,
                        exc,
                    )
            milestone_scaffolded_files = await _run_pre_wave_scaffolding(
                run_scaffolding,
                ir,
                cwd,
                milestone,
                scaffold_cfg=resolved_scaffold_cfg,
            )
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
        # Phase G Slice 3d: also snapshot before merged Wave D so we can
        # roll back to the pre-D tree when compile-fix exhausts its cap.
        snapshot_waves = {"A", "D5"}
        if (
            wave_letter == "D"
            and _get_v18_value(config, "wave_d_merged_enabled", False)
        ):
            snapshot_waves = snapshot_waves | {"D"}
        if wave_letter in snapshot_waves:
            from .provider_router import snapshot_for_rollback

            rollback_snapshot = snapshot_for_rollback(cwd, checkpoint_before)

        wave_a_rejection_context = ""
        wave_a_retry_count = 0

        while True:
            if wave_letter == "A":
                _wave_contract_conflict_path(cwd).unlink(missing_ok=True)

            if wave_letter == "C":
                if generate_contracts is None:
                    wave_result = WaveResult(
                        wave="C",
                        success=False,
                        error_message="generate_contracts callback not provided",
                        timestamp=_now_iso(),
                    )
                else:
                    wave_result = await _execute_wave_c(
                        generate_contracts,
                        cwd,
                        milestone,
                        wave_artifacts,
                    )
            elif wave_letter == "A5":
                # Phase G Slice 4a + 4e: Wave A.5 plan-review (Codex medium)
                # with GATE 8 rerun loop. When v18.wave_a5_gate_enforcement=True
                # and A.5 returns FAIL+CRITICAL, re-dispatch Wave A with the
                # findings as [PLAN REVIEW FEEDBACK], then re-run A.5. Bounded
                # by wave_a5_max_reruns (default 1). Unrecoverable failures
                # raise GateEnforcementError which propagates to the caller.
                from .cli import _enforce_gate_a5 as _enforce_a5

                wave_result = await _execute_wave_a5(
                    milestone=milestone,
                    config=config,
                    cwd=cwd,
                    template=template,
                    wave_artifacts=wave_artifacts,
                    provider_routing=provider_routing,
                )
                _a5_rerun = 0
                while True:
                    should_rerun_a, critical_a_findings = _enforce_a5(
                        config=config,
                        cwd=cwd,
                        milestone_id=result.milestone_id,
                        rerun_count=_a5_rerun,
                    )
                    if not should_rerun_a:
                        break
                    # Re-execute Wave A with [PLAN REVIEW FEEDBACK]. The
                    # feedback block is appended to stack_contract_rejection_context
                    # so the Wave A prompt carries findings into the next pass.
                    _a5_feedback = _format_plan_review_feedback(critical_a_findings)
                    _rerun_a_prompt = await _invoke(
                        build_wave_prompt,
                        wave="A",
                        milestone=milestone,
                        wave_artifacts=wave_artifacts,
                        dependency_artifacts=dependency_artifacts,
                        ir=ir,
                        config=config,
                        scaffolded_files=scaffolded_files,
                        cwd=cwd,
                        stack_contract=stack_contract_dict,
                        stack_contract_rejection_context=_a5_feedback,
                    )
                    _rerun_a_prompt = apply_scope_if_enabled(
                        str(_rerun_a_prompt or ""),
                        milestone_scope,
                        config,
                        wave="A",
                    )
                    await _execute_wave_sdk(
                        execute_sdk_call=execute_sdk_call,
                        wave_letter="A",
                        prompt=str(_rerun_a_prompt or ""),
                        config=config,
                        cwd=cwd,
                        milestone=milestone,
                        provider_routing=provider_routing,
                    )
                    wave_result = await _execute_wave_a5(
                        milestone=milestone,
                        config=config,
                        cwd=cwd,
                        template=template,
                        wave_artifacts=wave_artifacts,
                        provider_routing=provider_routing,
                    )
                    _a5_rerun += 1
            elif wave_letter == "T5":
                # Phase G Slice 4b + 4e: Wave T.5 test-gap audit (Codex high)
                # with GATE 9 rerun loop. When v18.wave_t5_gate_enforcement=True
                # and T.5 returns ≥1 CRITICAL gap, loop back to Wave T with
                # the gap list injected, then re-run T.5 once. Unrecoverable
                # CRITICAL gaps raise GateEnforcementError.
                from .cli import _enforce_gate_t5 as _enforce_t5

                wave_result = await _execute_wave_t5(
                    milestone=milestone,
                    config=config,
                    cwd=cwd,
                    wave_artifacts=wave_artifacts,
                    provider_routing=provider_routing,
                )
                _t5_rerun = 0
                while True:
                    should_rerun_t, _critical_t_gaps = _enforce_t5(
                        config=config,
                        cwd=cwd,
                        milestone_id=result.milestone_id,
                        rerun_count=_t5_rerun,
                    )
                    if not should_rerun_t:
                        break
                    # Re-execute Wave T (Claude-only; bypasses provider_routing
                    # per V18.2). Wave T reads its own .agent-team/milestones/
                    # {id}/WAVE_T5_GAPS.json via prompt injection in Slice 5.
                    # For now we simply re-run it to pick up the gap list in
                    # its iteration-2 context.
                    await _execute_wave_t(
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
                    wave_result = await _execute_wave_t5(
                        milestone=milestone,
                        config=config,
                        cwd=cwd,
                        wave_artifacts=wave_artifacts,
                        provider_routing=provider_routing,
                    )
                    _t5_rerun += 1
            elif wave_letter == "T":
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
                    stack_contract=stack_contract_dict,
                    stack_contract_rejection_context=wave_a_rejection_context,
                )
                # A-09: prepend milestone-scope preamble when the feature flag
                # is on and we have a scope loaded. Pre-fix behaviour when
                # the flag is off or scope is unavailable.
                prompt = apply_scope_if_enabled(
                    str(prompt or ""),
                    milestone_scope,
                    config,
                    wave=wave_letter,
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

            wave_result.stack_contract = dict(stack_contract_dict)
            wave_result.stack_contract_retry_count = wave_a_retry_count

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
                    fallback_used=wave_result.fallback_used,
                    provider_routing=provider_routing,
                )
                dto_guard = _DeterministicGuardResult()
                frontend_guard = _DeterministicGuardResult()
                if wave_letter == "B" and compile_result.passed:
                    dto_guard = await _run_wave_b_dto_contract_guard(
                        run_compile_check=run_compile_check,
                        execute_sdk_call=execute_sdk_call,
                        template=template,
                        config=config,
                        cwd=cwd,
                        milestone=milestone,
                        provider_routing=provider_routing,
                    )
                    if dto_guard.findings:
                        wave_result.findings.extend(dto_guard.findings)
                    compile_result.iterations += dto_guard.compile_iterations
                    compile_result.fix_cost += dto_guard.fix_cost
                    # NEW-1: see _maybe_cleanup_duplicate_prisma — flag-gated.
                    _maybe_cleanup_duplicate_prisma(cwd=cwd, config=config)
                if wave_letter == "D" and compile_result.passed:
                    frontend_guard = await _run_wave_d_frontend_hallucination_guard(
                        run_compile_check=run_compile_check,
                        execute_sdk_call=execute_sdk_call,
                        template=template,
                        config=config,
                        cwd=cwd,
                        milestone=milestone,
                        ir=ir,
                    )
                    if frontend_guard.findings:
                        wave_result.findings.extend(frontend_guard.findings)
                    compile_result.iterations += frontend_guard.compile_iterations
                    compile_result.fix_cost += frontend_guard.fix_cost

                # N-13: scaffold-verifier runs immediately after Wave A compile
                # succeeds. On verdict == "FAIL" the wave is flipped to
                # success=False with a diagnostic error_message so downstream
                # finalization halts before Wave B touches a drifted tree.
                if (
                    wave_letter == "A"
                    and compile_result.passed
                    and _get_v18_value(config, "scaffold_verifier_enabled", False)
                ):
                    verifier_error = _maybe_run_scaffold_verifier(
                        cwd=cwd,
                        milestone_scope=milestone_scope,
                        scope_aware=bool(
                            _get_v18_value(config, "scaffold_verifier_scope_aware", False)
                        ),
                    )
                    if verifier_error is not None:
                        wave_result.success = False
                        wave_result.error_message = verifier_error
                        compile_result.passed = False

                wave_result.compile_passed = (
                    compile_result.passed
                    and dto_guard.compile_passed
                    and frontend_guard.compile_passed
                )
                wave_result.compile_iterations = compile_result.iterations
                wave_result.compile_errors_initial = compile_result.initial_error_count
                wave_result.compile_fix_cost = compile_result.fix_cost
                wave_result.cost += compile_result.fix_cost

                if not compile_result.passed or not dto_guard.passed or not frontend_guard.passed:
                    merged_d_rollback = (
                        wave_letter == "D"
                        and _get_v18_value(config, "wave_d_merged_enabled", False)
                        and rollback_snapshot is not None
                    )
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
                    elif merged_d_rollback:
                        # Phase G Slice 3d: merged Wave D exhausted compile-fix
                        # attempts. Roll back to pre-D state and flag the
                        # wave_result so the orchestrator can retry this
                        # milestone in legacy D+D5 mode (that retry is
                        # scheduled at the wave-sequence layer, not here).
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
                        wave_result.success = False
                        wave_result.error_message = (
                            f"Merged Wave D compile-fix exhausted after "
                            f"{compile_result.iterations} attempt(s); "
                            "restored the pre-D checkpoint. Milestone is a "
                            "candidate for legacy D+D5 retry "
                            "(wave_d_merged_enabled override scoped to this "
                            "milestone)."
                        )
                    else:
                        wave_result.success = False
                        # Preserve a specific diagnostic already set
                        # upstream (e.g. scaffold-verifier FAIL reason)
                        # instead of clobbering it with the generic
                        # "Compile failed after N attempt(s)" message.
                        # Callers that set a specific reason ALSO flip
                        # compile_result.passed=False, so without this
                        # guard the specific reason is lost to the
                        # telemetry and downstream diagnostics (see the
                        # build-final-smoke-20260418-041514 regression:
                        # scaffold-verifier FAIL was reported as
                        # "Compile failed after 1 attempt(s)").
                        existing_specific = (
                            wave_result.error_message
                            and not wave_result.error_message.startswith(
                                "Compile failed after "
                            )
                        )
                        if existing_specific:
                            pass  # keep the specific upstream reason
                        elif not compile_result.passed:
                            wave_result.error_message = (
                                f"Compile failed after {compile_result.iterations} attempt(s)"
                            )
                        elif not dto_guard.passed:
                            wave_result.error_message = dto_guard.error_message
                        else:
                            wave_result.error_message = frontend_guard.error_message

            checkpoint_after = _create_checkpoint(f"{wave_letter}_final", cwd)
            changed_files = _diff_checkpoints(checkpoint_before, checkpoint_after)
            wave_result.files_created = changed_files.created
            wave_result.files_modified = changed_files.modified

            # A-09 post-wave scope validator: flag files_created that fell
            # outside the milestone's allowed_file_globs. Read-only — never
            # deletes files or fails the wave.
            if milestone_scope is not None and milestone_scope.allowed_file_globs:
                wave_result.scope_violations = files_outside_scope(
                    wave_result.files_created, milestone_scope,
                )
                if wave_result.scope_violations:
                    logger.warning(
                        "Wave %s for %s produced %d file(s) outside milestone scope: %s",
                        wave_letter,
                        result.milestone_id,
                        len(wave_result.scope_violations),
                        wave_result.scope_violations[:10],
                    )

            if wave_letter == "A" and wave_result.success:
                contract_conflict = _read_wave_a_contract_conflict(cwd)
                if contract_conflict:
                    wave_result.success = False
                    wave_result.error_message = (
                        "Wave A wrote WAVE_A_CONTRACT_CONFLICT.md: "
                        f"{contract_conflict[:1000]}"
                    )

            wave_result.stack_contract_violations = []
            if (
                wave_letter in {"A", "B", "D"}
                and wave_result.success
                and resolved_stack_contract is not None
            ):
                from .stack_contract import (
                    format_stack_violations,
                    validate_wave_against_stack_contract,
                )

                violations = validate_wave_against_stack_contract(
                    wave_result,
                    resolved_stack_contract,
                    Path(cwd),
                )
                if wave_letter in {"B", "D"}:
                    violations = [
                        violation
                        for violation in violations
                        if str(getattr(violation, "code", "")).strip() not in {"STACK-FILE-002", "STACK-IMPORT-002"}
                    ]
                wave_result.stack_contract_violations = [
                    violation.to_dict() for violation in violations
                ]
                stack_findings = [
                    _stack_violation_to_finding(violation)
                    for violation in violations
                ]

                if wave_letter == "A":
                    critical = [
                        violation
                        for violation in violations
                        if str(getattr(violation, "severity", "")).upper() == "CRITICAL"
                    ]
                    hard_block = str(
                        getattr(resolved_stack_contract, "confidence", "low")
                    ).strip().lower() in {"explicit", "high"}
                    if critical and hard_block and wave_a_retry_count < 1 and rollback_snapshot is not None:
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
                        wave_a_retry_count = 1
                        wave_a_rejection_context = format_stack_violations(critical)
                        continue
                    if critical and hard_block:
                        wave_result.success = False
                        wave_result.error_message = "Stack contract violated after retry"
                    if stack_findings:
                        wave_result.findings.extend(stack_findings)
                elif stack_findings:
                    wave_result.findings.extend(stack_findings)

            break

        if wave_result.success and wave_letter not in {"C", "A5", "T5"}:
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

        if wave_letter == "E":
            scan_findings = _run_post_wave_e_scans(cwd)
            if scan_findings:
                wave_result.findings.extend(scan_findings)

            backend_passed = 0
            backend_failed = 0
            for subdir in ("apps/api", "apps/web"):
                ran, passed, failed, _ = await _run_node_tests(cwd, subdir, timeout=120.0)
                if ran:
                    backend_passed += passed
                    backend_failed += failed
            wave_result.backend_tests_passed = backend_passed
            wave_result.backend_tests_failed = backend_failed

            pw_ran, pw_passed, pw_failed, _ = await _run_playwright_tests(
                cwd,
                result.milestone_id,
                timeout=180.0,
            )
            if pw_ran:
                wave_result.playwright_tests_passed = pw_passed
                wave_result.playwright_tests_failed = pw_failed

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
        wave_result.duration_seconds = (
            datetime.now(timezone.utc) - wave_start
        ).total_seconds()
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

    persist_wave_findings_for_audit(
        cwd,
        result.milestone_id,
        result.waves,
        wave_t_expected=("T" in _wave_sequence(template, config)),
        failing_wave=result.error_wave,
    )

    # Phase G Slice 1c: append this milestone's architectural summary to
    # the cumulative ARCHITECTURE.md. Best-effort; never blocks the pipeline.
    _v18 = getattr(config, "v18", None)
    if getattr(_v18, "architecture_md_enabled", False):
        try:
            from . import architecture_writer as _architecture_writer
            _architecture_writer.append_milestone(
                result.milestone_id,
                wave_artifacts,
                cwd,
                stack_contract=stack_contract_dict,
                title=getattr(milestone, "title", None),
            )
            _architecture_writer.summarize_if_over(
                cwd,
                max_lines=getattr(_v18, "architecture_md_max_lines", 500),
                summarize_floor=getattr(_v18, "architecture_md_summarize_floor", 5),
            )
        except Exception:
            pass

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
