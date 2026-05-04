"""Provider Router — Routes waves to providers with checkpoint-based rollback."""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass, replace as _dc_replace
from pathlib import Path
from typing import Any, Callable

from .async_subprocess_compat import create_subprocess_exec_compat
from .codex_captures import (
    CodexCaptureMetadata,
    update_latest_mirror_and_index,
    write_checkpoint_diff_capture,
)

logger = logging.getLogger(__name__)

_SKIP_DIRS = {
    ".git", ".agent-team", ".next", ".venv", "__pycache__",
    "build", "dist", "node_modules",
}

_STYLE_EXTENSIONS = frozenset({
    ".ts", ".tsx", ".js", ".jsx", ".json", ".css", ".scss",
})


def _claude_provider_model(config: Any | None) -> str:
    orchestrator = getattr(config, "orchestrator", None)
    return str(getattr(orchestrator, "model", "") or "")


def _call_accepts_kwarg(callable_obj: Callable[..., Any], name: str) -> bool:
    import inspect as _inspect

    signature_target = callable_obj
    side_effect = getattr(callable_obj, "side_effect", None)
    if callable(side_effect):
        signature_target = side_effect
    try:
        parameters = _inspect.signature(signature_target).parameters
    except (TypeError, ValueError):
        return False
    if name in parameters:
        return True
    return any(
        param.kind == _inspect.Parameter.VAR_KEYWORD
        for param in parameters.values()
    )


def _read_observer_requirements_text(
    *,
    cwd: str,
    prompt: str,
    claude_callback_kwargs: dict[str, Any],
) -> str:
    milestone = claude_callback_kwargs.get("milestone")
    milestone_id = str(getattr(milestone, "id", "") or "").strip()
    if milestone_id:
        req_path = Path(cwd) / ".agent-team" / "milestones" / milestone_id / "REQUIREMENTS.md"
        try:
            if req_path.exists():
                return req_path.read_text(encoding="utf-8")
        except OSError:
            pass
    return prompt


def _build_codex_observer_kwargs(
    execute_codex: Callable[..., Any],
    *,
    config: Any,
    cwd: str,
    prompt: str,
    wave_letter: str,
    claude_callback_kwargs: dict[str, Any],
) -> dict[str, Any]:
    observer_kwargs: dict[str, Any] = {}
    if _call_accepts_kwarg(execute_codex, "observer_config"):
        observer_kwargs["observer_config"] = getattr(config, "observer", None)
    if _call_accepts_kwarg(execute_codex, "requirements_text"):
        observer_kwargs["requirements_text"] = _read_observer_requirements_text(
            cwd=cwd,
            prompt=prompt,
            claude_callback_kwargs=claude_callback_kwargs,
        )
    if _call_accepts_kwarg(execute_codex, "wave_letter"):
        observer_kwargs["wave_letter"] = wave_letter
    return observer_kwargs


@dataclass
class WaveProviderMap:
    """Maps wave letters to provider names."""
    A: str = "claude"
    A5: str = "codex"   # Phase G Slice 3c: Codex plan-review at medium reasoning
    B: str = "codex"    # Codex strongest at integration wiring
    C: str = "python"   # Contract generation — no provider needed
    D: str = "codex"    # Codex owns frontend + generated-client wiring.
                        # Flipped to "claude" at construction-time when
                        # v18.wave_d_merged_enabled is True (merged D+polish).
    D5: str = "claude"  # UI polish is always Claude-owned
    T5: str = "codex"   # Phase G Slice 3c: Codex edge-case audit at high reasoning
    E: str = "claude"

    def provider_for(self, wave_letter: str) -> str:
        wave_key = str(wave_letter or "").strip().upper()
        if wave_key in {"D5", "UI"}:
            return "claude"
        provider = getattr(self, wave_key, "claude")
        return str(provider or "claude").strip().lower()

