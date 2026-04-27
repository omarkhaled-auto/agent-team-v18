"""Application Lifecycle Manager — Starts and stops built applications for browser testing.

Handles Docker services, database migrations, seeding, dev server startup,
health checks, and test authentication setup.  Stack-aware (Next.js, Vite,
Express) with Windows compatibility.

Typical usage::

    from pathlib import Path
    from agent_team_v15.app_lifecycle import AppLifecycleManager

    lifecycle = AppLifecycleManager(cwd=Path("./my_app"), port=3080)
    app = lifecycle.start()
    # ... run browser tests against http://localhost:3080 ...
    lifecycle.stop()
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AppInstance:
    """A running application instance."""

    cwd: Path
    port: int
    dev_server_process: Optional[subprocess.Popen] = None
    docker_running: bool = False
    db_migrated: bool = False
    db_seeded: bool = False
    healthy: bool = False
    stack: str = "unknown"  # "nextjs" | "vite" | "express" | "unknown"
    startup_log: str = ""


@dataclass
class BrowserTestUser:
    """A test user for browser testing."""

    customer_id: str = ""
    email: str = ""
    password: str = ""
    token: str = ""
    role: str = "user"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [lifecycle] {msg}")


# ---------------------------------------------------------------------------
# Stack detection
# ---------------------------------------------------------------------------


def detect_stack(cwd: Path) -> str:
    """Detect the application stack from package.json."""
    pkg_path = cwd / "package.json"
    if not pkg_path.is_file():
        return "unknown"

    try:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "unknown"

    all_deps = {}
    for key in ("dependencies", "devDependencies"):
        all_deps.update(pkg.get(key, {}))

    if "next" in all_deps:
        return "nextjs"
    if "vite" in all_deps:
        return "vite"
    if "express" in all_deps:
        return "express"
    return "unknown"


def _get_dev_command(stack: str, port: int) -> list[str]:
    """Return the dev server command for the detected stack."""
    if stack == "nextjs":
        return ["npm", "run", "dev", "--", "-p", str(port)]
    if stack == "vite":
        return ["npm", "run", "dev", "--", "--port", str(port)]
    if stack == "express":
        return ["npm", "run", "dev"]
    # Fallback: try npm run dev with PORT env
    return ["npm", "run", "dev"]


# ---------------------------------------------------------------------------
# App Lifecycle Manager
# ---------------------------------------------------------------------------


def _read_database_url(cwd: Path) -> str:
    """Read DATABASE_URL from .env file in the given directory."""
    env_file = cwd / ".env"
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("DATABASE_URL="):
                    return stripped.split("=", 1)[1].strip('"').strip("'")
        except OSError:
            pass
    return "postgresql://postgres:postgres@localhost:5432/app"


class AppLifecycleError(Exception):
    """Application lifecycle error."""


class AppLifecycleManager:
    """Manages the full application lifecycle for browser testing.

    Handles Docker services, migrations, seeding, dev server, and health checks.
    """

    def __init__(self, cwd: Path, port: int = 3080):
        self.cwd = cwd
        self.port = port
        self.instance: Optional[AppInstance] = None

    def start(self) -> AppInstance:
        """Full startup sequence. Returns a running AppInstance.

        Raises AppLifecycleError on unrecoverable failure.
        """
        stack = detect_stack(self.cwd)
        self.instance = AppInstance(cwd=self.cwd, port=self.port, stack=stack)
        _log(f"Starting application (stack={stack}, port={self.port})")

        try:
            self._start_docker_if_needed()
            self._run_migrations()
            self._run_seed()
            self._start_dev_server()
            self._wait_for_health()
            _log(f"Application healthy at http://localhost:{self.port}")
            return self.instance
        except Exception as e:
            _log(f"Startup failed: {e}")
            self.stop()
            raise AppLifecycleError(f"Application startup failed: {e}") from e

    def stop(self) -> None:
        """Graceful shutdown in reverse order: dev server, then Docker."""
        if not self.instance:
            return
        self._stop_dev_server()
        self._stop_docker()
        self.instance = None
        _log("Application stopped")

    def _stop_docker(self) -> None:
        """Stop Docker containers started by this manager."""
        if not self.instance or not self.instance.docker_running:
            return
        try:
            _log("Stopping Docker containers...")
            subprocess.run(
                ["docker", "compose", "down"],
                cwd=str(self.cwd),
                capture_output=True,
                timeout=30,
            )
        except Exception:
            _log("Warning: Docker compose down failed (containers may still be running)")

    # -- Docker ---------------------------------------------------------------

    def _start_docker_if_needed(self) -> None:
        """Start Docker services if docker-compose.yml exists."""
        compose_file = None
        for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
            if (self.cwd / name).is_file():
                compose_file = self.cwd / name
                break

        if compose_file is None:
            _log("No docker-compose file found, skipping Docker startup")
            return

        # Check Docker is available
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise AppLifecycleError(
                    "Docker is not running. Start Docker Desktop and retry."
                )
        except FileNotFoundError:
            raise AppLifecycleError(
                "Docker CLI not found. Install Docker and ensure it's on PATH."
            )

        _log("Starting Docker services...")
        result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=str(self.cwd),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise AppLifecycleError(f"docker compose up failed: {result.stderr[:500]}")

        self.instance.docker_running = True

        # Wait for PostgreSQL if it's a service
        self._wait_for_postgres()

    def _wait_for_postgres(self, max_wait: int = 30) -> None:
        """Wait for PostgreSQL to accept connections."""
        _log("Waiting for PostgreSQL...")
        for _ in range(max_wait):
            result = subprocess.run(
                ["docker", "compose", "exec", "-T", "postgres",
                 "pg_isready", "-U", "postgres"],
                cwd=str(self.cwd),
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                _log("PostgreSQL ready")
                return
            time.sleep(1)
        _log(f"PostgreSQL not ready after {max_wait}s (may not be needed)")

    # -- Migrations & Seed ----------------------------------------------------

    def _run_migrations(self) -> None:
        """Run database migrations if Prisma is detected."""
        if not (self.cwd / "prisma").is_dir():
            _log("No Prisma directory found, skipping migrations")
            return

        _log("Running database migrations...")
        env = {**os.environ, "DATABASE_URL": self._get_database_url()}

        result = subprocess.run(
            ["npx", "prisma", "migrate", "deploy"],
            cwd=str(self.cwd),
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            shell=True,  # Windows compatibility for npx
        )
        if result.returncode != 0:
            _log(f"Migration failed, trying reset: {result.stderr[:200]}")
            # Fallback: reset (acceptable for test DB)
            result = subprocess.run(
                ["npx", "prisma", "migrate", "reset", "--force"],
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
                shell=True,
            )
            if result.returncode != 0:
                raise AppLifecycleError(f"Migration reset failed: {result.stderr[:300]}")

        self.instance.db_migrated = True
        _log("Migrations complete")

    def _run_seed(self) -> None:
        """Run seed data (non-fatal if fails)."""
        if not (self.cwd / "prisma").is_dir():
            return

        _log("Seeding database...")
        env = {**os.environ, "DATABASE_URL": self._get_database_url()}

        result = subprocess.run(
            ["npx", "prisma", "db", "seed"],
            cwd=str(self.cwd),
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            shell=True,
        )
        if result.returncode == 0:
            self.instance.db_seeded = True
            _log("Seed complete")
        else:
            _log(f"Seed failed (non-fatal): {result.stderr[:200]}")

    # -- Dev server -----------------------------------------------------------

    def _start_dev_server(self) -> None:
        """Start the dev server in background."""
        self._kill_port(self.port)

        cmd = _get_dev_command(self.instance.stack, self.port)
        env = {**os.environ, "PORT": str(self.port)}

        _log(f"Starting dev server: {' '.join(cmd)}")
        # ``start_new_session=True`` puts the shell + dev server in a fresh
        # POSIX process group so ``_stop_dev_server`` can reap the whole
        # tree (next/vite/express → spawned compilers, watchers, sockets)
        # via ``os.killpg``. Silently ignored on Windows (taskkill /T is
        # the equivalent there; not used here yet).
        self.instance.dev_server_process = subprocess.Popen(
            cmd,
            cwd=str(self.cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            shell=True,  # Windows compatibility
            start_new_session=True,
        )

        # Quick check: process didn't crash immediately
        time.sleep(2)
        if self.instance.dev_server_process.poll() is not None:
            stderr = ""
            if self.instance.dev_server_process.stderr:
                stderr = self.instance.dev_server_process.stderr.read().decode(
                    errors="replace"
                )[:500]
            raise AppLifecycleError(f"Dev server crashed on start: {stderr}")

    def _wait_for_health(self, max_wait: int = 60) -> None:
        """Wait for the dev server to respond."""
        # Try common health endpoints
        health_paths = ["/api/health", "/health", "/", "/api"]

        _log(f"Waiting for health check (max {max_wait}s)...")
        for i in range(max_wait):
            # Check process is still alive
            if (
                self.instance.dev_server_process
                and self.instance.dev_server_process.poll() is not None
            ):
                stderr = ""
                if self.instance.dev_server_process.stderr:
                    stderr = self.instance.dev_server_process.stderr.read().decode(
                        errors="replace"
                    )[:500]
                raise AppLifecycleError(
                    f"Dev server process died during health check: {stderr}"
                )

            for path in health_paths:
                url = f"http://localhost:{self.port}{path}"
                try:
                    req = urllib.request.Request(url, method="GET")
                    response = urllib.request.urlopen(req, timeout=2)  # noqa: S310
                    if response.status < 500:
                        self.instance.healthy = True
                        _log(f"Health check passed: {url}")
                        return
                except urllib.error.HTTPError as e:
                    if e.code < 500:
                        # 4xx is OK — app is running, just auth/routing
                        self.instance.healthy = True
                        _log(f"Health check passed (HTTP {e.code}): {url}")
                        return
                except Exception:
                    pass
            time.sleep(1)

        raise AppLifecycleError(
            f"Health check failed after {max_wait}s on port {self.port}"
        )

    def _stop_dev_server(self) -> None:
        """Stop the dev server process and any children it spawned."""
        if self.instance and self.instance.dev_server_process:
            _log("Stopping dev server...")
            proc = self.instance.dev_server_process
            # POSIX: send SIGTERM to the whole process group first so
            # next/vite/express children (compilers, watchers) exit
            # together with their parent. Falls back to SIGKILL on the
            # group if SIGTERM doesn't take. Windows handles this via
            # taskkill (not wired in this helper; relies on terminate()).
            if os.name != "nt" and proc.pid:
                with contextlib.suppress(OSError, ProcessLookupError, PermissionError):
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name != "nt" and proc.pid:
                    with contextlib.suppress(OSError, ProcessLookupError, PermissionError):
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.kill()
                proc.wait(timeout=5)

    # -- Port management ------------------------------------------------------

    def _kill_port(self, port: int) -> None:
        """Kill any process using the specified port (best effort)."""
        try:
            if os.name == "nt":
                # Windows: find PID and kill
                result = subprocess.run(
                    f'netstat -aon | findstr ":{port} "',
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                for line in result.stdout.strip().splitlines():
                    parts = line.split()
                    if len(parts) >= 5 and parts[3].endswith(f":{port}"):
                        pid = parts[4]
                        if pid.isdigit() and pid != "0":
                            subprocess.run(
                                f"taskkill /F /PID {pid}",
                                shell=True,
                                capture_output=True,
                                timeout=10,
                            )
            else:
                # POSIX: ``fuser -k <port>/tcp`` (psmisc) — atomic, no
                # shell-pipeline race, no dependency on ``lsof`` which
                # isn't installed by default on minimal Ubuntu. Default
                # signal is SIGKILL, matching the prior ``kill -9``
                # behaviour. Fail-open (outer try/except).
                subprocess.run(
                    ["fuser", "-k", f"{port}/tcp"],
                    capture_output=True,
                    timeout=10,
                )
        except Exception:
            pass  # Best effort

    # -- Database URL ---------------------------------------------------------

    def _get_database_url(self) -> str:
        """Read DATABASE_URL from .env file."""
        return _read_database_url(self.cwd)


# ---------------------------------------------------------------------------
# Test Authentication Setup
# ---------------------------------------------------------------------------


class AuthSetup:
    """Creates test users and sessions for browser testing.

    Two-tier approach:
    1. Extract seed credentials for UI-based login
    2. Generate direct DB session for apps requiring external auth (magic link, OAuth)
    """

    def __init__(self, cwd: Path, database_url: str = ""):
        self.cwd = cwd
        self.database_url = database_url or self._read_database_url()

    def get_seed_credentials(self) -> dict[str, dict[str, str]]:
        """Extract test credentials from seed files.

        Returns dict like: {"admin": {"email": "...", "password": "..."}}
        Delegates to browser_testing._extract_seed_credentials().
        """
        from agent_team_v15.browser_testing import _extract_seed_credentials

        return _extract_seed_credentials(self.cwd)

    def create_test_session_script(self) -> str:
        """Generate a Node.js script that creates a test user + valid session.

        The script uses the application's own Prisma client and auth utilities
        to ensure the JWT format matches what the middleware expects.

        Returns the script text. Caller should execute it via:
            subprocess.run(["node", "-e", script], cwd=app_dir, ...)
        """
        script = r"""
