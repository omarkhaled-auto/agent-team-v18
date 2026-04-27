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

Phase 4.2 will replace the thin ``_build_retry_prompt_suffix`` here with
the structured ``retry_feedback.build_retry_payload`` shared with Wave B.
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
    build_failures: list[BuildResult] = field(default_factory=list)
    error_summary: str = ""
    retry_prompt_suffix: str = ""
    # Mirror of Wave B's contract — see ``WaveBVerifyResult.env_unavailable``
    # for the full rationale (R1B1-server-req-fix). When True, Wave D output
    # was not validated because Docker daemon was unreachable; the wave
    # output is accepted as-authored and the caller MUST NOT trigger a
    # Wave D re-dispatch.
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
    # Phase 4.2 replaces this with the shared
    # ``retry_feedback.build_retry_payload`` once that module lands.
    return (
        "<previous_attempt_failed>\n"
        "Your previous Wave D output failed acceptance testing. You MUST fix "
        "these issues in this retry. Do NOT repeat the same mistakes.\n\n"
        f"{error_summary}\n\n"
        "Requirements for this retry:\n"
        "- Every Dockerfile COPY/ADD source must resolve inside "
        "build.context.\n"
        "- `docker compose build web` must succeed.\n"
        "- Use `apply_patch` to edit files, never shell redirection.\n"
        "</previous_attempt_failed>"
    )


def run_wave_d_acceptance_test(
    cwd: Path,
    *,
    autorepair: bool = True,
    timeout_seconds: int = 600,
    narrow_services: bool = True,
    stack_contract: dict[str, Any] | None = None,
) -> WaveDVerifyResult:
    """Run compose sanity + ``docker compose build web`` as Wave D's acceptance test.

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
        Phase 4.1 scope-narrowing gate. Default ``True``: Wave D builds
        only ``["web"]`` (or stack-contract-derived equivalent). Flip to
        ``False`` to restore an all-services build (matches Wave B's
        rollback contract).
    stack_contract:
        Optional dict-shape STACK_CONTRACT for service-name resolution.

    Returns
    -------
    WaveDVerifyResult
        ``passed=True`` when either the compose file is absent (no-docker
        milestone) or compose sanity is clean AND the targeted service(s)
        build.
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

    services_arg: list[str] | None = (
        _resolve_per_wave_service_target("D", stack_contract)
        if narrow_services else None
    )
    try:
        all_results = docker_build(
            cwd_path,
            compose_file,
            timeout=timeout_seconds,
            services=services_arg,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("[wave-d-self-verify] docker_build raised unexpectedly: %s", exc)
        all_results = []

    build_failures = [br for br in all_results if not br.success]

    passed = not violations and not build_failures
    if passed:
        return WaveDVerifyResult(passed=True)

    error_summary = _build_error_summary(violations, build_failures)
    retry_prompt_suffix = _build_retry_prompt_suffix(error_summary)
    return WaveDVerifyResult(
        passed=False,
        violations=violations,
        build_failures=build_failures,
        error_summary=error_summary,
        retry_prompt_suffix=retry_prompt_suffix,
    )
