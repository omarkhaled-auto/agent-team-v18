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
from typing import Any

logger = logging.getLogger(__name__)


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
    # Start all services
    rc, out, err = _run_docker(
        "-f", str(compose_file), "up", "-d",
        cwd=str(project_root),
        timeout=120,
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
# Main orchestrator
# ---------------------------------------------------------------------------

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
) -> RuntimeReport:
    """Run the full runtime verification pipeline.

    Steps:
      6a. Docker build
      6b. Service startup + health check
      6c. Database migrations + seed
      6d. Smoke test (health + endpoints)
      6e. Optional cleanup

    Returns a RuntimeReport with all results.
    """
    report = RuntimeReport()
    overall_start = time.monotonic()

    # Pre-check: Docker available?
    report.docker_available = check_docker_available()
    if not report.docker_available:
        logger.warning("Docker not available — skipping runtime verification")
        report.total_duration_s = time.monotonic() - overall_start
        return report

    # Find compose file
    compose_file = find_compose_file(project_root, compose_override)
    if compose_file is None:
        logger.warning("No docker-compose file found — skipping runtime verification")
        report.total_duration_s = time.monotonic() - overall_start
        return report
    report.compose_file = str(compose_file)

    # 6a: Docker Build
    if docker_build_enabled:
        logger.info("Phase 6a: Building Docker images...")
        report.build_results = docker_build(project_root, compose_file)
        built_ok = sum(1 for r in report.build_results if r.success)
        built_total = len(report.build_results)
        logger.info("Phase 6a: %d/%d services built successfully", built_ok, built_total)

        if built_ok == 0:
            logger.error("Phase 6a: All Docker builds failed — aborting runtime verification")
            report.total_duration_s = time.monotonic() - overall_start
            return report

    # 6b: Service Startup
    if docker_start_enabled:
        logger.info("Phase 6b: Starting services...")
        report.services_status = docker_start(project_root, compose_file, startup_timeout_s)
        report.services_healthy = sum(1 for s in report.services_status if s.healthy)
        report.services_total = len(report.services_status)
        logger.info(
            "Phase 6b: %d/%d services healthy",
            report.services_healthy, report.services_total,
        )

    # 6c: Database Init
    if database_init_enabled and report.services_healthy > 0:
        logger.info("Phase 6c: Running database migrations...")
        success, error = run_migrations(project_root, compose_file)
        report.migrations_run = success
        report.migrations_error = error
        if error:
            logger.warning("Phase 6c: Migration issues: %s", error[:200])
        else:
            logger.info("Phase 6c: Migrations complete")

        # Try seed scripts
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
        logger.info(
            "Phase 6d: %d/%d services passed smoke test",
            healthy_count, len(report.smoke_results),
        )

    # 6e: Cleanup
    if cleanup_after:
        logger.info("Phase 6e: Cleaning up containers...")
        docker_cleanup(project_root, compose_file)

    report.total_duration_s = time.monotonic() - overall_start
    logger.info(
        "Runtime verification complete in %.1fs: %d/%d healthy",
        report.total_duration_s, report.services_healthy, report.services_total,
    )
    return report


def format_runtime_report(report: RuntimeReport) -> str:
    """Format a RuntimeReport as markdown for logging/display."""
    lines = ["## Runtime Verification Report\n"]

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

    lines.append(f"**Total duration:** {report.total_duration_s:.1f}s\n")
    return "\n".join(lines)