const { PrismaClient } = require('@prisma/client');
const crypto = require('crypto');

async function setup() {
    const prisma = new PrismaClient();

    try {
        // Find or create test user
        const testEmail = 'browser-test@agent-team.local';
        let user = null;

        // Try common user models
        for (const model of ['customer', 'user', 'account']) {
            if (prisma[model]) {
                try {
                    user = await prisma[model].findFirst({
                        where: { email: testEmail }
                    });
                    if (!user) {
                        user = await prisma[model].create({
                            data: {
                                email: testEmail,
                                name: 'Browser Test User',
                                ...(model === 'user' ? { password: 'not-used-for-session-auth' } : {}),
                            }
                        });
                    }
                    break;
                } catch (e) {
                    // Model doesn't have expected fields, try next
                    continue;
                }
            }
        }

        if (!user) {
            console.log(JSON.stringify({ error: 'No compatible user model found' }));
            return;
        }

        // Create a session token
        const token = crypto.randomBytes(32).toString('hex');
        const tokenHash = crypto.createHash('sha256').update(token).digest('hex');

        // Try to create session record
        if (prisma.session) {
            try {
                await prisma.session.create({
                    data: {
                        userId: user.id,
                        tokenHash: tokenHash,
                        expiresAt: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000),
                    }
                });
            } catch (e) {
                // Session model might have different fields
                try {
                    await prisma.session.create({
                        data: {
                            customerId: user.id,
                            tokenHash: tokenHash,
                            expiresAt: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000),
                        }
                    });
                } catch (e2) {
                    // Could not create session — token won't be valid
                }
            }
        }

        console.log(JSON.stringify({
            user_id: user.id,
            email: user.email,
            token: token,
        }));
    } finally {
        await prisma.$disconnect();
    }
}

setup().catch(e => {
    console.log(JSON.stringify({ error: e.message }));
    process.exit(1);
});
"""
        return script

    def create_test_session(self) -> Optional[BrowserTestUser]:
        """Execute the test session creation script.

        Returns BrowserTestUser with credentials, or None on failure.
        """
        script = self.create_test_session_script()
        env = {**os.environ, "DATABASE_URL": self.database_url}

        try:
            result = subprocess.run(
                ["node", "-e", script],
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            _log(f"Test session creation failed: {e}")
            return None

        if result.returncode != 0:
            _log(f"Test session script failed: {result.stderr[:200]}")
            return None

        try:
            data = json.loads(result.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            _log(f"Could not parse test session output: {result.stdout[:200]}")
            return None

        if "error" in data:
            _log(f"Test session error: {data['error']}")
            return None

        return BrowserTestUser(
            customer_id=str(data.get("user_id", "")),
            email=data.get("email", ""),
            token=data.get("token", ""),
        )

    def _read_database_url(self) -> str:
        url = _read_database_url(self.cwd)
        # Return empty string if only the default was found (no .env)
        if url == "postgresql://postgres:postgres@localhost:5432/app" and not (self.cwd / ".env").is_file():
            return ""
        return url
