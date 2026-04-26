"""M1 startup-AC probe (D-20).

M1 (the infrastructure / platform-foundation milestone) has a handful of
startup acceptance criteria that only the build itself can prove:

  1. The detected package-manager install exits 0 at the workspace root.
  2. ``docker compose up -d postgres`` brings the database online.
  3. ``prisma migrate dev --name init`` applies the initial schema.
  4. ``test:api`` runs (zero tests is acceptable).
  5. ``test:web`` runs (zero tests is acceptable).

The audit phase previously reasoned about files but never executed these
commands, so build-j's M1 REQUIREMENTS.md ended up with two ACs marked
``UNKNOWN (not tested in audit)``. This module executes the five probes
in order, captures structured results, and always tears down the
compose stack afterwards — even if one of the earlier probes fails.

The probe module is *only called from the audit phase for
infrastructure milestones*; unit tests mock ``subprocess.run`` via the
``_run`` seam and NEVER invoke real commands. The real subprocess path
runs at pipeline runtime and is covered by Session 6's Gate A smoke.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


# Tail size for captured stdout/stderr (full output can be megabytes
# for package-manager installs; telemetry only needs the last ~1 KB).
_TAIL_CHARS = 1000


def _tail(blob: bytes | str | None) -> str:
    """Return the last ``_TAIL_CHARS`` characters of a bytes/str payload.

    ``subprocess.run`` may produce ``bytes`` (default) or ``str`` (when
    ``text=True``) output. We keep the call ``text=False`` so the caller
    can't be surprised by encoding issues — this helper always returns
    a string with a bounded size.
    """
    if blob is None:
        return ""
    if isinstance(blob, bytes):
        try:
            text = blob.decode("utf-8", errors="replace")
        except Exception:
            text = repr(blob)
    else:
        text = str(blob)
    return text[-_TAIL_CHARS:]


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    timeout: float,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute ``cmd`` via ``subprocess.run`` and return a structured result.

    This is the single seam unit tests mock. Never invoke
    ``subprocess.run`` directly from :func:`run_m1_startup_probe` —
    funnel every probe through here so ``unittest.mock.patch`` of
    ``m1_startup_probe._run`` is sufficient to unit-test the module.

    Returns a dict with keys:
      * ``status``: ``"pass"``, ``"fail"``, ``"timeout"``, or ``"error"``.
      * ``exit_code``: int (``-1`` for timeout/error).
      * ``stdout_tail``: last ~1 KB of stdout.
      * ``stderr_tail``: last ~1 KB of stderr.
      * ``duration_s``: wall-clock seconds.
    """
    started = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "exit_code": -1,
            "stdout_tail": _tail(getattr(exc, "stdout", None)),
            "stderr_tail": _tail(getattr(exc, "stderr", None)),
            "duration_s": round(time.monotonic() - started, 2),
        }
    except (FileNotFoundError, OSError) as exc:
        return {
            "status": "error",
            "exit_code": -1,
            "stdout_tail": "",
            "stderr_tail": f"{type(exc).__name__}: {exc}",
            "duration_s": round(time.monotonic() - started, 2),
        }

    status = "pass" if result.returncode == 0 else "fail"
    return {
        "status": status,
        "exit_code": int(result.returncode),
        "stdout_tail": _tail(result.stdout),
        "stderr_tail": _tail(result.stderr),
        "duration_s": round(time.monotonic() - started, 2),
    }


