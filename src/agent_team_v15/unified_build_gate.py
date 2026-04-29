"""Phase 5.6 — Unified strict build gate helpers.

Shared between :mod:`wave_b_self_verify` and :mod:`wave_d_self_verify` for
the Phase 5.6 unified acceptance gate (project-scope all-services Docker
build + strict TypeScript compile profile, gated by
``RuntimeVerificationConfig.tsc_strict_check_enabled``). Wave-letter-
agnostic — Wave B and Wave D consume identical helpers.

Plan: ``docs/plans/2026-04-28-phase-5-quality-milestone.md`` §I + §M.M5.

Risks closed by Phase 5.6 (and the contracts these helpers implement):

* **R-#39** (compile-fix vs acceptance-test build-check divergence) —
  ``compile_profiles.run_wave_compile_check`` now runs INSIDE the
  Wave B/D in-wave acceptance gate. Previously the strict TypeScript
  check only fired post-acceptance via ``_run_wave_compile``.
* **R-#44** (build-check scope divergence: wave-scope per-service vs
  project-scope all-services Docker build) — the Wave B/D acceptance
  test now runs ``docker_build(..., services=None)`` (project-scope
  all-services) AS THE AUTHORITATIVE CONTRACT, with the existing
  wave-scope per-service diagnostic preserved for retry attribution.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from pathlib import Path
from typing import Any

from .compile_profiles import CompileResult, run_wave_compile_check
from .runtime_verification import BuildResult

logger = logging.getLogger(__name__)

# Codes ``compile_profiles.run_wave_compile_check`` emits when the env
# itself is unavailable (TypeScript not installed, command missing).
# Phase 5.6 surfaces these as ``tsc_env_unavailable=True`` so operators
# can distinguish "TSC skipped because pnpm not installed" from "TSC
# errors found". CRITICAL: callers MUST NOT use this signal to suppress
# project-scope Docker failures — Phase 5.6 gate 5.6b is independent.
_COMPILE_ENV_UNAVAILABLE_CODES = frozenset({"ENV_NOT_READY", "MISSING_COMMAND"})


def run_compile_profile_sync(
    *,
    cwd: str,
    wave_letter: str,
    template: str = "",
    config: Any | None = None,
    milestone: Any | None = None,
    project_root: Path | None = None,
    stack_target: str = "",
    timeout_seconds: float | None = None,
) -> CompileResult:
    """Bridge :func:`compile_profiles.run_wave_compile_check` to a sync caller.

    The Wave B/D acceptance helpers are sync but ``run_wave_compile_check``
    is ``async`` (uses ``asyncio.subprocess`` for ``tsc`` invocation).
    ``asyncio.run`` raises ``RuntimeError`` when called from inside an
    already-running event loop — and the Wave B/D acceptance helpers are
    invoked from the wave-executor's main async loop at
    ``wave_executor.py:_execute_milestone_waves_with_stack_contract`` and
    from ``cli.py``'s async ``_run_audit_loop`` cascade epilogue.

    To stay safe regardless of caller context, this bridge ALWAYS runs
    the coroutine in a fresh thread with its own event loop via
    :class:`concurrent.futures.ThreadPoolExecutor`. The dedicated thread
    isolates the new ``asyncio.run`` call from the caller's loop;
    ``ThreadPoolExecutor`` cleans the thread up on context-manager exit.
    Overhead: ~1ms thread-spawn, well under the per-command 120s
    compile-profile budget.

    Timeout discipline (post-2026-04-29 reviewer correction):
    :func:`compile_profiles.run_wave_compile_check` already caps EACH
    command at 120s via ``asyncio.wait_for`` /
    ``asyncio.TimeoutError`` (see ``compile_profiles.py``). A profile
    with N commands is bounded at ``N * 120s`` worst-case; an aggregate
    bridge ceiling would FALSE-fail valid multi-command profiles
    (e.g. apps/api + apps/web + generated + shared TypeScript surfaces).
    The bridge therefore relies on the inner primitive's per-command
    discipline by default. The optional ``timeout_seconds`` kwarg is
    preserved for tests + future operator tuning; ``None`` (default)
    means "no aggregate ceiling — rely on inner primitive". Callers
    needing a defensive aggregate ceiling can pass an explicit value.

    On bridge timeout (when ``timeout_seconds`` is set) or arbitrary
    exception, returns a synthesised failure :class:`CompileResult` so
    callers can treat the bridge as never-raising. The Wave B/D helper
    contract is "never raise to the wave-executor loop"; this preserves
    it.

    Parameters mirror :func:`compile_profiles.run_wave_compile_check`.
    """
    def _runner() -> CompileResult:
        # Inside the dedicated worker thread we always create a fresh
        # event loop via ``asyncio.run``. The thread has no prior loop,
        # so ``asyncio.run`` is safe here regardless of the caller's
        # thread state.
        return asyncio.run(
            run_wave_compile_check(
                cwd=cwd,
                wave=wave_letter,
                template=template,
                config=config,
                milestone=milestone,
                project_root=project_root or Path(cwd),
                stack_target=stack_target,
            )
        )

    logger.info(
        "[unified-build-gate] 5.6c compile profile starting (wave=%s)",
        wave_letter,
    )
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_runner)
            # ``Future.result(timeout=None)`` blocks indefinitely; the
            # inner primitive's per-command 120s discipline bounds total
            # execution. Tests + future operator tuning may pass an
            # explicit aggregate ceiling.
            result = future.result(timeout=timeout_seconds)
        logger.info(
            "[unified-build-gate] 5.6c compile profile complete "
            "(wave=%s): passed=%s errors=%d",
            wave_letter,
            result.passed,
            len(result.errors or []),
        )
        return result
    except concurrent.futures.TimeoutError:
        # Only fires when the caller passed an explicit
        # ``timeout_seconds``. Default (None) does not impose an
        # aggregate ceiling, so this path is opt-in.
        ceiling = (
            f"{timeout_seconds:.0f}s"
            if timeout_seconds is not None
            else "<no aggregate ceiling>"
        )
        logger.warning(
            "[unified-build-gate] 5.6c compile profile timed out after %s "
            "(wave=%s)",
            ceiling,
            wave_letter,
        )
        return CompileResult(
            passed=False,
            error_count=1,
            errors=[
                {
                    "file": "",
                    "line": 0,
                    "code": "TIMEOUT",
                    "message": (
                        f"Compile profile bridge timed out after {ceiling}"
                    ),
                }
            ],
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "[unified-build-gate] 5.6c compile profile raised unexpectedly "
            "(wave=%s): %s",
            wave_letter,
            exc,
        )
        return CompileResult(
            passed=False,
            error_count=1,
            errors=[
                {
                    "file": "",
                    "line": 0,
                    "code": "BRIDGE_ERROR",
                    "message": f"Compile profile bridge failed: {exc}",
                }
            ],
        )


def is_compile_env_unavailable(result: CompileResult) -> bool:
    """Decide whether ``run_wave_compile_check`` was env-blocked.

    Returns True when EVERY error in ``result.errors`` carries an
    env-unavailability code (``ENV_NOT_READY`` from the Windows App
    Execution Alias sentinel or ``MISSING_COMMAND`` from a missing
    executable). Mixed results — one env error + one real TS error —
    return False; real signal dominates.

    Critically, the Phase 5.6 caller uses this signal to set
    ``tsc_env_unavailable=True`` on the Wave-verify result, but does
    NOT use it to suppress a project-scope Docker failure. R-#44
    closure requires that gate 5.6b (project-scope all-services) fail
    the wave even when TSC was env-skipped.
    """
    if result.passed:
        return False
    if not result.errors:
        return False
    return all(
        str(err.get("code", "") or "").strip() in _COMPILE_ENV_UNAVAILABLE_CODES
        for err in result.errors
    )


def format_tsc_failures(errors: list[dict[str, Any]]) -> list[str]:
    """Project ``CompileResult.errors`` dicts to formatted strings.

    Used to populate ``WaveBVerifyResult.tsc_failures`` /
    ``WaveDVerifyResult.tsc_failures`` per plan §I.4. Cap at 50 entries
    so the result struct stays bounded.
    """
    formatted: list[str] = []
    for err in errors[:50]:
        file_path = str(err.get("file", "") or "").strip()
        line = err.get("line", 0) or 0
        code = str(err.get("code", "") or "").strip()
        message = str(err.get("message", "") or "").strip()
        if file_path:
            formatted.append(
                f"{file_path}:{line} {code} {message}".rstrip()
            )
        else:
            formatted.append(f"{code} {message}".rstrip())
    return formatted


def format_tsc_failures_as_stderr(errors: list[dict[str, Any]]) -> str:
    """Serialise ``CompileResult.errors`` to canonical tsc-stderr shape.

    ``retry_feedback.build_retry_payload`` extracts TypeScript
    diagnostics from a ``stderr`` parameter via regex
    (``file(line,col): error TSXXXX: message``). To re-feed our
    structured errors into the same payload (so the Phase 4.2
    progressive-signal + parsed-errors sections fire), we serialise
    them in the canonical shape and concatenate.
    """
    lines: list[str] = []
    for err in errors:
        file_path = str(err.get("file", "") or "")
        line = err.get("line", 0) or 0
        code = str(err.get("code", "") or "TS_UNKNOWN")
        message = str(err.get("message", "") or "")
        if file_path:
            lines.append(f"{file_path}({line},0): error {code}: {message}")
        elif code or message:
            lines.append(f"error {code}: {message}".strip())
    return "\n".join(lines)


def format_project_build_failures_as_stderr(
    failures: list[BuildResult],
) -> str:
    """Serialise per-service ``BuildResult`` failures to stderr text.

    Mirrors the wave-scope diagnostic serialisation pattern used by
    the existing ``_build_retry_prompt_suffix`` shims. The project-
    scope marker (``project-scope service=X``) lets the consumer
    distinguish 5.6b failures from 5.6a failures in the retry payload.
    """
    blocks: list[str] = []
    for br in failures:
        err = (br.error or "").strip()
        if not err:
            continue
        blocks.append(
            f"--- project-scope service={br.service} "
            f"duration_s={br.duration_s:.2f} ---\n{err}"
        )
    return "\n\n".join(blocks)


__all__ = (
    "format_project_build_failures_as_stderr",
    "format_tsc_failures",
    "format_tsc_failures_as_stderr",
    "is_compile_env_unavailable",
    "run_compile_profile_sync",
)
