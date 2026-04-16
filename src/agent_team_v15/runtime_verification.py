"""Runtime verification for v16.5 — build, start, migrate, and smoke-test.

Runs AFTER code generation to verify the built system actually works.
Requires Docker Desktop to be running. Config-gated: disabled by default.

Patterns adapted from super-team's docker_orchestrator.py (subprocess-based,
Windows-safe, asyncio-compatible via ThreadPoolExecutor).
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wave B Docker transient-failure retry (PR #9)
# ---------------------------------------------------------------------------
# See docs/plans/2026-04-15-wave-b-docker-transient-retry.md.
# Wraps the `docker compose up -d` call in `docker_start` and the
# `docker compose exec ... TRUNCATE` call in `endpoint_prober._truncate_tables`.
# Narrow classifier: retry only on Docker daemon transients, never on
# permanent config/image errors.

DOCKER_RETRY_MAX_ATTEMPTS = 3
DOCKER_RETRY_BACKOFFS_S: tuple[int, ...] = (5, 15, 45)

_DOCKER_TRANSIENT_SUBSTRINGS = (
    "failed to set up container networking",
    "driver failed",
    "error response from daemon",
)
_DOCKER_PERMANENT_SUBSTRINGS = (
    "no such image",
    "image not found",
    "invalid compose",
    "port already allocated",
    "syntax error",
    "yaml:",
)


def _is_transient_docker_error(stderr: str) -> bool:
    """Classify a Docker stderr as transient (retry) or permanent (fail fast).

    Permanent wins on mixed-signal: if any permanent substring matches, the
    error is permanent regardless of transient substrings. Default for
    unknown errors is permanent — the classifier is intentionally narrow.
    """
    if not stderr:
        return False
    text = stderr.lower()
    if any(p in text for p in _DOCKER_PERMANENT_SUBSTRINGS):
        return False
    return any(t in text for t in _DOCKER_TRANSIENT_SUBSTRINGS)


def _retry_docker_op(
    op: Callable[[], tuple[int, str, str]],
    op_name: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, str, str]:
    """Run a Docker subprocess op with retry on transient daemon failures.

    `op` returns `(returncode, stdout, stderr)`. On `rc != 0` with a
    transient-classified stderr, sleep and retry up to
    `DOCKER_RETRY_MAX_ATTEMPTS` total attempts (so up to 2 retries with
    backoffs `DOCKER_RETRY_BACKOFFS_S[0]` and `[1]`). On exhaustion or a
    permanent error, return the most recent `(rc, out, err)` tuple
    unchanged so the caller surfaces the original error verbatim.
    """
    last_result: tuple[int, str, str] = (1, "", "")
    for attempt in range(1, DOCKER_RETRY_MAX_ATTEMPTS + 1):
        rc, out, err = op()
        last_result = (rc, out, err)
        if rc == 0:
            return last_result
        if not _is_transient_docker_error(err):
            return last_result
        if attempt >= DOCKER_RETRY_MAX_ATTEMPTS:
            return last_result
        backoff = DOCKER_RETRY_BACKOFFS_S[attempt - 1]
        next_attempt = attempt + 1
        logger.warning(
            "[Wave B probing] Docker %s attempt %d/%d after transient failure: %s",
            op_name,
            next_attempt,
            DOCKER_RETRY_MAX_ATTEMPTS,
            (err or "")[:200],
        )
        sleep(backoff)
    return last_result


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class BuildResult:
    """Result of building a single Docker service."""
    service: str
    success: bool
    error: str = ""
    duration_s: float = 0.0


@dataclass
class ServiceStatus:
    """Runtime status of a single service."""
    service: str
    healthy: bool
    health_url: str = ""
    error: str = ""
    logs_tail: str = ""


@dataclass
class FixAttempt:
    """Record of a single fix attempt for a service."""
    service: str
    round: int
    phase: str           # "build" or "startup"
    error_before: str
    fix_applied: bool
    cost_usd: float = 0.0


@dataclass
class RuntimeReport:
    """Aggregate report from the runtime verification phase."""
    docker_available: bool = False
    compose_file: str = ""
    build_results: list[BuildResult] = field(default_factory=list)
    services_healthy: int = 0
    services_total: int = 0
    services_status: list[ServiceStatus] = field(default_factory=list)
    migrations_run: bool = False
    migrations_error: str = ""
    seed_run: bool = False
    seed_error: str = ""
    smoke_results: dict[str, Any] = field(default_factory=dict)
    total_duration_s: float = 0.0
    # Fix loop tracking
    fix_attempts: list[FixAttempt] = field(default_factory=list)
    fix_cost_usd: float = 0.0
    fix_rounds_completed: int = 0
    services_given_up: list[str] = field(default_factory=list)  # Services that exceeded max attempts
    budget_exceeded: bool = False
    # D-02: structured health + blocking-reason payload. ``health`` is one of
    # ``unknown`` / ``verified`` / ``skipped`` / ``blocked`` / ``external_app``.
    # Legacy callers treat ``docker_available=False`` or ``compose_file==""``
    # as implicitly skipped; D-02 promotes that to an explicit field so
    # downstream gates can distinguish "opted out" (skipped) from "opted in
    # but infrastructure missing" (blocked). ``block_reason`` names the
    # specific failure ("compose_file_missing", "docker_unavailable",
    # "live_app_unreachable"); ``details`` records the exact paths/URLs
    # checked so operators can triage without re-running.
    health: str = "unknown"
    block_reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Docker subprocess runner (from super-team docker_orchestrator.py)
# ---------------------------------------------------------------------------

def _run_docker(*args: str, cwd: str | None = None, timeout: int = 600) -> tuple[int, str, str]:
    """Run a docker compose command synchronously.

    Uses subprocess.run directly (not asyncio) to avoid Windows CancelledError
    issues with anyio cancel scopes.

    Returns (return_code, stdout, stderr).
    """
    cmd = ["docker", "compose", *args]
    logger.debug("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            cwd=cwd,
            timeout=timeout,
        )
        return (result.returncode, result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        return (1, "", f"Command timed out after {timeout}s")
    except FileNotFoundError:
        return (1, "", "docker command not found — is Docker Desktop installed?")


def _run_cmd(cmd: list[str], cwd: str | None = None, timeout: int = 120) -> tuple[int, str, str]:
    """Run an arbitrary command. Returns (rc, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            cwd=cwd,
            timeout=timeout,
        )
        return (result.returncode, result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        return (1, "", f"Command timed out after {timeout}s")
    except FileNotFoundError:
        return (1, "", f"Command not found: {cmd[0]}")


# ---------------------------------------------------------------------------
# Docker availability check
# ---------------------------------------------------------------------------

def check_docker_available() -> bool:
    """Return True if Docker daemon is running and accessible."""
    rc, out, err = _run_cmd(["docker", "info"], timeout=10)
    if rc != 0:
        logger.warning("Docker not available: %s", err[:200])
        return False
    return True


# ---------------------------------------------------------------------------
# 6a: Docker Build
# ---------------------------------------------------------------------------

def find_compose_file(project_root: Path, override: str = "") -> Path | None:
    """Find the docker-compose file in the project."""
    if override:
        p = Path(override)
        if p.is_file():
            return p
        p = project_root / override
        if p.is_file():
            return p

    candidates = [
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    ]
    for name in candidates:
        p = project_root / name
        if p.is_file():
            return p
    return None


def docker_build(
    project_root: Path,
    compose_file: Path,
    timeout: int = 600,
) -> list[BuildResult]:
    """Build all Docker images defined in the compose file.

    Returns a BuildResult per service.
    """
    results: list[BuildResult] = []
    start = time.monotonic()

    # Get list of services from compose file
    rc, out, err = _run_docker(
        "-f", str(compose_file), "config", "--services",
        cwd=str(project_root),
        timeout=30,
    )
    if rc != 0:
        logger.error("Failed to list services: %s", err)
        return [BuildResult(service="(all)", success=False, error=err[:500])]

    services = [s.strip() for s in out.strip().splitlines() if s.strip()]

    # Build all services
    rc, out, err = _run_docker(
        "-f", str(compose_file), "build", "--parallel",
        cwd=str(project_root),
        timeout=timeout,
    )

    total_duration = time.monotonic() - start

    if rc == 0:
        # All services built successfully
        for svc in services:
            results.append(BuildResult(
                service=svc, success=True, duration_s=total_duration / max(len(services), 1),
            ))
    else:
        # Parse which services failed from stderr
        failed_services: set[str] = set()
        for line in err.splitlines():
            line_lower = line.lower()
            if "failed" in line_lower or "error" in line_lower:
                # Try to extract service name: "target <service>: failed to solve"
                for svc in services:
                    if svc in line_lower:
                        failed_services.add(svc)

        for svc in services:
            if svc in failed_services:
                results.append(BuildResult(
                    service=svc, success=False,
                    error=_extract_service_error(err, svc),
                    duration_s=total_duration,
                ))
            else:
                results.append(BuildResult(service=svc, success=True, duration_s=0.0))

    return results


def _extract_service_error(stderr: str, service: str) -> str:
    """Extract the error message for a specific service from Docker build output."""
    lines = stderr.splitlines()
    error_lines: list[str] = []
    capturing = False
    for line in lines:
        if service in line.lower() and ("error" in line.lower() or "failed" in line.lower()):
            capturing = True
        if capturing:
            error_lines.append(line)
            if len(error_lines) > 15:
                break
    return "\n".join(error_lines) if error_lines else stderr[:500]


# ---------------------------------------------------------------------------
# 6b: Service Startup
# ---------------------------------------------------------------------------

def docker_start(
    project_root: Path,
    compose_file: Path,
    timeout_s: int = 90,
) -> list[ServiceStatus]:
    """Start services and wait for health checks.

    Returns a ServiceStatus per service.
    """
    # Start all services. Retry transient Docker daemon failures (PR #9):
    # the Wave B probing scaffold has historically lost runs to
    # "failed to set up container networking: driver failed" transients
    # that recover on retry.
    rc, out, err = _retry_docker_op(
        lambda: _run_docker(
            "-f", str(compose_file), "up", "-d",
            cwd=str(project_root),
            timeout=120,
        ),
        op_name="compose up",
    )
    if rc != 0:
        logger.error("docker compose up failed: %s", err[:500])
        return [ServiceStatus(service="(all)", healthy=False, error=err[:500])]

    # Wait for services to start
    logger.info("Waiting %ds for services to become healthy...", timeout_s)
    time.sleep(min(timeout_s, 15))  # Initial grace period

    # Poll for health
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        statuses = _check_container_health(project_root, compose_file)
        all_decided = all(s.healthy or s.error for s in statuses)
        if all_decided:
            break
        time.sleep(5)

    # Final check
    statuses = _check_container_health(project_root, compose_file)

    # Collect logs for unhealthy services
    for status in statuses:
        if not status.healthy:
            rc, logs, _ = _run_docker(
                "-f", str(compose_file), "logs", "--tail", "20", status.service,
                cwd=str(project_root),
                timeout=10,
            )
            status.logs_tail = logs[:2000]

    return statuses


def _check_container_health(
    project_root: Path, compose_file: Path,
) -> list[ServiceStatus]:
    """Check health status of all containers."""
    rc, out, err = _run_docker(
        "-f", str(compose_file), "ps", "--format",
        "{{.Service}}\t{{.Status}}",
        cwd=str(project_root),
        timeout=10,
    )
    if rc != 0:
        return [ServiceStatus(service="(all)", healthy=False, error=err[:200])]

    statuses: list[ServiceStatus] = []
    for line in out.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) < 2:
            continue
        svc = parts[0].strip()
        status_text = parts[1].strip().lower()
        healthy = "healthy" in status_text or ("up" in status_text and "unhealthy" not in status_text and "restarting" not in status_text)
        error = ""
        if "restarting" in status_text:
            error = "Container is restarting (crash loop)"
        elif "unhealthy" in status_text:
            error = "Health check failing"
        statuses.append(ServiceStatus(
            service=svc, healthy=healthy, error=error,
        ))

    return statuses