def _compose_command() -> list[str]:
    """Return the docker-compose binary invocation to use.

    Prefers modern ``docker compose`` (plugin); falls back to legacy
    ``docker-compose`` when ``docker compose version`` is unavailable.
    Detection is best-effort: if neither exists, return the modern form
    so the downstream probe records an ``error`` result with a
    descriptive stderr tail.
    """
    # Modern: `docker compose`.
    try:
        modern_probe = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if modern_probe.returncode == 0:
            return ["docker", "compose"]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Legacy: `docker-compose`.
    try:
        legacy_probe = subprocess.run(
            ["docker-compose", "version"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if legacy_probe.returncode == 0:
            return ["docker-compose"]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Neither detected — caller will get a deterministic "error" status
    # with a descriptive stderr tail.
    return ["docker", "compose"]


def _detect_package_manager(workspace: Path) -> str:
    """Detect the Node package manager for the scaffolded workspace.

    M1 currently scaffolds a pnpm workspace. Falling back to npm for this probe
    gives false audit failures once the pipeline reaches runtime validation, so
    prefer explicit pnpm signals from package.json and workspace files.
    """
    package_json = workspace / "package.json"
    if package_json.is_file():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            package_manager = str(payload.get("packageManager", "") or "").lower()
            if package_manager.startswith("pnpm"):
                return "pnpm"
            if package_manager.startswith("npm"):
                return "npm"

    if (workspace / "pnpm-workspace.yaml").is_file() or (
        workspace / "pnpm-lock.yaml"
    ).is_file():
        return "pnpm"
    return "npm"


def _install_command(package_manager: str) -> list[str]:
    if package_manager == "pnpm":
        return ["pnpm", "install", "--frozen-lockfile"]
    return ["npm", "install"]


def _run_script_command(package_manager: str, script: str) -> list[str]:
    if package_manager == "pnpm":
        return ["pnpm", "run", script]
    return ["npm", "run", script]


def _prisma_migrate_command(package_manager: str) -> tuple[list[str], Path | None]:
    if package_manager == "pnpm":
        return (
            [
                "pnpm",
                "--filter",
                "api",
                "exec",
                "prisma",
                "migrate",
                "dev",
                "--name",
                "init",
            ],
            None,
        )
    return (
        ["npx", "prisma", "migrate", "dev", "--name", "init"],
        Path("apps/api"),
    )


def _skipped_by_dep(reason: str) -> dict[str, Any]:
    """Build a skip result for probes gated on an earlier failure."""
    return {
        "status": "skipped_by_dep",
        "exit_code": -1,
        "stdout_tail": "",
        "stderr_tail": reason,
        "duration_s": 0.0,
    }


def run_m1_startup_probe(workspace: Path) -> dict[str, dict[str, Any]]:
    """Execute M1's startup ACs in order against a scaffolded workspace.

    Called by the audit phase for infrastructure milestones only
    (``complexity_estimate.entity_count == 0 AND template == "full_stack"``).
    Each probe records structured telemetry; ``docker compose down``
    *always* runs in a finally block, even if an earlier probe raised.

    Parameters
    ----------
    workspace :
        The scaffolded project root (the directory containing
        ``package.json`` and ``docker-compose.yml``). For the prisma
        migration, we run in ``workspace / "apps" / "api"``.

    Returns
    -------
    dict[str, dict[str, Any]]
        One structured result per probe, keyed by:
        ``npm_install``, ``compose_up``, ``prisma_migrate``,
        ``test_api``, ``test_web``, ``compose_down``.
    """
    workspace = Path(workspace)
    results: dict[str, dict[str, Any]] = {}
    compose_bin = _compose_command()
    package_manager = _detect_package_manager(workspace)

    try:
        # 1. package manager install (workspace root)
        results["npm_install"] = _run(
            _install_command(package_manager), cwd=workspace, timeout=300,
        )

        # 2. docker compose up -d postgres
        results["compose_up"] = _run(
            [*compose_bin, "up", "-d", "postgres"],
            cwd=workspace,
            timeout=120,
        )

        # 3. npx prisma migrate dev --name init (apps/api)
        if results["compose_up"]["status"] != "pass":
            results["prisma_migrate"] = _skipped_by_dep(
                "skipped: compose_up did not reach pass"
            )
        else:
            prisma_cmd, prisma_cwd_rel = _prisma_migrate_command(package_manager)
            prisma_cwd = workspace / prisma_cwd_rel if prisma_cwd_rel else workspace
            env = os.environ.copy()
            # Fallback DATABASE_URL matches the docker-compose postgres
            # service defaults. A real run already has this env var set.
            env.setdefault(
                "DATABASE_URL",
                "postgresql://postgres:postgres@localhost:5432/app",
            )
            results["prisma_migrate"] = _run(
                prisma_cmd,
                cwd=prisma_cwd,
                timeout=180,
                env=env,
            )

        # 4. package manager run test:api
        results["test_api"] = _run(
            _run_script_command(package_manager, "test:api"),
            cwd=workspace,
            timeout=60,
        )

        # 5. package manager run test:web
        results["test_web"] = _run(
            _run_script_command(package_manager, "test:web"),
            cwd=workspace,
            timeout=60,
        )
    finally:
        # Teardown always runs — even if an earlier probe raised
        # mid-flight. ``docker compose down`` on a stack that was never
        # started is a harmless no-op, so we don't gate on earlier
        # success: guarantees Postgres doesn't linger after any failure
        # mode (including tests that inject exceptions).
        try:
            results["compose_down"] = _run(
                [*compose_bin, "down"], cwd=workspace, timeout=60,
            )
        except Exception as exc:  # pragma: no cover - defensive
            # _run swallows subprocess exceptions; any exception reaching
            # here is from our own code (unlikely). Record it rather than
            # letting finalize leak.
            results["compose_down"] = {
                "status": "error",
                "exit_code": -1,
                "stdout_tail": "",
                "stderr_tail": f"teardown error: {exc!r}",
                "duration_s": 0.0,
            }

    return results
