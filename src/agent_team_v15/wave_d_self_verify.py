"""Wave D in-wave acceptance test: compose sanity + docker build (web only).

Phase 4.1 mirror of :mod:`agent_team_v15.wave_b_self_verify` for the frontend
wave. Where Wave B narrows ``docker compose build`` to ``api``, Wave D
narrows it to ``web`` — each wave is graded on its own deliverable per
plan §D Risk #23.

The 2026-04-26 M1 hardening smoke
(``v18 test runs/m1-hardening-smoke-20260426-173745/``) shows Wave B
retried 3 times, all graded on the FULL compose, with retry-2 failing
on ``service=web`` — Wave D's deliverable that hadn't even run yet. With
this module wired in alongside the existing Wave B helper, each wave
gets its own deterministic acceptance bar and never blocks on a sibling
wave's output.

Same contract as Wave B's helper: never retries, never raises on Docker
or compose-sanity errors, always returns a :class:`WaveDVerifyResult`.
The retry policy lives in ``wave_executor`` so each attempt accumulates
on ``wave_result.findings``.

Phase 4.2 replaces the thin ``_build_retry_prompt_suffix`` here with a
shim that delegates to
:func:`agent_team_v15.retry_feedback.build_retry_payload` —
the same shared payload Wave B uses, with ``wave_letter="D"`` driving
Wave D-specific framing (``docker compose build web`` etc.). The shim
preserves a legacy fallback when
``AuditTeamConfig.strong_retry_feedback_enabled=False``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .compose_sanity import ComposeSanityError, Violation, validate_compose_build_context
from .runtime_verification import BuildResult, check_docker_available, docker_build, find_compose_file
from .wave_b_self_verify import _resolve_per_wave_service_target

logger = logging.getLogger(__name__)

# Per-service stderr truncation — keep the retry prompt bounded.
_STDERR_MAX_CHARS = 2000


@dataclass
class WaveDVerifyResult:
    """Outcome of the Wave D in-wave acceptance test."""

    passed: bool
    violations: list[Violation] = field(default_factory=list)
    # Phase 5.6a — wave-scope per-service Docker diagnostic failures
    # (existing field; preserved verbatim). Used for fast retry
    # attribution. NOT authoritative for the Quality Contract gate.
    build_failures: list[BuildResult] = field(default_factory=list)
    error_summary: str = ""
    retry_prompt_suffix: str = ""
    # Mirror of Wave B's contract — see ``WaveBVerifyResult.env_unavailable``
    # for the full rationale (R1B1-server-req-fix). When True, Wave D output
    # was not validated because Docker daemon was unreachable; the wave
    # output is accepted as-authored and the caller MUST NOT trigger a
    # Wave D re-dispatch.
    env_unavailable: bool = False
    # Phase 5.6c — strict TypeScript compile-profile failures projected
    # from ``CompileResult.errors``. Populated when
    # ``tsc_strict_enabled=True`` and the compile profile reported real
    # errors (env-unavailability is reported via ``tsc_env_unavailable``
    # below, NOT in this list). Empty list when TSC was skipped /
    # passed. Closes R-#39.
    tsc_failures: list[str] = field(default_factory=list)
    # Phase 5.6b — project-scope ``docker compose build`` (no SERVICE
    # args) failures. AUTHORITATIVE for the Quality Contract build
    # gate per §B gate 2 — ``services=None`` builds every compose
    # service and is the contract Phase 5.5's resolver downstream
    # depends on. Empty list when project-scope Docker passed or was
    # skipped (``tsc_strict_enabled=False`` kill switch). Closes
    # R-#44 (M2 narrow-pass / broad-fail surface).
    project_build_failures: list[BuildResult] = field(default_factory=list)
    # Phase 5.6 — ``True`` when ``run_wave_compile_check`` was env-
    # blocked (TypeScript not installed; ``ENV_NOT_READY`` /
    # ``MISSING_COMMAND``). Distinct from ``env_unavailable`` so
    # operators can tell "Docker daemon dead" (skip whole gate) from
    # "TSC env not ready" (skip TSC subset only; project-scope Docker
    # still runs). The Wave D acceptance gate MUST NOT use this signal
    # to suppress a project-scope Docker failure — Phase 5.6b is
    # independent of TSC.
    tsc_env_unavailable: bool = False


def _format_violation(v: Violation) -> str:
    return (
        f"- service={v.service} source={v.source!r} reason={v.reason} "
        f"resolved={v.resolved_path}"
    )


def _format_build_failure(br: BuildResult) -> str:
    err = (br.error or "").strip()
    if len(err) > _STDERR_MAX_CHARS:
        err = err[:_STDERR_MAX_CHARS] + "\n…(truncated)"
    return f"- service={br.service} duration_s={br.duration_s:.2f}\n{err}"


def _build_error_summary(
    violations: list[Violation],
    build_failures: list[BuildResult],
) -> str:
    parts: list[str] = []
    if violations:
        parts.append("Compose build-context violations:")
        parts.extend(_format_violation(v) for v in violations)
    if build_failures:
        if parts:
            parts.append("")
        parts.append("Docker build failures (per service):")
        parts.extend(_format_build_failure(br) for br in build_failures)
    return "\n".join(parts)


def _build_retry_prompt_suffix(
    error_summary: str,
    *,
    stderr: str = "",
    modified_files: list[str] | None = None,
    project_root: str | None = None,
    prior_attempts: list[dict[str, Any]] | None = None,
    this_retry_index: int | None = None,
    extra_violations: list[dict[str, Any]] | None = None,
    strong_feedback_enabled: bool = True,
    wave_letter: str = "D",
) -> str:
    """Phase 4.2 shim — delegates to ``retry_feedback.build_retry_payload``.

    Symmetric with the Wave B shim (see ``wave_b_self_verify`` module
    docstring). ``wave_letter`` defaults to ``"D"`` here so Wave D-
    specific framing (``docker compose build web``) flows through the
    shared payload constructor automatically.
    """
    from .retry_feedback import (
        _legacy_retry_prompt_suffix,
        build_retry_payload,
    )

    if not strong_feedback_enabled:
        return _legacy_retry_prompt_suffix(
            error_summary, wave_letter=wave_letter
        )

    return build_retry_payload(
        stderr=stderr or error_summary,
        modified_files=modified_files or [],
        project_root=project_root or "",
        prior_attempts=prior_attempts or [],
        wave_letter=wave_letter,
        error_summary=error_summary if stderr else None,
        extra_violations=extra_violations,
        this_retry_index=this_retry_index,
    )


def run_wave_d_acceptance_test(
    cwd: Path,
    *,
    autorepair: bool = True,
    timeout_seconds: int = 600,
    narrow_services: bool = True,
    stack_contract: dict[str, Any] | None = None,
    modified_files: list[str] | None = None,
    prior_attempts: list[dict[str, Any]] | None = None,
    this_retry_index: int | None = None,
    strong_feedback_enabled: bool = True,
    tsc_strict_enabled: bool = True,
) -> WaveDVerifyResult:
    """Run compose sanity + Wave D unified build gate.

    Phase 5.6 unified gate runs THREE checks (when
    ``tsc_strict_enabled=True``, the default):

    * **5.6a (always runs) — wave-scope per-service Docker diagnostic.**
      Builds only the Wave D service (default ``["web"]``); preserves
      Phase 4.1 scope-narrowing for fast retry attribution.
    * **5.6b (gated by ``tsc_strict_enabled``) — project-scope all-
      services Docker build.** Calls ``docker_build(..., services=None)``
      so EVERY service in the compose file is built. Authoritative for
      the Quality Contract gate 2 (§B). Closes R-#44 narrow-pass /
      broad-fail divergence.
    * **5.6c (gated by ``tsc_strict_enabled``) — strict TypeScript
      compile profile.** Reuses
      :func:`compile_profiles.run_wave_compile_check` so generated
      and shared TypeScript surfaces (NOT just Wave D's deliverable)
      are covered. Closes R-#39 compile-vs-Docker divergence.

    Setting ``tsc_strict_enabled=False`` is the kill switch — gates BOTH
    5.6b AND 5.6c so the gate is byte-identical to pre-Phase-5.6
    (AC6 contract). 5.6a stays active.

    Failure semantics: any violation, any 5.6a failure, any 5.6b
    failure, OR any non-env-unavailable 5.6c failure → ``passed=False``.
    TSC env-unavailability (``ENV_NOT_READY`` / ``MISSING_COMMAND``)
    surfaces via ``tsc_env_unavailable=True`` and does NOT cause
    ``passed=False`` on its own — but it CANNOT suppress a 5.6b
    Docker failure (Phase 5.6 gate 5.6b is independent of TSC).

    Parameters
    ----------
    cwd:
        Project root used to locate the compose file and as the docker cwd.
    autorepair:
        Forwarded to :func:`validate_compose_build_context`. When ``True``
        (the Phase 6.0 default) compose-sanity violations are repaired in
        place; only violations that survive the repair are reported.
    timeout_seconds:
        Per-compose ``docker compose build`` timeout (applied to both
        wave-scope 5.6a AND project-scope 5.6b builds).
    narrow_services:
        Phase 4.1 scope-narrowing gate for the 5.6a wave-scope
        diagnostic. Default ``True``: Wave D builds only ``["web"]``
        (or stack-contract-derived equivalent) for the diagnostic.
        Flip to ``False`` to restore an all-services build for 5.6a
        (matches the Phase 4.1 rollback contract). Note: 5.6b ALWAYS
        runs project-scope (``services=None``) regardless of this flag.
    stack_contract:
        Optional dict-shape STACK_CONTRACT for service-name resolution.
    modified_files:
        Phase 4.2 — files Wave D's just-failed dispatch
        ``files_created + files_modified``. Threaded into the structured
        retry payload's unresolved-import scanner.
    prior_attempts:
        Phase 4.2 — WAVE_FINDINGS-shaped per-retry attribution.
    this_retry_index:
        Phase 4.2 — zero-based index of the current attempt.
    strong_feedback_enabled:
        Phase 4.2 master kill switch (mirrors
        ``AuditTeamConfig.strong_retry_feedback_enabled``).
    tsc_strict_enabled:
        Phase 5.6 master kill switch (mirrors
        ``RuntimeVerificationConfig.tsc_strict_check_enabled``).
        Default ``True`` per §I.1. When ``False``, 5.6b project-scope
        Docker AND 5.6c strict TSC are BOTH skipped — gate behaviour
        is byte-identical to pre-Phase-5.6 (AC6 contract). The
        §M.M11 calibration smoke is the operator-authorised activity
        that decides whether to flip the default.

    Returns
    -------
    WaveDVerifyResult
        ``passed=True`` when the compose file is absent OR all enabled
        Phase 5.6 checks pass.
    """
    cwd_path = Path(cwd).resolve()
    compose_file = find_compose_file(cwd_path)
    if compose_file is None:
        logger.info("[wave-d-self-verify] no compose file under %s — skipping", cwd_path)
        return WaveDVerifyResult(passed=True)

    if not check_docker_available():
        logger.warning(
            "[wave-d-self-verify] Docker daemon unreachable; SKIPPING acceptance "
            "test (env_unavailable=True). Wave output will be accepted as-authored."
        )
        return WaveDVerifyResult(
            passed=False,
            env_unavailable=True,
            error_summary=(
                "Docker daemon unreachable at acceptance-test time. "
                "Self-verify skipped; wave output accepted as-authored."
            ),
        )

    violations: list[Violation] = []
    try:
        violations = list(
            validate_compose_build_context(
                compose_file,
                autorepair=autorepair,
                project_root=cwd_path,
            )
        )
    except ComposeSanityError as exc:
        violations = list(exc.violations)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "[wave-d-self-verify] compose sanity raised unexpectedly: %s", exc
        )
        violations = []

    # Phase 5.6a — wave-scope per-service Docker diagnostic. ALWAYS runs.
    services_arg: list[str] | None = (
        _resolve_per_wave_service_target("D", stack_contract)
        if narrow_services else None
    )
    try:
        diagnostic_results = docker_build(
            cwd_path,
            compose_file,
            timeout=timeout_seconds,
            services=services_arg,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("[wave-d-self-verify] docker_build (5.6a) raised: %s", exc)
        diagnostic_results = []

    build_failures = [br for br in diagnostic_results if not br.success]

    # Phase 5.6b + 5.6c — both gated by ``tsc_strict_enabled``. Run
    # serially per §I.7 anti-pattern (don't parallelize: different
    # failure semantics).
    project_build_failures: list[BuildResult] = []
    tsc_failures_dicts: list[dict[str, Any]] = []
    tsc_env_unavailable = False
    tsc_compile_result_errors: list[dict[str, Any]] = []
    if tsc_strict_enabled:
        # Phase 5.6b — project-scope all-services Docker build (the
        # AUTHORITATIVE Quality Contract gate per §B gate 2). Always
        # runs even after a 5.6a failure so the retry payload has full
        # diagnostic data for the wave-self-verify retry loop.
        try:
            project_results = docker_build(
                cwd_path,
                compose_file,
                timeout=timeout_seconds,
                services=None,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "[wave-d-self-verify] docker_build (5.6b project-scope) raised: %s",
                exc,
            )
            project_results = []
        project_build_failures = [br for br in project_results if not br.success]

        # Phase 5.6c — strict TypeScript compile profile. Bridged to
        # sync via :func:`unified_build_gate.run_compile_profile_sync`
        # (thread-pool isolation; never raises to caller).
        from .unified_build_gate import (
            format_tsc_failures,
            is_compile_env_unavailable,
            run_compile_profile_sync,
        )
        compile_result = run_compile_profile_sync(
            cwd=str(cwd_path),
            wave_letter="D",
            project_root=cwd_path,
        )
        if is_compile_env_unavailable(compile_result):
            # TSC env not ready (pnpm not installed; tsc missing). Surface
            # via tsc_env_unavailable; do NOT count as wave failure on
            # its own. CRITICAL: this MUST NOT suppress a 5.6b project-
            # scope Docker failure — Phase 5.6 gate 5.6b is independent.
            tsc_env_unavailable = True
            tsc_compile_result_errors = []
        elif not compile_result.passed:
            tsc_compile_result_errors = list(compile_result.errors or [])
            tsc_failures_dicts = tsc_compile_result_errors
        # else: compile profile passed cleanly — nothing to record.
    tsc_failures_strs = (
        format_tsc_failures(tsc_failures_dicts)
        if tsc_failures_dicts
        else []
    )

    # Aggregate pass/fail decision. Phase 5.6 contract:
    #   * Compose violations → fail.
    #   * 5.6a wave-scope Docker failures → fail.
    #   * 5.6b project-scope Docker failures → fail (authoritative).
    #   * 5.6c real TSC failures → fail. Env-unavailable does NOT.
    passed = (
        not violations
        and not build_failures
        and not project_build_failures
        and not tsc_failures_dicts
    )
    if passed:
        return WaveDVerifyResult(
            passed=True,
            tsc_env_unavailable=tsc_env_unavailable,
        )

    error_summary = _build_error_summary(violations, build_failures)
    if project_build_failures:
        if error_summary:
            error_summary += "\n\n"
        error_summary += "Project-scope Docker build failures (authoritative; Phase 5.6b):\n"
        error_summary += "\n".join(
            _format_build_failure(br) for br in project_build_failures
        )
    if tsc_failures_strs:
        if error_summary:
            error_summary += "\n\n"
        error_summary += "TypeScript compile-profile failures (Phase 5.6c):\n"
        error_summary += "\n".join(f"- {line}" for line in tsc_failures_strs[:20])

    # Phase 4.2 — concatenate per-service raw stderrs for the structured
    # payload's extractors. Mirror of Wave B's contract. Phase 5.6
    # appends project-scope and TSC stderr blocks so the existing
    # ``retry_feedback`` extractors (TypeScript, BuildKit, Next.js) fire
    # against ALL Phase 5.6 failure surfaces in one payload.
    stderr_blocks: list[str] = []
    for br in build_failures:
        if (br.error or "").strip():
            stderr_blocks.append(
                f"--- service={br.service} duration_s={br.duration_s:.2f} ---\n"
                f"{(br.error or '').strip()}"
            )
    if project_build_failures:
        from .unified_build_gate import format_project_build_failures_as_stderr
        proj_block = format_project_build_failures_as_stderr(project_build_failures)
        if proj_block:
            stderr_blocks.append(proj_block)
    if tsc_compile_result_errors:
        from .unified_build_gate import format_tsc_failures_as_stderr
        tsc_block = format_tsc_failures_as_stderr(tsc_compile_result_errors)
        if tsc_block:
            stderr_blocks.append(tsc_block)
    stderr_concat = "\n\n".join(stderr_blocks)

    extra_violations_payload = [
        {
            "service": v.service,
            "source": v.source,
            "reason": v.reason,
            "resolved_path": v.resolved_path,
        }
        for v in violations
    ]
    retry_prompt_suffix = _build_retry_prompt_suffix(
        error_summary,
        stderr=stderr_concat,
        modified_files=modified_files,
        project_root=str(cwd_path),
        prior_attempts=prior_attempts,
        this_retry_index=this_retry_index,
        extra_violations=extra_violations_payload or None,
        strong_feedback_enabled=strong_feedback_enabled,
        wave_letter="D",
    )
    return WaveDVerifyResult(
        passed=False,
        violations=violations,
        build_failures=build_failures,
        error_summary=error_summary,
        retry_prompt_suffix=retry_prompt_suffix,
        tsc_failures=tsc_failures_strs,
        project_build_failures=project_build_failures,
        tsc_env_unavailable=tsc_env_unavailable,
    )