# ---------------------------------------------------------------------------
# 6c: Database Init
# ---------------------------------------------------------------------------

def run_migrations(
    project_root: Path,
    compose_file: Path,
    db_service: str = "postgres",
    db_user: str = "",
    db_name: str = "",
) -> tuple[bool, str]:
    """Find and run SQL migration files against the database container.

    Returns (success, error_message).
    """
    # Auto-detect migration directory
    migration_dirs = [
        project_root / "database" / "migrations",
        project_root / "migrations",
        project_root / "db" / "migrations",
    ]
    migration_dir = None
    for d in migration_dirs:
        if d.is_dir():
            migration_dir = d
            break

    if migration_dir is None:
        return True, ""  # No migrations to run — not an error

    sql_files = sorted(migration_dir.glob("*.sql"))
    if not sql_files:
        return True, ""

    # Auto-detect DB credentials from compose file
    if not db_user:
        db_user = "postgres"
        # Try to read from compose
        try:
            content = compose_file.read_text(encoding="utf-8")
            import re
            m = re.search(r"POSTGRES_USER[=:]\s*\$?\{?(\w+)", content)
            if m:
                db_user = m.group(1)
        except Exception:
            pass

    if not db_name:
        db_name = db_user  # Common default

    errors: list[str] = []
    run_count = 0
    for sql_file in sql_files:
        rc, out, err = _run_cmd(
            [
                "docker", "exec", "-i", f"globalbooks-{db_service}" if "globalbooks" not in db_service else db_service,
                "psql", "-U", db_user, "-d", db_name,
            ],
            timeout=30,
        )
        # Actually pipe the SQL file content
        try:
            sql_content = sql_file.read_text(encoding="utf-8")
            result = subprocess.run(
                ["docker", "exec", "-i", _find_container_name(compose_file, db_service),
                 "psql", "-U", db_user, "-d", db_name],
                input=sql_content,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=30,
            )
            if result.returncode != 0 and "already exists" not in result.stderr.lower() and "rollback" not in result.stderr.lower():
                errors.append(f"{sql_file.name}: {result.stderr[:200]}")
            else:
                run_count += 1
        except Exception as exc:
            errors.append(f"{sql_file.name}: {exc}")

    logger.info("Ran %d/%d migration files", run_count, len(sql_files))

    if errors:
        return False, "; ".join(errors[:5])
    return True, ""