def snapshot_for_rollback(cwd: str, checkpoint: Any) -> dict[str, bytes]:
    """Read actual file contents for every file in *checkpoint*.file_manifest.

    Returns ``{relative_posix_path: raw_bytes}`` so both text and binary
    files can be restored byte-for-byte on failure.
    """
    root = Path(cwd)
    snapshot: dict[str, bytes] = {}
    for rel_posix in checkpoint.file_manifest:
        try:
            snapshot[rel_posix] = (root / rel_posix).read_bytes()
        except (OSError, PermissionError):
            pass
    return snapshot


def rollback_from_snapshot(
    cwd: str,
    snapshot: dict[str, bytes],
    pre_checkpoint: Any,
    post_checkpoint: Any,
    checkpoint_diff: Callable[..., Any],
) -> None:
    """Restore the working directory to the state captured in *snapshot*.

    * **created** files are deleted.
    * **modified** files are overwritten from the snapshot.
    * **deleted** files are recreated from the snapshot.
    """
    diff = checkpoint_diff(pre_checkpoint, post_checkpoint)
    root = Path(cwd)

    for rel in diff.created:
        try:
            (root / rel).unlink(missing_ok=True)
            logger.info("Rollback: deleted created file %s", rel)
        except OSError as exc:
            logger.warning("Rollback: could not delete %s: %s", rel, exc)

    for rel in diff.modified:
        if rel in snapshot:
            try:
                (root / rel).write_bytes(snapshot[rel])
                logger.info("Rollback: restored modified file %s", rel)
            except OSError as exc:
                logger.warning("Rollback: could not restore %s: %s", rel, exc)

    for rel in diff.deleted:
        if rel in snapshot:
            abs_path = root / rel
            try:
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.write_bytes(snapshot[rel])
                logger.info("Rollback: recreated deleted file %s", rel)
            except OSError as exc:
                logger.warning("Rollback: could not recreate %s: %s", rel, exc)

