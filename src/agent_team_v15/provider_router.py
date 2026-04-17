"""Provider Router — Routes waves to providers with checkpoint-based rollback."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

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

@dataclass
class WaveProviderMap:
    """Maps wave letters to provider names."""
    A: str = "claude"
    B: str = "codex"    # Codex strongest at integration wiring
    C: str = "python"   # Contract generation — no provider needed
    D: str = "codex"    # Codex owns frontend + generated-client wiring
    D5: str = "claude"  # UI polish is always Claude-owned
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
            proc = await asyncio.create_subprocess_exec(
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
                proc = await asyncio.create_subprocess_exec(
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
) -> dict[str, Any]:
    """Route a wave to the appropriate provider.

    Returns a plain dict with provider metadata the caller merges into
    :class:`WaveResult`.
    """
    provider = provider_map.provider_for(wave_letter)

    if provider == "python":
        return {"provider": "python", "provider_model": "", "cost": 0.0}

    if provider == "codex" and force_claude_fallback_reason:
        logger.warning(
            "Wave %s: skipping Codex after wedge and routing retry directly to Claude fallback",
            wave_letter,
        )
        return await _claude_fallback(
            prompt=prompt,
            claude_callback=claude_callback,
            claude_callback_kwargs=claude_callback_kwargs,
            reason=force_claude_fallback_reason,
            config=config,
            codex_config=codex_config,
            progress_callback=progress_callback,
            retry_count_override=retry_count_override,
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
) -> dict[str, Any]:
    """Execute a wave via Codex with checkpoint rollback on failure."""
    import inspect as _inspect
    from .wave_executor import WaveWatchdogTimeoutError

    # Import CodexOrphanToolError — only exists in the app-server transport.
    # Graceful fallback: if the import fails (exec mode), use a sentinel that
    # never matches so the except clause is inert.
    try:
        from .codex_appserver import CodexOrphanToolError as _CodexOrphanToolError
    except ImportError:
        _CodexOrphanToolError = type("_CodexOrphanToolError", (Exception,), {})

    # 1. Check Codex availability
    if codex_transport_module is None:
        return await _claude_fallback(
            prompt=prompt, claude_callback=claude_callback,
            claude_callback_kwargs=claude_callback_kwargs,
            reason="codex_transport_module not provided",
            config=config,
            codex_config=codex_config,
            progress_callback=progress_callback,
        )

    is_available = getattr(codex_transport_module, "is_codex_available", None)
    if is_available is not None and not is_available():
        logger.warning("Wave %s: Codex not available — Claude fallback", wave_letter)
        return await _claude_fallback(
            prompt=prompt, claude_callback=claude_callback,
            claude_callback_kwargs=claude_callback_kwargs,
            reason="Codex CLI not available on this machine",
            config=config,
            codex_config=codex_config,
            progress_callback=progress_callback,
        )

    # 2. Pre-execution checkpoint + content snapshot
    pre_checkpoint = checkpoint_create(f"pre-codex-wave-{wave_letter}", cwd)
    content_snapshot = snapshot_for_rollback(cwd, pre_checkpoint)

    # 3. Wrap prompt for Codex
    try:
        from .codex_prompts import wrap_prompt_for_codex
        codex_prompt = wrap_prompt_for_codex(wave_letter, prompt)
    except ImportError:
        codex_prompt = prompt

    # 4. Execute via Codex
    execute_codex = getattr(codex_transport_module, "execute_codex", None)
    if execute_codex is None:
        logger.error("Wave %s: codex_transport_module has no execute_codex()", wave_letter)
        return await _claude_fallback(
            prompt=prompt, claude_callback=claude_callback,
            claude_callback_kwargs=claude_callback_kwargs,
            reason="execute_codex function not found in codex_transport_module",
            config=config,
            codex_config=codex_config,
            progress_callback=progress_callback,
        )

    try:
        codex_result = execute_codex(
            codex_prompt,
            cwd,
            codex_config,
            codex_home,
            progress_callback=progress_callback,
        )
        if _inspect.isawaitable(codex_result):
            codex_result = await codex_result
    except WaveWatchdogTimeoutError as exc:
        logger.warning(
            "Wave %s: WaveWatchdogTimeoutError — rollback + Claude fallback (was: re-raise)",
            wave_letter,
        )
        post_checkpoint = checkpoint_create(f"post-codex-fail-{wave_letter}", cwd)
        rollback_from_snapshot(cwd, content_snapshot, pre_checkpoint,
                               post_checkpoint, checkpoint_diff)
        return await _claude_fallback(
            prompt=prompt, claude_callback=claude_callback,
            claude_callback_kwargs=claude_callback_kwargs,
            reason=f"WaveWatchdogTimeoutError: {exc}",
            config=config,
            codex_config=codex_config,
            progress_callback=progress_callback,
        )
    except _CodexOrphanToolError as exc:
        logger.warning(
            "Wave %s: CodexOrphanToolError (tool=%s, age=%.0fs, count=%d) — rollback + Claude fallback",
            wave_letter, exc.tool_name, exc.age_seconds, exc.orphan_count,
        )
        post_checkpoint = checkpoint_create(f"post-codex-fail-{wave_letter}", cwd)
        rollback_from_snapshot(cwd, content_snapshot, pre_checkpoint,
                               post_checkpoint, checkpoint_diff)
        return await _claude_fallback(
            prompt=prompt, claude_callback=claude_callback,
            claude_callback_kwargs=claude_callback_kwargs,
            reason=f"CodexOrphanToolError: {exc}",
            config=config,
            codex_config=codex_config,
            progress_callback=progress_callback,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Wave %s: Codex execution raised: %s", wave_letter, exc)
        post_checkpoint = checkpoint_create(f"post-codex-fail-{wave_letter}", cwd)
        rollback_from_snapshot(cwd, content_snapshot, pre_checkpoint,
                               post_checkpoint, checkpoint_diff)
        return await _claude_fallback(
            prompt=prompt, claude_callback=claude_callback,
            claude_callback_kwargs=claude_callback_kwargs,
            reason=f"Codex raised: {exc}",
            config=config,
            codex_config=codex_config,
            progress_callback=progress_callback,
        )

    # 5. Evaluate result
    if getattr(codex_result, "success", False):
        post_checkpoint = checkpoint_create(f"post-codex-wave-{wave_letter}", cwd)
        diff = checkpoint_diff(pre_checkpoint, post_checkpoint)
        created = list(getattr(diff, "created", []))
        modified = list(getattr(diff, "modified", []))
        deleted = list(getattr(diff, "deleted", []))
        changed = created + modified
        if not (created or modified or deleted):
            logger.warning(
                "Wave %s: Codex reported success but produced no tracked file changes; using Claude fallback",
                wave_letter,
            )
            return await _claude_fallback(
                prompt=prompt,
                config=config,
                claude_callback=claude_callback,
                claude_callback_kwargs=claude_callback_kwargs,
                reason="Codex reported success but produced no tracked file changes",
                codex_result=codex_result,
                codex_config=codex_config,
                progress_callback=progress_callback,
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

    # 6. Failure — rollback and fall back to Claude
    error_msg = (getattr(codex_result, "error", "") or "")[:200]
    logger.warning("Wave %s: Codex failed (exit=%s, error=%s) — rollback + Claude fallback",
                   wave_letter, getattr(codex_result, "exit_code", "?"), error_msg)
    post_checkpoint = checkpoint_create(f"post-codex-fail-{wave_letter}", cwd)
    rollback_from_snapshot(cwd, content_snapshot, pre_checkpoint,
                           post_checkpoint, checkpoint_diff)
    return await _claude_fallback(
        prompt=prompt, claude_callback=claude_callback,
        claude_callback_kwargs=claude_callback_kwargs,
        reason=f"Codex failed: {error_msg}",
        config=config,
        codex_result=codex_result,
        codex_config=codex_config,
        progress_callback=progress_callback,
    )

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