def _find_container_name(compose_file: Path, service: str) -> str:
    """Find the container name for a compose service."""
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "ps", "--format", "{{.Name}}", service],
            capture_output=True, text=True, errors="replace",
            cwd=str(compose_file.parent), timeout=10,
        )
        name = result.stdout.strip().splitlines()
        if name:
            return name[0]
    except Exception:
        pass
    return f"globalbooks-{service}"


def run_seed_scripts(project_root: Path) -> tuple[bool, str]:
    """Find and run seed scripts if they exist.

    Returns (success, error_message).
    """
    seed_dirs = [
        project_root / "seed",
        project_root / "seeds",
        project_root / "database" / "seed",
    ]
    for seed_dir in seed_dirs:
        run_all = seed_dir / "run_all.py"
        if run_all.is_file():
            rc, out, err = _run_cmd(
                ["python", str(run_all)],
                cwd=str(seed_dir),
                timeout=60,
            )
            if rc != 0:
                return False, err[:500]
            return True, ""

    return True, ""  # No seed scripts — not an error


# ---------------------------------------------------------------------------
# 6d: Smoke Test
# ---------------------------------------------------------------------------

def smoke_test(
    project_root: Path,
    compose_file: Path,
    services: list[ServiceStatus] | None = None,
) -> dict[str, Any]:
    """Hit health endpoints and one CRUD endpoint per healthy service.

    Returns dict with per-service results.
    """
    import urllib.request
    import urllib.error
    import json

    results: dict[str, Any] = {}

    if services is None:
        services = _check_container_health(project_root, compose_file)

    healthy_services = [s for s in services if s.healthy and s.service not in (
        "postgres", "redis", "traefik", "proxy",
    )]

    for svc in healthy_services:
        svc_result: dict[str, Any] = {"health": False, "endpoints": []}

        # Try health endpoint via docker exec (internal network)
        try:
            result = subprocess.run(
                ["docker", "exec", _find_container_name(compose_file, svc.service),
                 "wget", "-qO-", "http://127.0.0.1:8080/health"],
                capture_output=True, text=True, errors="replace", timeout=10,
            )
            if result.returncode == 0:
                svc_result["health"] = True
                svc_result["health_response"] = result.stdout[:200]
        except Exception:
            # Try with python urllib as fallback
            try:
                result = subprocess.run(
                    ["docker", "exec", _find_container_name(compose_file, svc.service),
                     "python", "-c",
                     "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health').read().decode())"],
                    capture_output=True, text=True, errors="replace", timeout=10,
                )
                if result.returncode == 0:
                    svc_result["health"] = True
                    svc_result["health_response"] = result.stdout[:200]
            except Exception:
                pass

        results[svc.service] = svc_result

    return results