async def _normalize_code_style(cwd: str, changed_files: list[str]) -> None:
    """Run Prettier then ESLint --fix on *changed_files*.  Non-fatal."""
    styleable = [f for f in changed_files if Path(f).suffix in _STYLE_EXTENSIONS]
    if not styleable:
        return

    root = Path(cwd)

    # Prettier
    prettier_names = (
        ".prettierrc", ".prettierrc.json", ".prettierrc.js",
        ".prettierrc.yml", ".prettierrc.yaml",
        "prettier.config.js", "prettier.config.cjs",
    )
    if any((root / n).exists() for n in prettier_names):
        try:
            proc = await create_subprocess_exec_compat(
                "npx", "prettier", "--write", *styleable,
                cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning("Prettier exited %d: %s", proc.returncode,
                               stderr.decode(errors="replace")[:500])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Prettier failed: %s", exc)

    # ESLint
    eslint_names = (
        ".eslintrc", ".eslintrc.json", ".eslintrc.js",
        ".eslintrc.yml", ".eslintrc.yaml",
        "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs",
    )
    if any((root / n).exists() for n in eslint_names):
        ts_files = [f for f in styleable if Path(f).suffix in {".ts", ".tsx", ".js", ".jsx"}]
        if ts_files:
            try:
                proc = await create_subprocess_exec_compat(
                    "npx", "eslint", "--fix", *ts_files,
                    cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode not in (0, 1):
                    logger.warning("ESLint exited %d: %s", proc.returncode,
                                   stderr.decode(errors="replace")[:500])
            except Exception as exc:  # noqa: BLE001
                logger.warning("ESLint failed: %s", exc)

async def execute_wave_with_provider(
    *,
    wave_letter: str,
    prompt: str,
    cwd: str,
    config: Any,
    provider_map: WaveProviderMap,
    claude_callback: Callable[..., Any],
    claude_callback_kwargs: dict[str, Any],
    codex_transport_module: Any | None = None,
    codex_config: Any | None = None,
    codex_home: Path | None = None,
    checkpoint_create: Callable[..., Any],
    checkpoint_restore: Callable[..., Any] | None = None,
    checkpoint_diff: Callable[..., Any],
    progress_callback: Callable[..., Any] | None = None,
    force_claude_fallback_reason: str | None = None,
    retry_count_override: int | None = None,
    stack_contract: Any | None = None,
) -> dict[str, Any]:
    """Route a wave to the appropriate provider.

    Returns a plain dict with provider metadata the caller merges into
    :class:`WaveResult`.
    """
    provider = provider_map.provider_for(wave_letter)

    if provider == "python":
        return {"provider": "python", "provider_model": "", "cost": 0.0}

    if provider == "codex" and force_claude_fallback_reason:
        return _codex_hard_failure(
            f"Codex watchdog wedge detected; Claude fallback is disabled: {force_claude_fallback_reason}",
            provider_model=_codex_provider_model(codex_config),
        )

    if provider == "codex":
        return await _execute_codex_wave(
            wave_letter=wave_letter, prompt=prompt, cwd=cwd, config=config,
            claude_callback=claude_callback,
            claude_callback_kwargs=claude_callback_kwargs,
            codex_transport_module=codex_transport_module,
            codex_config=codex_config, codex_home=codex_home,
            checkpoint_create=checkpoint_create,
            checkpoint_diff=checkpoint_diff,
            progress_callback=progress_callback,
            stack_contract=stack_contract,
        )

    return await _execute_claude_wave(
        prompt=prompt, config=config, claude_callback=claude_callback,
        claude_callback_kwargs=claude_callback_kwargs,
        progress_callback=progress_callback,
    )

async def _execute_claude_wave(
    *,
    prompt: str,
    config: Any | None,
    claude_callback: Callable[..., Any],
    claude_callback_kwargs: dict[str, Any],
    progress_callback: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Execute a wave via the Claude SDK callback."""
    import inspect
    callback_kwargs = dict(claude_callback_kwargs)
    if progress_callback is not None and "progress_callback" not in callback_kwargs:
        callback_kwargs["progress_callback"] = progress_callback
    cost = claude_callback(prompt=prompt, **callback_kwargs)
    if inspect.isawaitable(cost):
        cost = await cost
    return {
        "cost": float(cost or 0.0),
        "provider": "claude",
        "provider_model": _claude_provider_model(config),
        "fallback_used": False,
        "fallback_reason": "",
        "retry_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
    }

def _wrap_codex_prompt_with_contract(
    wave_letter: str,
    prompt: str,
    cwd: str | Path,
    stack_contract: Any | None = None,
) -> str:
    """Wrap a Codex wave prompt, injecting the infrastructure_contract block
    when the stack_contract carries one.

    Extracted from ``_execute_codex_wave`` so the Issue #14 runtime plumbing
    (scaffold → STACK_CONTRACT.json → wrap_prompt_for_codex → final prompt)
    is exercised directly by unit tests.

    If ``stack_contract`` is supplied by the caller (the preferred path —
    wave_executor threads the already-loaded contract through), it is used
    as-is. Otherwise the helper loads the persisted contract from ``cwd``
    as a fallback so legacy callers that don't yet pass the arg still get
    the injection behavior.

    Falls back to the raw prompt on any ImportError from the codex_prompts
    module (exec-mode fallback).
    """
    try:
        from .codex_prompts import wrap_prompt_for_codex
    except ImportError:
        return prompt

    resolved = stack_contract
    if resolved is None:
        try:
            from .stack_contract import load_stack_contract
            resolved = load_stack_contract(cwd)
        except Exception:  # pragma: no cover — defensive
            resolved = None

    return wrap_prompt_for_codex(
        wave_letter, prompt, stack_contract=resolved
    )


async def _execute_codex_wave(
    *,
    wave_letter: str,
    prompt: str,
    cwd: str,
    config: Any,
    claude_callback: Callable[..., Any],
    claude_callback_kwargs: dict[str, Any],
    codex_transport_module: Any | None,
    codex_config: Any | None,
    codex_home: Path | None,
    checkpoint_create: Callable[..., Any],
    checkpoint_diff: Callable[..., Any],
    progress_callback: Callable[..., Any] | None = None,
    stack_contract: Any | None = None,
) -> dict[str, Any]:
    """Execute a wave via Codex with checkpoint rollback on failure."""
    import inspect as _inspect
    from .wave_executor import WaveWatchdogTimeoutError, _get_v18_value

    # Import CodexOrphanToolError — only exists in the app-server transport.
    # Graceful fallback: if the import fails (exec mode), use a sentinel that
    # never matches so the except clause is inert.
    try:
        from .codex_appserver import CodexOrphanToolError as _CodexOrphanToolError
    except ImportError:
        _CodexOrphanToolError = type("_CodexOrphanToolError", (Exception,), {})

    # Phase 5 closeout Stage 2 §M.M5 follow-up #3 — same fallback shape
    # for ``CodexTerminalTurnError`` (per-session abnormal termination).
    # Imported separately because exec-mode dispatch doesn't carry the
    # class; the sentinel keeps the ``except`` clause inert there.
    try:
        from .codex_appserver import CodexTerminalTurnError as _CodexTerminalTurnError
    except ImportError:
        _CodexTerminalTurnError = type("_CodexTerminalTurnError", (Exception,), {})

    def _is_transport_stdout_eof(exc: BaseException) -> bool:
        reason = str(getattr(exc, "reason", "") or "")
        text = f"{reason} {exc}".lower()
        return "stdout eof" in text or "app-server stdout eof" in text

    def _codex_terminal_retry_budget(config_obj: Any) -> int:
        raw = getattr(config_obj, "max_retries", 0)
        if isinstance(raw, bool):
            return int(raw)
        if isinstance(raw, int):
            return max(raw, 0)
        if isinstance(raw, float):
            return max(int(raw), 0)
        if isinstance(raw, str):
            try:
                return max(int(raw.strip()), 0)
            except ValueError:
                return 0
        return 0

    # 1. Check Codex availability
    if codex_transport_module is None:
        return _codex_hard_failure(
            "codex_transport_module not provided",
            provider_model=_codex_provider_model(codex_config),
        )

    is_available = getattr(codex_transport_module, "is_codex_available", None)
    if is_available is not None and not is_available():
        logger.warning("Wave %s: Codex not available; failing Codex-owned wave", wave_letter)
        return _codex_hard_failure(
            "Codex CLI not available on this machine",
            provider_model=_codex_provider_model(codex_config),
        )

    # 2. Pre-execution checkpoint + content snapshot
    pre_checkpoint = checkpoint_create(f"pre-codex-wave-{wave_letter}", cwd)
    content_snapshot = snapshot_for_rollback(cwd, pre_checkpoint)

    # 3. Wrap prompt for Codex (extracted to _wrap_codex_prompt_with_contract
    # so the runtime injection path is directly testable). When the caller
    # passed an explicit stack_contract, prefer it over re-loading from disk.
    codex_prompt = _wrap_codex_prompt_with_contract(
        wave_letter, prompt, cwd, stack_contract=stack_contract
    )

    # 4. Execute via Codex
    execute_codex = getattr(codex_transport_module, "execute_codex", None)
    if execute_codex is None:
        logger.error("Wave %s: codex_transport_module has no execute_codex()", wave_letter)
        return _codex_hard_failure(
            "execute_codex function not found in codex_transport_module",
            provider_model=_codex_provider_model(codex_config),
        )

    capture_kwargs: dict[str, Any] = {}
    observer_kwargs = _build_codex_observer_kwargs(
        execute_codex,
        config=config,
        cwd=cwd,
        prompt=prompt,
        wave_letter=wave_letter,
        claude_callback_kwargs=claude_callback_kwargs,
    )
    capture_metadata: CodexCaptureMetadata | None = None
    if (
        _get_v18_value(config, "codex_capture_enabled", False)
        or _get_v18_value(config, "codex_protocol_capture_enabled", False)
    ):
        milestone = claude_callback_kwargs.get("milestone") if isinstance(claude_callback_kwargs, dict) else None
        capture_metadata = CodexCaptureMetadata(
            milestone_id=str(getattr(milestone, "id", "") or "").strip() or "unknown-milestone",
            wave_letter=wave_letter,
            session_id=secrets.token_hex(8),
        )
        try:
            signature = _inspect.signature(execute_codex)
            parameters = signature.parameters
            accepts_kwargs = any(
                param.kind == _inspect.Parameter.VAR_KEYWORD
                for param in parameters.values()
            )
            if "capture_enabled" in parameters or accepts_kwargs:
                capture_kwargs["capture_enabled"] = True
            if "capture_metadata" in parameters or accepts_kwargs:
                capture_kwargs["capture_metadata"] = capture_metadata
        except (TypeError, ValueError):
            pass

    try:
        retry_budget = _codex_terminal_retry_budget(codex_config)
        current_codex_home = codex_home
        while True:
            try:
                codex_result = execute_codex(
                    codex_prompt,
                    cwd,
                    codex_config,
                    current_codex_home,
                    progress_callback=progress_callback,
                    **capture_kwargs,
                    **observer_kwargs,
                )
                if _inspect.isawaitable(codex_result):
                    codex_result = await codex_result
                break
            except _CodexTerminalTurnError as exc:
                if not _is_transport_stdout_eof(exc) or retry_budget <= 0:
                    # Non-EOF terminal-turn failures retain the typed propagation
                    # path expected by the wave watchdog/hang-report layer.
                    raise
                logger.warning(
                    "Wave %s: Codex transport stdout EOF before turn/completed; "
                    "rollback to pre-wave anchor and retry once with a fresh Codex home",
                    wave_letter,
                )
                post_checkpoint = checkpoint_create(
                    f"post-codex-transport-eof-{wave_letter}",
                    cwd,
                )
                rollback_from_snapshot(
                    cwd,
                    content_snapshot,
                    pre_checkpoint,
                    post_checkpoint,
                    checkpoint_diff,
                )
                # B3 — preserve the failed attempt's capture artifacts before
                # retrying. Bump attempt_id so the next iteration writes to
                # a disambiguated stem; refresh the legacy-stem latest-mirror
                # + capture-index so existing consumers still find canonical
                # filenames + reviewers can enumerate every attempt.
                if capture_metadata is not None:
                    update_latest_mirror_and_index(
                        cwd=cwd,
                        metadata=capture_metadata,
                    )
                    capture_metadata = _dc_replace(
                        capture_metadata,
                        attempt_id=int(getattr(capture_metadata, "attempt_id", 1) or 1) + 1,
                    )
                    capture_kwargs["capture_metadata"] = capture_metadata
                retry_budget -= 1
                current_codex_home = None
    except WaveWatchdogTimeoutError as exc:
        logger.warning(
            "Wave %s: WaveWatchdogTimeoutError; rollback and hard-fail Codex-owned wave",
            wave_letter,
        )
        post_checkpoint = checkpoint_create(f"post-codex-fail-{wave_letter}", cwd)
        rollback_from_snapshot(cwd, content_snapshot, pre_checkpoint,
                               post_checkpoint, checkpoint_diff)
        return _codex_hard_failure(
            f"WaveWatchdogTimeoutError: {exc}",
            provider_model=_codex_provider_model(codex_config),
            rolled_back=True,
        )
    except _CodexOrphanToolError as exc:
        logger.warning(
            "Wave %s: CodexOrphanToolError (tool=%s, age=%.0fs, count=%d); rollback and hard-fail Codex-owned wave",
            wave_letter, exc.tool_name, exc.age_seconds, exc.orphan_count,
        )
        post_checkpoint = checkpoint_create(f"post-codex-fail-{wave_letter}", cwd)
        rollback_from_snapshot(cwd, content_snapshot, pre_checkpoint,
                               post_checkpoint, checkpoint_diff)
        return _codex_hard_failure(
            f"CodexOrphanToolError: {exc}",
            provider_model=_codex_provider_model(codex_config),
            rolled_back=True,
        )
    except _CodexTerminalTurnError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Wave %s: Codex execution raised: %s", wave_letter, exc)
        post_checkpoint = checkpoint_create(f"post-codex-fail-{wave_letter}", cwd)
        rollback_from_snapshot(cwd, content_snapshot, pre_checkpoint,
                               post_checkpoint, checkpoint_diff)
        return _codex_hard_failure(
            f"Codex raised: {exc}",
            provider_model=_codex_provider_model(codex_config),
            rolled_back=True,
        )

    if (
        _get_v18_value(config, "codex_blocked_prefix_as_failure_enabled", False)
        and getattr(codex_result, "success", False)
    ):
        final_message = str(getattr(codex_result, "final_message", "") or "")
        stripped_message = final_message.lstrip()
        if stripped_message.startswith("BLOCKED:"):
            blocked_reason = stripped_message.splitlines()[0][:400]
            logger.warning(
                "CODEX-WAVE-B-BLOCKED-001: Codex emitted BLOCKED signal; "
                "treating as failure despite success=true. Reason: %s",
                blocked_reason,
            )
            codex_result.success = False
            if not (getattr(codex_result, "error", "") or ""):
                codex_result.error = blocked_reason

    # 5. Evaluate result
    if getattr(codex_result, "success", False):
        if _get_v18_value(config, "codex_flush_wait_enabled", False):
            try:
                flush_seconds = max(
                    0.0,
                    float(_get_v18_value(config, "codex_flush_wait_seconds", 0.5)),
                )
            except (TypeError, ValueError):
                flush_seconds = 0.5
            await asyncio.sleep(flush_seconds)
            logger.debug("Codex flush-wait completed: %.3fs", flush_seconds)
        post_checkpoint = checkpoint_create(f"post-codex-wave-{wave_letter}", cwd)
        diff = checkpoint_diff(pre_checkpoint, post_checkpoint)
        if capture_metadata is not None:
            write_checkpoint_diff_capture(
                cwd=cwd,
                metadata=capture_metadata,
                pre_checkpoint=pre_checkpoint,
                post_checkpoint=post_checkpoint,
                diff=diff,
            )
        created = list(getattr(diff, "created", []))
        modified = list(getattr(diff, "modified", []))
        deleted = list(getattr(diff, "deleted", []))
        changed = created + modified
        if not (created or modified or deleted):
            logger.warning(
                "Wave %s: Codex reported success but produced no tracked file changes; hard-failing Codex-owned wave",
                wave_letter,
            )
            return _codex_hard_failure(
                "Codex reported success but produced no tracked file changes",
                codex_result=codex_result,
            )
        await _normalize_code_style(cwd, changed)
        return {
            "cost": float(getattr(codex_result, "cost_usd", 0.0) or 0.0),
            "provider": "codex",
            "provider_model": str(getattr(codex_result, "model", "") or ""),
            "fallback_used": False,
            "fallback_reason": "",
            "retry_count": int(getattr(codex_result, "retry_count", 0) or 0),
            "input_tokens": int(getattr(codex_result, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(codex_result, "output_tokens", 0) or 0),
            "reasoning_tokens": int(getattr(codex_result, "reasoning_tokens", 0) or 0),
            "files_created": list(getattr(diff, "created", [])),
            "files_modified": list(getattr(diff, "modified", [])),
        }

    # 6. Failure - rollback and hard-fail Codex-owned wave.
    error_msg = (getattr(codex_result, "error", "") or "")[:200]
    logger.warning("Wave %s: Codex failed (exit=%s, error=%s); rollback and hard-fail",
                   wave_letter, getattr(codex_result, "exit_code", "?"), error_msg)
    post_checkpoint = checkpoint_create(f"post-codex-fail-{wave_letter}", cwd)
    rollback_from_snapshot(cwd, content_snapshot, pre_checkpoint,
                           post_checkpoint, checkpoint_diff)
    return _codex_hard_failure(
        f"Codex failed: {error_msg}",
        codex_result=codex_result,
        rolled_back=True,
    )

def _codex_provider_model(codex_config: Any | None) -> str:
    return str(getattr(codex_config, "model", "") or "")


def _codex_hard_failure(
    reason: str,
    *,
    codex_result: Any | None = None,
    provider_model: str = "",
    rolled_back: bool = False,
) -> dict[str, Any]:
    """Return failure metadata for Codex-owned waves without Claude fallback."""

    error_message = str(reason or "Codex-owned wave failed")
    return {
        "success": False,
        "error_message": error_message,
        "cost": float(getattr(codex_result, "cost_usd", 0.0) or 0.0),
        "provider": "codex",
        "provider_model": str(getattr(codex_result, "model", "") or provider_model or ""),
        "fallback_used": False,
        "fallback_reason": "",
        "retry_count": int(getattr(codex_result, "retry_count", 0) or 0),
        "input_tokens": int(getattr(codex_result, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(codex_result, "output_tokens", 0) or 0),
        "reasoning_tokens": int(getattr(codex_result, "reasoning_tokens", 0) or 0),
        "rolled_back": bool(rolled_back),
        "codex_hard_failure": True,
    }


async def _claude_fallback(
    *,
    prompt: str,
    claude_callback: Callable[..., Any],
    claude_callback_kwargs: dict[str, Any],
    reason: str,
    config: Any | None = None,
    codex_result: Any | None = None,
    codex_config: Any | None = None,
    progress_callback: Callable[..., Any] | None = None,
    retry_count_override: int | None = None,
) -> dict[str, Any]:
    """Execute via Claude as a fallback and tag the result accordingly."""
    result = await _execute_claude_wave(
        prompt=prompt, config=config, claude_callback=claude_callback,
        claude_callback_kwargs=claude_callback_kwargs,
        progress_callback=progress_callback,
    )
    codex_cost = float(getattr(codex_result, "cost_usd", 0.0) or 0.0)

    result["cost"] = float(result.get("cost", 0.0) or 0.0) + codex_cost
    result["fallback_used"] = True
    result["fallback_reason"] = reason
    if retry_count_override is not None:
        result["retry_count"] = int(retry_count_override)
    else:
        result["retry_count"] = int(getattr(codex_result, "retry_count", 0) or 0)
    result["input_tokens"] = int(getattr(codex_result, "input_tokens", 0) or 0)
    result["output_tokens"] = int(getattr(codex_result, "output_tokens", 0) or 0)
    result["reasoning_tokens"] = int(getattr(codex_result, "reasoning_tokens", 0) or 0)
    return result

_CODEX_ISSUE_KW = {
    "wiring", "contract", "endpoint", "dto", "auth", "guard",
    "middleware", "service", "import", "module", "provider",
    "injection", "dependency", "route", "controller", "resolver",
    "schema", "migration", "model", "entity", "repository",
}
_CLAUDE_ISSUE_KW = {
    "styling", "layout", "responsive", "i18n", "component",
    "visual", "animation", "accessibility", "a11y", "design",
    "typography", "colour", "color", "theme", "css", "tailwind",
    "translation", "localisation", "localization", "copy", "text",
}
_CODEX_PATH_KW = {
    "service", "controller", "guard", "middleware", "module",
    "resolver", "dto", "entity", "migration", "route", "api",
    "server", "backend",
}
_CLAUDE_PATH_KW = {
    "component", "page", "layout", "style", "css", "scss",
    "theme", "i18n", "locale", "hook", "context", "store",
    "frontend", "client", "app", "ui",
}


def classify_fix_provider(affected_files: list[str], issue_type: str) -> str:
    """Decide whether a fix should be routed to Codex or Claude.

    Uses *issue_type* as primary signal and file-path heuristics as
    secondary.  Returns ``"codex"`` or ``"claude"``.
    """
    issue_lower = issue_type.lower() if issue_type else ""

    for kw in _CODEX_ISSUE_KW:
        if kw in issue_lower:
            return "codex"
    for kw in _CLAUDE_ISSUE_KW:
        if kw in issue_lower:
            return "claude"

    codex_score = claude_score = 0
    for fpath in affected_files:
        pl = fpath.lower().replace("\\", "/")
        codex_score += sum(1 for p in _CODEX_PATH_KW if p in pl)
        claude_score += sum(1 for p in _CLAUDE_PATH_KW if p in pl)

    if codex_score > claude_score:
        return "codex"
    return "claude"
