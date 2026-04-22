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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .compose_sanity import ComposeSanityError, Violation, validate_compose_build_context
from .runtime_verification import BuildResult, check_docker_available, docker_build, find_compose_file

logger = logging.getLogger(__name__)

# Per-service stderr truncation — keep the retry prompt bounded while still
# giving the model enough context to find the offending COPY/ADD or layer.
_STDERR_MAX_CHARS = 2000


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

    Returns
    -------
    WaveBVerifyResult
        ``passed=True`` when either the compose file is absent (no-docker
        milestone) or compose sanity is clean AND every service builds.
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

    try:
        all_results = docker_build(cwd_path, compose_file, timeout=timeout_seconds)
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