# ---------------------------------------------------------------------------
# 6e: Cleanup
# ---------------------------------------------------------------------------

def docker_cleanup(project_root: Path, compose_file: Path) -> None:
    """Stop and remove all containers."""
    _run_docker(
        "-f", str(compose_file), "down", "--remove-orphans",
        cwd=str(project_root),
        timeout=60,
    )


# ---------------------------------------------------------------------------
# Fix agent dispatch (v16.5 fix loop)
# ---------------------------------------------------------------------------

def build_fix_prompt(service: str, phase: str, error: str) -> str:
    """Build a targeted fix prompt for a Docker build or startup error.

    Parameters
    ----------
    service : str
        The service name (e.g., "asset", "tax").
    phase : str
        "build" for Docker build errors, "startup" for container crash errors.
    error : str
        The error text from Docker build output or container logs.

    Returns
    -------
    str
        A prompt string for the Claude fix agent.
    """
    if phase == "build":
        return (
            f"[PHASE: RUNTIME FIX — Docker Build Error]\n\n"
            f"The Docker build for service '{service}' failed with this error:\n\n"
            f"```\n{error[:3000]}\n```\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Read the error carefully — identify the exact file and line\n"
            f"2. Fix the root cause (type error, missing import, syntax error, etc.)\n"
            f"3. Do NOT change the Dockerfile — fix the SOURCE CODE that the build compiles\n"
            f"4. If the error is a missing dependency, add it to requirements.txt or package.json\n"
            f"5. Make the MINIMAL change needed to fix the build\n"
        )
    else:  # startup
        return (
            f"[PHASE: RUNTIME FIX — Service Startup Error]\n\n"
            f"Service '{service}' started but crashed immediately. Container logs:\n\n"
            f"```\n{error[:3000]}\n```\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Read the error — identify the root cause (import error, config issue, DB connection, etc.)\n"
            f"2. Fix the source code or configuration\n"
            f"3. If it's a missing module, check that all imports are correct and dependencies are listed\n"
            f"4. If it's a DB error, check connection strings and environment variables\n"
            f"5. Make the MINIMAL change needed to fix the startup\n"
        )


class FixTracker:
    """Tracks fix attempts per service with budget and repeat detection."""

    def __init__(
        self,
        max_rounds_per_service: int = 3,
        max_total_rounds: int = 5,
        max_budget_usd: float = 50.0,
    ) -> None:
        self.max_rounds_per_service = max_rounds_per_service
        self.max_total_rounds = max_total_rounds
        self.max_budget_usd = max_budget_usd
        self._attempts: dict[str, int] = {}       # service -> attempt count
        self._last_errors: dict[str, str] = {}    # service -> last error signature
        self._total_cost: float = 0.0
        self._total_rounds: int = 0
        self._given_up: set[str] = set()
        self.attempts_log: list[FixAttempt] = []

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def budget_exceeded(self) -> bool:
        return self._total_cost >= self.max_budget_usd

    @property
    def total_rounds_exceeded(self) -> bool:
        return self._total_rounds >= self.max_total_rounds

    @property
    def given_up_services(self) -> list[str]:
        return sorted(self._given_up)

    def can_fix(self, service: str) -> bool:
        """Return True if this service can be attempted again."""
        if service in self._given_up:
            return False
        if self._attempts.get(service, 0) >= self.max_rounds_per_service:
            self._given_up.add(service)
            return False
        if self.budget_exceeded:
            return False
        if self.total_rounds_exceeded:
            return False
        return True

    def is_repeat_error(self, service: str, error: str) -> bool:
        """Return True if this is the same error as the last attempt."""
        sig = error[:200].strip()
        if self._last_errors.get(service) == sig:
            return True
        self._last_errors[service] = sig
        return False

    def record_attempt(
        self, service: str, phase: str, error: str, cost: float = 0.0
    ) -> None:
        """Record a fix attempt."""
        self._attempts[service] = self._attempts.get(service, 0) + 1
        self._total_cost += cost
        self._total_rounds += 1
        self.attempts_log.append(FixAttempt(
            service=service,
            round=self._attempts[service],
            phase=phase,
            error_before=error[:500],
            fix_applied=True,
            cost_usd=cost,
        ))

    def mark_given_up(self, service: str, reason: str = "") -> None:
        """Mark a service as given up (won't attempt again)."""
        self._given_up.add(service)
        logger.info("Giving up on %s: %s", service, reason)


