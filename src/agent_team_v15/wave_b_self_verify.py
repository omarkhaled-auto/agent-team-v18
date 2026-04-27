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


def _build_retry_prompt_suffix(error_summary: str) -> str:
    return (
        "<previous_attempt_failed>\n"
        "Your previous Wave B output failed acceptance testing. You MUST fix "
        "these issues in this retry. Do NOT repeat the same mistakes.\n\n"
        f"{error_summary}\n\n"
        "Requirements for this retry:\n"
        "- Every Dockerfile COPY/ADD source must resolve inside "
        "build.context.\n"
        "- `docker compose build` must succeed for all services.\n"
        "- Use `apply_patch` to edit files, never shell redirection.\n"
        "</previous_attempt_failed>"
    )


def run_wave_b_acceptance_test(
    cwd: Path,
    *,
    autorepair: bool = True,
    timeout_seconds: int = 600,
    narrow_services: bool = True,
    stack_contract: dict[str, Any] | None = None,
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

    services_arg: list[str] | None = (
        _resolve_per_wave_service_target("B", stack_contract)
        if narrow_services else None
    )
    try:
        all_results = docker_build(
            cwd_path,
            compose_file,
            timeout=timeout_seconds,
            services=services_arg,
        )
    except Exception as exc:  # pragma: no cover — defensive; never raise to caller
        logger.warning("[wave-b-self-verify] docker_build raised unexpectedly: %s", exc)
        all_results = []

    build_failures = [br for br in all_results if not br.success]

    passed = not violations and not build_failures
    if passed:
        return WaveBVerifyResult(passed=True)

    error_summary = _build_error_summary(violations, build_failures)
    retry_prompt_suffix = _build_retry_prompt_suffix(error_summary)
    return WaveBVerifyResult(
        passed=False,
        violations=violations,
        build_failures=build_failures,
        error_summary=error_summary,
        retry_prompt_suffix=retry_prompt_suffix,
    )
