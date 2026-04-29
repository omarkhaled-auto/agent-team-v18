"""Wave B in-wave acceptance test: compose sanity + docker build, with error-aware retry.

Called from wave_executor after Wave B's initial turn completes. If the build
fails, constructs an augmented prompt with the error text and returns it to
the caller so Wave B can be re-dispatched. Codex is one-turn-only, so we
cannot resume a session — each retry is a fresh dispatch with the same wave
prompt + error context appended.

The helper itself never retries: the retry loop lives in ``wave_executor`` so
``wave_result.findings`` can accumulate a record for every attempt. The helper
also never raises on Docker or compose-sanity errors — it returns a
:class:`WaveBVerifyResult` with ``passed=False``. Policy (retry? fail the
wave?) belongs to the caller.

Phase 4.1 introduces ``_resolve_per_wave_service_target`` so each wave
self-verifies only on its own deliverable. The ``narrow_services`` kwarg on
``run_wave_b_acceptance_test`` defaults to ``True`` (new behaviour — Wave B
builds only ``api``); flip the master ``AuditTeamConfig.per_wave_self_verify_enabled``
flag to False to restore the legacy full-compose behaviour.

Phase 4.2 replaces the legacy ``_build_retry_prompt_suffix`` body with a thin
shim that delegates to :func:`agent_team_v15.retry_feedback.build_retry_payload`
when ``strong_feedback_enabled=True`` (the default; controlled by
``AuditTeamConfig.strong_retry_feedback_enabled``). The new payload is
structured, deterministic, ≥10× richer than the legacy ~150-byte block, and
bounded at 12 KB. Wave_executor threads ``modified_files`` and
``prior_attempts`` through ``run_wave_b_acceptance_test`` so the payload
includes parsed compile errors, unresolved-import findings, and progressive
signal across retries. See ``retry_feedback.py`` module docstring for the
full contract.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .compose_sanity import ComposeSanityError, Violation, validate_compose_build_context
from .runtime_verification import BuildResult, check_docker_available, docker_build, find_compose_file

logger = logging.getLogger(__name__)

# Per-service stderr truncation — keep the retry prompt bounded while still
# giving the model enough context to find the offending COPY/ADD or layer.
_STDERR_MAX_CHARS = 2000


# Phase 4.1 default wave-letter → compose-service-name mapping. The smoke
# evidence at ``v18 test runs/m1-hardening-smoke-20260426-173745/`` shows
# Wave B was graded on the FULL compose (api + web), and retry-2 only
# failed on ``service=web`` — Wave D's deliverable. Narrowing each wave
# to its own service is the structural fix.
_DEFAULT_WAVE_SERVICE_MAP: dict[str, tuple[str, ...]] = {
    "B": ("api",),
    "D": ("web",),
    "T": ("api", "web"),
}


def _resolve_per_wave_service_target(
    wave_letter: str,
    stack_contract: dict[str, Any] | None = None,
) -> list[str]:
    """Map a wave letter to the compose service names it owns.

    Returns ``["api"]`` for B, ``["web"]`` for D, ``["api", "web"]`` for T,
    and ``[]`` for waves that do not run docker self-verify (A, A5, C,
    scaffold). Stack contract overrides, in order:

    1. Explicit ``wave_self_verify_services: {<letter>: [<svc>, ...]}``
       field on STACK_CONTRACT.json (forward-compat for non-default
       service-name layouts).
    2. Derived from ``backend_path_prefix`` / ``frontend_path_prefix`` —
       the last path component is taken as the canonical service name
       (e.g. ``apps/api/`` → ``api``, ``services/backend/`` → ``backend``).
       This auto-adapts to the actual project layout when the smoke's
       canonical ``api``/``web`` names don't apply.

    Always returns a fresh list — callers that mutate the result do not
    contaminate the module-level default map.
    """
    if stack_contract:
        explicit = stack_contract.get("wave_self_verify_services")
        if isinstance(explicit, dict) and wave_letter in explicit:
            value = explicit[wave_letter]
            if isinstance(value, list):
                return [str(s) for s in value if isinstance(s, str)]

        derived: dict[str, list[str]] = {}
        backend_prefix = stack_contract.get("backend_path_prefix")
        if isinstance(backend_prefix, str) and backend_prefix.strip("/"):
            backend_svc = backend_prefix.strip("/").rsplit("/", 1)[-1]
            if backend_svc:
                derived["B"] = [backend_svc]
        frontend_prefix = stack_contract.get("frontend_path_prefix")
        if isinstance(frontend_prefix, str) and frontend_prefix.strip("/"):
            frontend_svc = frontend_prefix.strip("/").rsplit("/", 1)[-1]
            if frontend_svc:
                derived["D"] = [frontend_svc]
        if "B" in derived and "D" in derived:
            derived["T"] = derived["B"] + derived["D"]
        if wave_letter in derived:
            return list(derived[wave_letter])

    return list(_DEFAULT_WAVE_SERVICE_MAP.get(wave_letter, ()))


@dataclass
class WaveBVerifyResult:
    """Outcome of the Wave B in-wave acceptance test."""

    passed: bool
    violations: list[Violation] = field(default_factory=list)
    # Phase 5.6a — wave-scope per-service Docker diagnostic failures
    # (existing field; preserved verbatim). Used for fast retry
    # attribution. NOT authoritative for the Quality Contract gate.
    build_failures: list[BuildResult] = field(default_factory=list)
    error_summary: str = ""
    retry_prompt_suffix: str = ""
    # ``True`` when the acceptance test was SKIPPED because the Docker
    # daemon is unreachable (Docker Desktop crashed / not started / WSL
    # backend degraded). The wave output was not validated, but this is
    # an environmental signal — not a Codex-authored Dockerfile bug — so
    # the caller MUST NOT trigger a Wave B re-dispatch on env_unavailable
    # (see wave_executor.py self-verify retry loop). R1B1-server-req-fix
    # (2026-04-22) burned an entire Wave B turn (620s Codex wedge) trying
    # to repair a Dockerfile when the real problem was Docker daemon 500s
    # at /_ping — this flag prevents that.
    env_unavailable: bool = False
    # Phase 5.6c — strict TypeScript compile-profile failures projected
    # from ``CompileResult.errors`` (real diagnostics only; env-
    # unavailability is reported via ``tsc_env_unavailable``).
    # Closes R-#39.
    tsc_failures: list[str] = field(default_factory=list)
    # Phase 5.6b — project-scope ``docker compose build`` failures
    # (no SERVICE args). AUTHORITATIVE for the Quality Contract build
    # gate per §B gate 2. Closes R-#44.
    project_build_failures: list[BuildResult] = field(default_factory=list)
    # Phase 5.6 — TSC env-unavailability signal. Distinct from
    # ``env_unavailable``; never suppresses a 5.6b Docker failure.
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
    wave_letter: str = "B",
) -> str:
    """Phase 4.2 shim — delegates to ``retry_feedback.build_retry_payload``.

    When ``strong_feedback_enabled`` is True (default; controlled by
    ``AuditTeamConfig.strong_retry_feedback_enabled``), the
    ``<previous_attempt_failed>`` block is composed by the structured
    Phase 4.2 payload. When False, falls back to the legacy ~150-byte
    block preserved as ``retry_feedback._legacy_retry_prompt_suffix``
    for one release cycle of rollback contract.

    Pre-Phase-4.2 callers that pass only ``error_summary`` continue to
    work — the strong-feedback path produces a non-empty payload from
    the summary alone (no progressive signal, but parsed errors land
    if the summary contains them, plus the framing + requirements).
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