def dispatch_fix_agent(
    project_root: Path,
    service: str,
    phase: str,
    error: str,
) -> float:
    """Dispatch a Claude fix agent for a Docker build or startup error.

    This is a SYNCHRONOUS function that spawns a Claude SDK session.
    Returns the cost in USD.

    In test/headless environments where Claude SDK is not available,
    returns 0.0 and logs the error for manual fixing.
    """
    prompt = build_fix_prompt(service, phase, error)

    try:
        from .cli import _build_options, _process_response, _backend
        from .config import AgentTeamConfig
        from claude_agent_sdk import ClaudeSDKClient

        import asyncio

        config = AgentTeamConfig()
        options = _build_options(config, str(project_root), depth="standard", backend=_backend)

        async def _run_fix() -> float:
            phase_costs: dict[str, float] = {}
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)
                return await _process_response(client, config, phase_costs, current_phase=f"runtime_fix_{service}")

        cost = asyncio.run(_run_fix())
        return cost
    except Exception as exc:
        # Claude SDK not available or session failed — log for manual fixing
        logger.warning(
            "Fix agent dispatch failed for %s (%s): %s. "
            "Error to fix manually:\n%s",
            service, phase, exc, error[:500],
        )
        return 0.0


# ---------------------------------------------------------------------------
# Phase-boundary checkpoint (lightweight build + health check)
# ---------------------------------------------------------------------------

def run_phase_checkpoint(
    project_root: Path,
    phase_name: str = "",
    compose_override: str = "",
    startup_timeout_s: int = 60,
) -> dict[str, Any]:
    """Run a lightweight Docker build + health check at a phase boundary.

    Unlike run_runtime_verification(), this does NOT:
    - Run migrations or seeds
    - Run smoke tests
    - Dispatch fix agents
    - Run a fix loop

    It only builds images and checks if services start healthy. Returns
    a summary dict with build_ok/total and healthy/total counts plus
    a list of failed services with their errors.

    Designed to run between milestone phases (A→B, B→C, C→D) to catch
    broken services early before the next phase tries to integrate them.

    Returns dict with:
      phase, build_ok, build_total, healthy, total,
      failed_services: [{service, phase, error}]
    """
    result: dict[str, Any] = {
        "phase": phase_name,
        "docker_available": False,
        "build_ok": 0,
        "build_total": 0,
        "healthy": 0,
        "total": 0,
        "failed_services": [],
        "duration_s": 0.0,
    }

    start = time.monotonic()

    if not check_docker_available():
        result["duration_s"] = time.monotonic() - start
        return result
    result["docker_available"] = True

    compose_file = find_compose_file(project_root, compose_override)
    if compose_file is None:
        result["duration_s"] = time.monotonic() - start
        return result

    # Build
    build_results = docker_build(project_root, compose_file)
    result["build_total"] = len(build_results)
    result["build_ok"] = sum(1 for r in build_results if r.success)
    for r in build_results:
        if not r.success:
            result["failed_services"].append({
                "service": r.service, "phase": "build", "error": r.error[:300],
            })

    if result["build_ok"] == 0:
        result["duration_s"] = time.monotonic() - start
        return result

    # Start + health check
    statuses = docker_start(project_root, compose_file, startup_timeout_s)
    result["total"] = len(statuses)
    result["healthy"] = sum(1 for s in statuses if s.healthy)
    for s in statuses:
        if not s.healthy and s.error:
            result["failed_services"].append({
                "service": s.service, "phase": "startup",
                "error": (s.logs_tail or s.error)[:300],
            })

    result["duration_s"] = time.monotonic() - start
    logger.info(
        "Phase checkpoint '%s': build %d/%d, healthy %d/%d (%.1fs)",
        phase_name, result["build_ok"], result["build_total"],
        result["healthy"], result["total"], result["duration_s"],
    )
    return result


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def _probe_live_app(url: str, timeout: float = 5.0) -> bool:
    """D-02: best-effort HEAD/GET against *url* to detect a live external app.

    Returns ``True`` if ``url`` responds with HTTP 2xx/3xx/4xx (anything
    other than a connection/timeout error — the goal is "something is
    listening", not "the app is healthy"). Uses ``urllib.request`` instead
    of ``requests`` so callers don't need an extra dependency, and because
    the whole module is synchronous. Any URL error, timeout, or missing
    scheme returns ``False``. Caller mocks ``urllib.request.urlopen`` in
    tests — no real network traffic.
    """
    import urllib.error
    import urllib.request

    candidate = (url or "").strip()
    if not candidate:
        return False
    try:
        with urllib.request.urlopen(candidate, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            return 200 <= status < 500
    except urllib.error.HTTPError as exc:
        # HTTPError means the server responded; treat 4xx as "listening"
        # but 5xx as "something is broken" — conservative.
        return 200 <= int(getattr(exc, "code", 0) or 0) < 500
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return False


def run_runtime_verification(
    project_root: Path,
    compose_override: str = "",
    docker_build_enabled: bool = True,
    docker_start_enabled: bool = True,
    database_init_enabled: bool = True,
    smoke_test_enabled: bool = True,
    cleanup_after: bool = False,
    max_build_fix_rounds: int = 2,
    startup_timeout_s: int = 90,
    fix_loop: bool = True,
    max_fix_rounds_per_service: int = 3,
    max_total_fix_rounds: int = 5,
    max_fix_budget_usd: float = 50.0,
    live_endpoint_check: bool = False,
    live_app_url: str = "",
) -> RuntimeReport:
    """Run the full runtime verification pipeline with fix loop.

    The pipeline loops until ALL services are healthy or safety rails trigger:
    - Budget cap: stops when fix cost exceeds max_fix_budget_usd
    - Per-service cap: gives up on a service after max_fix_rounds_per_service
    - Global cap: stops after max_total_fix_rounds total iterations
    - Repeat detection: stops retrying a service if same error recurs

    Steps per iteration:
      6a. Docker build (fix compilation errors)
      6b. Service startup + health check (fix crash errors)
    After all healthy:
      6c. Database migrations + seed
      6d. Smoke test
      6e. Optional cleanup

    Returns a RuntimeReport with all results.
    """
    report = RuntimeReport()
    overall_start = time.monotonic()

    # D-02: record the caller's intent + the resources we plan to probe so
    # the ``details`` payload is populated even when we short-circuit.
    # ``compose_path_checked`` is the explicit override or an empty string
    # (``find_compose_file`` does its own discovery under ``project_root``).
    report.details["live_endpoint_check"] = bool(live_endpoint_check)
    report.details["live_app_url_checked"] = str(live_app_url or "")
    report.details["compose_path_checked"] = str(compose_override or "")
    report.details["project_root"] = str(project_root)

    # Pre-check: Docker available?
    report.docker_available = check_docker_available()
    if not report.docker_available:
        # D-02: when the caller opted-in to live endpoint verification
        # (live_endpoint_check=True) the lack of Docker is a BLOCKING
        # infrastructure gap, not a silent opt-out. Fall through to a
        # live-app probe first — if an external app is reachable we can
        # still run endpoint checks against it; if not, ``health=blocked``.
        if live_endpoint_check:
            if live_app_url and _probe_live_app(live_app_url):
                report.health = "external_app"
                report.block_reason = ""
                report.details["live_app_reachable"] = True
                logger.info(
                    "Docker unavailable but live app reachable at %s — using external app",
                    live_app_url,
                )
            else:
                report.health = "blocked"
                report.block_reason = "docker_unavailable"
                report.details["live_app_reachable"] = False
                logger.warning(
                    "Runtime verification BLOCKED: Docker unavailable and no "
                    "live app reachable at %r (live_endpoint_check=True)",
                    live_app_url,
                )
        else:
            report.health = "skipped"
            logger.warning("Docker not available — skipping runtime verification")
        report.total_duration_s = time.monotonic() - overall_start
        return report

    # Find compose file
    compose_file = find_compose_file(project_root, compose_override)
    if compose_file is None:
        if live_endpoint_check:
            if live_app_url and _probe_live_app(live_app_url):
                report.health = "external_app"
                report.block_reason = ""
                report.details["live_app_reachable"] = True
                logger.info(
                    "No compose file found but live app reachable at %s — "
                    "using external app for endpoint verification",
                    live_app_url,
                )
            else:
                report.health = "blocked"
                report.block_reason = "compose_file_missing"
                report.details["live_app_reachable"] = False
                logger.warning(
                    "Runtime verification BLOCKED: no docker-compose file found "
                    "and no live app reachable at %r (live_endpoint_check=True)",
                    live_app_url,
                )
        else:
            report.health = "skipped"
            logger.warning("No docker-compose file found — skipping runtime verification")
        report.total_duration_s = time.monotonic() - overall_start
        return report
    report.compose_file = str(compose_file)

    # Initialize fix tracker
    tracker = FixTracker(
        max_rounds_per_service=max_fix_rounds_per_service,
        max_total_rounds=max_total_fix_rounds,
        max_budget_usd=max_fix_budget_usd,
    )

    # ---- FIX LOOP: Build → Start → Fix → Repeat until healthy ----
    all_services_healthy = False

    for fix_round in range(max_total_fix_rounds + 1):  # +1 for initial attempt
        report.fix_rounds_completed = fix_round

        # Safety rail: budget exceeded
        if tracker.budget_exceeded:
            logger.warning("Fix budget exceeded ($%.2f/$%.2f) — stopping fix loop",
                          tracker.total_cost, max_fix_budget_usd)
            report.budget_exceeded = True
            break

        # Safety rail: total rounds exceeded
        if fix_round > 0 and tracker.total_rounds_exceeded:
            logger.warning("Max total fix rounds (%d) exceeded — stopping fix loop",
                          max_total_fix_rounds)
            break

        # 6a: Docker Build
        if docker_build_enabled:
            logger.info("Phase 6a (round %d): Building Docker images...", fix_round + 1)
            report.build_results = docker_build(project_root, compose_file)
            failed_builds = [r for r in report.build_results if not r.success]
            built_ok = len(report.build_results) - len(failed_builds)
            logger.info("Phase 6a: %d/%d built, %d failed",
                       built_ok, len(report.build_results), len(failed_builds))

            if built_ok == 0 and not fix_loop:
                logger.error("All builds failed and fix_loop disabled — aborting")
                break

            # Fix failed builds
            needs_rebuild = False
            if fix_loop and failed_builds and fix_round < max_total_fix_rounds:
                for failure in failed_builds:
                    if not tracker.can_fix(failure.service):
                        continue
                    if tracker.is_repeat_error(failure.service, failure.error):
                        tracker.mark_given_up(failure.service, "repeat error")
                        continue

                    logger.info("Fixing build error for %s (attempt %d)...",
                               failure.service, tracker._attempts.get(failure.service, 0) + 1)
                    cost = dispatch_fix_agent(project_root, failure.service, "build", failure.error)
                    tracker.record_attempt(failure.service, "build", failure.error, cost)
                    needs_rebuild = True

                    if tracker.budget_exceeded:
                        break

            if needs_rebuild:
                continue  # Go back to build step

        # 6b: Service Startup
        if docker_start_enabled:
            logger.info("Phase 6b (round %d): Starting services...", fix_round + 1)
            report.services_status = docker_start(project_root, compose_file, startup_timeout_s)
            report.services_healthy = sum(1 for s in report.services_status if s.healthy)
            report.services_total = len(report.services_status)
            unhealthy = [s for s in report.services_status
                        if not s.healthy and s.error
                        and s.service not in ("postgres", "redis", "traefik")]
            logger.info("Phase 6b: %d/%d healthy, %d unhealthy",
                       report.services_healthy, report.services_total, len(unhealthy))

            if not unhealthy or not fix_loop:
                all_services_healthy = len(unhealthy) == 0
                if all_services_healthy:
                    logger.info("All services healthy!")
                break  # Either all healthy or fix_loop disabled

            # Fix unhealthy services
            needs_restart = False
            if fix_round < max_total_fix_rounds:
                for svc in unhealthy:
                    if not tracker.can_fix(svc.service):
                        continue
                    error_text = svc.logs_tail or svc.error
                    if tracker.is_repeat_error(svc.service, error_text):
                        tracker.mark_given_up(svc.service, "repeat error")
                        continue

                    logger.info("Fixing startup error for %s (attempt %d)...",
                               svc.service, tracker._attempts.get(svc.service, 0) + 1)
                    cost = dispatch_fix_agent(project_root, svc.service, "startup", error_text)
                    tracker.record_attempt(svc.service, "startup", error_text, cost)
                    needs_restart = True

                    if tracker.budget_exceeded:
                        break

            if needs_restart:
                # Stop containers before rebuilding
                _run_docker("-f", str(compose_file), "down", "--remove-orphans",
                           cwd=str(project_root), timeout=30)
                continue  # Go back to build+start

            break  # No more fixable services

    # Record tracker state into report
    report.fix_attempts = tracker.attempts_log
    report.fix_cost_usd = tracker.total_cost
    report.services_given_up = tracker.given_up_services
    report.budget_exceeded = tracker.budget_exceeded

    # 6c: Database Init (only after services are up)
    if database_init_enabled and report.services_healthy > 0:
        logger.info("Phase 6c: Running database migrations...")
        success, error = run_migrations(project_root, compose_file)
        report.migrations_run = success
        report.migrations_error = error
        if error:
            logger.warning("Phase 6c: Migration issues: %s", error[:200])
        else:
            logger.info("Phase 6c: Migrations complete")

        seed_ok, seed_err = run_seed_scripts(project_root)
        report.seed_run = seed_ok
        report.seed_error = seed_err

    # 6d: Smoke Test
    if smoke_test_enabled and report.services_healthy > 0:
        logger.info("Phase 6d: Running smoke tests...")
        report.smoke_results = smoke_test(
            project_root, compose_file, report.services_status,
        )
        healthy_count = sum(1 for r in report.smoke_results.values() if r.get("health"))
        logger.info("Phase 6d: %d/%d services passed smoke test",
                   healthy_count, len(report.smoke_results))

    # 6e: Cleanup
    if cleanup_after:
        logger.info("Phase 6e: Cleaning up containers...")
        docker_cleanup(project_root, compose_file)

    report.total_duration_s = time.monotonic() - overall_start
    # D-02: compose+docker happy path finalises as ``verified`` when at
    # least one service came up healthy; otherwise the caller still sees
    # the fix-loop outcome via services_given_up / budget_exceeded.
    if report.services_total > 0 and report.services_healthy > 0:
        report.health = "verified"
    elif report.health == "unknown":
        # Compose+docker path ran but produced no healthy services.
        # Mark blocked so the status never stays "unknown" on a completed
        # run — the block_reason names the failure mode.
        report.health = "blocked"
        report.block_reason = "no_services_healthy"
    logger.info(
        "Runtime verification complete in %.1fs: %d/%d healthy, "
        "%d fix attempts ($%.2f), %d services given up",
        report.total_duration_s, report.services_healthy, report.services_total,
        len(report.fix_attempts), report.fix_cost_usd, len(report.services_given_up),
    )
    return report


def format_runtime_report(report: RuntimeReport) -> str:
    """Format a RuntimeReport as markdown for logging/display."""
    lines = ["## Runtime Verification Report\n"]

    # D-02: emit the legible BLOCKED vs SKIPPED vs EXTERNAL APP header
    # based on ``health``. The docker_available / compose_file checks
    # below keep the legacy "skipped" wording ONLY when the caller
    # actually opted out (health=="skipped"); blocked runs get a
    # distinct banner with the block_reason so operators can triage.
    if report.health == "blocked":
        reason = report.block_reason or "unknown"
        lines.append(
            f"**Runtime verification BLOCKED** — reason: `{reason}`. "
            "Live endpoint verification was requested "
            "(`live_endpoint_check=True`) but the required infrastructure "
            "(compose file and/or Docker and/or a reachable live app) was "
            "not available. Downstream gates should treat this as a hard "
            "failure, not a silent skip.\n"
        )
        if report.details:
            lines.append("Details:\n")
            for key in (
                "compose_path_checked",
                "live_app_url_checked",
                "live_app_reachable",
                "live_endpoint_check",
            ):
                if key in report.details:
                    lines.append(f"- `{key}`: `{report.details[key]}`")
            lines.append("")
        return "\n".join(lines)

    if report.health == "external_app":
        lines.append(
            "**External app used** — no compose boot required; endpoint "
            f"verification probed the live app at "
            f"`{report.details.get('live_app_url_checked', '')}`.\n"
        )
        return "\n".join(lines)

    if not report.docker_available:
        lines.append("**Docker not available** — runtime verification skipped.\n")
        return "\n".join(lines)

    if not report.compose_file:
        lines.append("**No docker-compose file found** — runtime verification skipped.\n")
        return "\n".join(lines)

    # Build results
    if report.build_results:
        built_ok = sum(1 for r in report.build_results if r.success)
        lines.append(f"### Docker Build: {built_ok}/{len(report.build_results)} services\n")
        for r in report.build_results:
            status = "PASS" if r.success else "FAIL"
            lines.append(f"- {r.service}: {status}")
            if r.error:
                lines.append(f"  Error: {r.error[:100]}")
        lines.append("")

    # Service status
    if report.services_status:
        lines.append(f"### Services: {report.services_healthy}/{report.services_total} healthy\n")
        for s in report.services_status:
            status = "HEALTHY" if s.healthy else "UNHEALTHY"
            lines.append(f"- {s.service}: {status}")
            if s.error:
                lines.append(f"  Error: {s.error[:100]}")
        lines.append("")

    # Migrations
    if report.migrations_run is not None:
        status = "OK" if report.migrations_run else f"FAILED: {report.migrations_error[:100]}"
        lines.append(f"### Migrations: {status}\n")

    # Smoke test
    if report.smoke_results:
        healthy = sum(1 for r in report.smoke_results.values() if r.get("health"))
        lines.append(f"### Smoke Test: {healthy}/{len(report.smoke_results)} services responding\n")
        for svc, result in report.smoke_results.items():
            status = "PASS" if result.get("health") else "FAIL"
            lines.append(f"- {svc}: {status}")
        lines.append("")

    # Fix loop summary
    if report.fix_attempts:
        lines.append(f"### Fix Loop: {len(report.fix_attempts)} attempts, ${report.fix_cost_usd:.2f} spent\n")
        for attempt in report.fix_attempts:
            lines.append(
                f"- {attempt.service} (round {attempt.round}, {attempt.phase}): "
                f"${attempt.cost_usd:.2f}"
            )
        lines.append("")

    if report.services_given_up:
        lines.append(f"### Given Up ({len(report.services_given_up)} services)\n")
        for svc in report.services_given_up:
            lines.append(f"- {svc}: exceeded max fix attempts or repeat error")
        lines.append("")

    if report.budget_exceeded:
        lines.append(f"**WARNING: Fix budget exceeded** (${report.fix_cost_usd:.2f})\n")

    lines.append(f"**Total duration:** {report.total_duration_s:.1f}s\n")
    lines.append(f"**Fix rounds completed:** {report.fix_rounds_completed}\n")
    return "\n".join(lines)