def run_wave_b_acceptance_test(
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
) -> WaveBVerifyResult:
    """Run compose sanity + docker build as Wave B's acceptance test.

    Parameters
    ----------
    cwd:
        Project root used to locate the compose file and as the docker cwd.
    autorepair:
        Forwarded to :func:`validate_compose_build_context`. When ``True``
        (the Phase 6.0 default) compose-sanity violations are repaired in
        place; only violations that survive the repair are reported.
    timeout_seconds:
        Per-compose ``docker compose build`` timeout.
    narrow_services:
        Phase 4.1 scope-narrowing gate. Default ``True``: Wave B builds
        only ``["api"]`` (or stack-contract-derived equivalent), so Wave
        B is graded only on its own deliverable. Flip to ``False`` (e.g.
        when ``AuditTeamConfig.per_wave_self_verify_enabled`` is False)
        to restore the legacy all-services build.
    stack_contract:
        Optional dict-shape STACK_CONTRACT for service-name resolution.
        See :func:`_resolve_per_wave_service_target` for the precedence
        order.
    modified_files:
        Phase 4.2 — files Wave B's just-failed dispatch
        ``files_created + files_modified``. Threaded into the structured
        retry payload's unresolved-import scanner. ``None`` (default)
        is equivalent to ``[]`` (no scan; payload still composes).
    prior_attempts:
        Phase 4.2 — WAVE_FINDINGS-shaped per-retry attribution. Each
        entry: ``{"retry": int, "failing_services": list[str],
        "error_summary": str}``. Sourced from accumulated
        ``self_verify_findings`` in the wave_executor retry loop.
        ``None`` (default) is equivalent to ``[]``.
    this_retry_index:
        Phase 4.2 — zero-based index of the current attempt. When
        omitted, ``build_retry_payload`` derives from ``prior_attempts``.
    strong_feedback_enabled:
        Phase 4.2 master kill switch (mirrors
        ``AuditTeamConfig.strong_retry_feedback_enabled``). True
        (default) → structured ≥1500-byte payload. False → legacy
        ~150-byte block.

    Returns
    -------
    WaveBVerifyResult
        ``passed=True`` when either the compose file is absent (no-docker
        milestone) or compose sanity is clean AND every targeted service
        builds.
    """
    cwd_path = Path(cwd).resolve()
    compose_file = find_compose_file(cwd_path)
    if compose_file is None:
        logger.info("[wave-b-self-verify] no compose file under %s — skipping", cwd_path)
        return WaveBVerifyResult(passed=True)

    # Check Docker daemon BEFORE attempting compose-sanity / docker_build.
    # If Docker Desktop / WSL backend is unhealthy, neither compose validation
    # nor docker build can actually run, and any "failure" they report would
    # be about the environment, not the Codex-authored files. Returning a
    # ``passed=False, env_unavailable=True`` result lets the caller skip the
    # retry loop (which would otherwise burn Codex turns trying to fix a
    # Dockerfile that's fine). The wave output is accepted as-authored; the
    # skip is recorded as a WaveFinding so operators see it.
    if not check_docker_available():
        logger.warning(
            "[wave-b-self-verify] Docker daemon unreachable; SKIPPING acceptance "
            "test (env_unavailable=True). Wave output will be accepted as-authored."
        )
        return WaveBVerifyResult(
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
        # autorepair=False contract (or repair ran out of options): collect
        # the violations and surface them without raising.
        violations = list(exc.violations)
    except Exception as exc:  # pragma: no cover — defensive; never raise to caller
        logger.warning(
            "[wave-b-self-verify] compose sanity raised unexpectedly: %s", exc
        )
        violations = []

    # Phase 5.6a — wave-scope per-service Docker diagnostic. ALWAYS runs.
    services_arg: list[str] | None = (
        _resolve_per_wave_service_target("B", stack_contract)
        if narrow_services else None
    )
    try:
        diagnostic_results = docker_build(
            cwd_path,
            compose_file,
            timeout=timeout_seconds,
            services=services_arg,
        )
    except Exception as exc:  # pragma: no cover — defensive; never raise to caller
        logger.warning("[wave-b-self-verify] docker_build (5.6a) raised: %s", exc)
        diagnostic_results = []

    build_failures = [br for br in diagnostic_results if not br.success]

    # Phase 5.6b + 5.6c — both gated by ``tsc_strict_enabled``. Run
    # serially per §I.7 anti-pattern (don't parallelize). Mirror of
    # Wave D's contract; see ``wave_d_self_verify.run_wave_d_acceptance_test``
    # for the canonical decision logic + Phase 5.6 risk-closure mapping.
    project_build_failures: list[BuildResult] = []
    tsc_failures_dicts: list[dict[str, Any]] = []
    tsc_env_unavailable = False
    tsc_compile_result_errors: list[dict[str, Any]] = []
    if tsc_strict_enabled:
        # Phase 5.6b — project-scope all-services Docker build (the
        # AUTHORITATIVE Quality Contract gate per §B gate 2). Mirror
        # of Wave D; see ``wave_d_self_verify.run_wave_d_acceptance_test``
        # for fail-CLOSED rationale on exception.
        logger.info(
            "[wave-b-self-verify] 5.6b project-scope docker compose build "
            "(services=None) starting"
        )
        try:
            project_results = docker_build(
                cwd_path,
                compose_file,
                timeout=timeout_seconds,
                services=None,
            )
        except Exception as exc:
            logger.warning(
                "[wave-b-self-verify] docker_build (5.6b project-scope) raised: "
                "%s — failing the wave on the authoritative gate",
                exc,
            )
            project_results = [
                BuildResult(
                    service="(all)",
                    success=False,
                    duration_s=0.0,
                    error=(
                        f"Phase 5.6b project-scope docker_build raised: "
                        f"{exc.__class__.__name__}: {exc}"
                    )[:500],
                )
            ]
        project_build_failures = [br for br in project_results if not br.success]
        logger.info(
            "[wave-b-self-verify] 5.6b project-scope docker compose build "
            "complete: %d failure(s)",
            len(project_build_failures),
        )

        from .unified_build_gate import (
            format_tsc_failures,
            is_compile_env_unavailable,
            run_compile_profile_sync,
        )
        compile_result = run_compile_profile_sync(
            cwd=str(cwd_path),
            wave_letter="B",
            project_root=cwd_path,
        )
        if is_compile_env_unavailable(compile_result):
            tsc_env_unavailable = True
            tsc_compile_result_errors = []
        elif not compile_result.passed:
            tsc_compile_result_errors = list(compile_result.errors or [])
            tsc_failures_dicts = tsc_compile_result_errors
    tsc_failures_strs = (
        format_tsc_failures(tsc_failures_dicts)
        if tsc_failures_dicts
        else []
    )

    passed = (
        not violations
        and not build_failures
        and not project_build_failures
        and not tsc_failures_dicts
    )
    if passed:
        return WaveBVerifyResult(
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

    # Phase 4.2 — concatenate per-service raw stderrs so the structured
    # payload's TypeScript / BuildKit / Next.js extractors run against
    # the actual command output, not just the formatted summary. Each
    # block is service-prefixed so the consumer can distinguish them.
    # Phase 5.6 appends project-scope and TSC stderr blocks.
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
        wave_letter="B",
    )
    return WaveBVerifyResult(
        passed=False,
        violations=violations,
        build_failures=build_failures,
        error_summary=error_summary,
        retry_prompt_suffix=retry_prompt_suffix,
        tsc_failures=tsc_failures_strs,
        project_build_failures=project_build_failures,
        tsc_env_unavailable=tsc_env_unavailable,
    )
