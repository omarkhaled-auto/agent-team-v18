"""Async subprocess helpers with a Windows ``subprocess.Popen`` fallback.

Some Windows hosts reject ``asyncio.create_subprocess_*`` with piped stdio
(``WinError 5``), while the standard synchronous ``subprocess`` APIs work on
the same commands.  These helpers keep the async-facing process contract used
by the orchestrator while avoiding that Windows-specific launch failure.

Also exposes ``terminate_process_group`` — a POSIX best-effort
``os.killpg``-based teardown helper that mirrors the Windows
``taskkill /T`` tree kill in ``codex_appserver`` / ``codex_transport``.
Required so orchestrator-spawned grandchildren (codex → npm → node)
do not leak as orphans on Linux when the parent is killed.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, BinaryIO


def _stdio_arg(value: Any) -> Any:
    if value is asyncio.subprocess.PIPE:
        return subprocess.PIPE
    if value is asyncio.subprocess.DEVNULL:
        return subprocess.DEVNULL
    if value is asyncio.subprocess.STDOUT:
        return subprocess.STDOUT
    return value


def _resolve_windows_argv(cmd: tuple[str, ...]) -> list[str]:
    if not cmd:
        return []

    exe = cmd[0]
    resolved = exe
    with_suffix = shutil.which(exe)
    if with_suffix:
        resolved = with_suffix
    elif Path(exe).is_file():
        resolved = exe
    else:
        for suffix in (".cmd", ".exe", ".bat", ".ps1"):
            with_suffix = shutil.which(f"{exe}{suffix}")
            if with_suffix:
                resolved = with_suffix
                break

    if resolved.lower().endswith(".ps1"):
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            resolved,
            *cmd[1:],
        ]

    return [resolved, *cmd[1:]]


def resolve_subprocess_argv(cmd: list[str] | tuple[str, ...]) -> list[str]:
    """Resolve Windows command shims for synchronous ``subprocess`` calls."""

    if sys.platform == "win32":
        return _resolve_windows_argv(tuple(cmd))
    return list(cmd)


class _AsyncPopenReader:
    def __init__(self, pipe: BinaryIO | None) -> None:
        self._pipe = pipe

    async def readline(self) -> bytes:
        if self._pipe is None:
            return b""
        return await asyncio.to_thread(self._pipe.readline)


class _AsyncPopenWriter:
    def __init__(self, pipe: BinaryIO | None) -> None:
        self._pipe = pipe

    def write(self, data: bytes) -> None:
        if self._pipe is None:
            raise BrokenPipeError("stdin pipe is unavailable")
        self._pipe.write(data)

    async def drain(self) -> None:
        if self._pipe is None:
            return
        await asyncio.to_thread(self._pipe.flush)

    def close(self) -> None:
        if self._pipe is not None:
            self._pipe.close()

    async def wait_closed(self) -> None:
        return None


class AsyncPopenProcess:
    """Small adapter matching the async process surface used in this repo."""

    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        self._proc = proc
        self.stdin = _AsyncPopenWriter(proc.stdin)
        self.stdout = _AsyncPopenReader(proc.stdout)
        self.stderr = _AsyncPopenReader(proc.stderr)
        self.pid = proc.pid

    @property
    def returncode(self) -> int | None:
        return self._proc.poll()

    async def wait(self) -> int:
        return await asyncio.to_thread(self._proc.wait)

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        if input is None:
            stdout, stderr = await asyncio.to_thread(self._proc.communicate)
        else:
            stdout, stderr = await asyncio.to_thread(self._proc.communicate, input=input)
        return stdout or b"", stderr or b""

    def terminate(self) -> None:
        self._proc.terminate()

    def kill(self) -> None:
        self._proc.kill()


async def create_subprocess_exec_compat(
    *cmd: str,
    cwd: str | None = None,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
    env: dict[str, str] | None = None,
    start_new_session: bool = False,
) -> Any:
    """Create an async process, using ``Popen`` on Windows for piped stdio.

    ``start_new_session`` is forwarded to the underlying spawn API. On POSIX
    it triggers ``setsid()`` so the child becomes the leader of a fresh
    process group — required for ``terminate_process_group`` to reap
    grandchildren atomically. Silently ignored on Windows (subprocess
    module behaviour; Windows callers use ``taskkill /T`` instead).
    """

    if sys.platform == "win32":
        resolved_cmd = _resolve_windows_argv(tuple(cmd))
        return AsyncPopenProcess(
            subprocess.Popen(
                resolved_cmd,
                cwd=cwd,
                stdin=_stdio_arg(stdin),
                stdout=_stdio_arg(stdout),
                stderr=_stdio_arg(stderr),
                env=env,
                start_new_session=start_new_session,
            )
        )

    return await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        env=env,
        start_new_session=start_new_session,
    )


async def create_subprocess_shell_compat(
    cmd: str,
    *,
    cwd: str | None = None,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
    env: dict[str, str] | None = None,
    start_new_session: bool = False,
) -> Any:
    """Create an async shell process, using ``Popen`` on Windows.

    See ``create_subprocess_exec_compat`` for ``start_new_session`` semantics.
    """

    if sys.platform == "win32":
        return AsyncPopenProcess(
            subprocess.Popen(
                cmd,
                shell=True,
                cwd=cwd,
                stdin=_stdio_arg(stdin),
                stdout=_stdio_arg(stdout),
                stderr=_stdio_arg(stderr),
                env=env,
                start_new_session=start_new_session,
            )
        )

    return await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        env=env,
        start_new_session=start_new_session,
    )


async def terminate_process_group(
    pid: int | None,
    *,
    timeout: float = 2.0,
) -> None:
    """Best-effort POSIX process-group teardown.

    Sends SIGTERM to the process group of *pid*, polls for exit up to
    *timeout* seconds, then escalates to SIGKILL if any child remains.
    No-op on Windows (taskkill /T is the equivalent there) and on
    invalid/missing pids. All exceptions are swallowed: teardown must
    never block the orchestrator's shutdown path.

    Mirror of ``_kill_process_tree_windows`` but for the POSIX session
    leader created via ``start_new_session=True`` at the spawn site.
    """
    if sys.platform == "win32" or not pid:
        return

    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return
    # Refuse pids that map to undefined ``killpg`` behaviour. On Linux,
    # ``killpg(pgrp, sig)`` is implemented as ``kill(-pgrp, sig)``;
    # ``pgrp <= 1`` is POSIX-undefined and, in practice, broadcasts the
    # signal to every process the calling user owns (init's pgid is 1).
    # This bites test fixtures where a child pid comes from a MagicMock
    # whose ``__int__`` defaults to 1 — without this guard, calling
    # ``terminate_process_group`` from a unit test SIGTERMs every
    # uid-owned process: pytest, the launching shell, the entire
    # desktop session.
    if pid_int <= 1:
        return

    try:
        pgid = os.getpgid(pid_int)
    except (ProcessLookupError, PermissionError, OSError):
        return
    except Exception:  # noqa: BLE001 — fail-open, never block teardown
        return

    # Same broadcast hazard at the pgid layer (in case getpgid returns
    # an unexpectedly small value).
    if pgid <= 1:
        return

    # Self-suicide guard: if the target shares our own process group,
    # the child was spawned without ``start_new_session=True`` and
    # inherited our pgid. Killing the group would also kill us
    # (the orchestrator / pytest / caller). Skip — the caller's
    # ``proc.kill()`` already handled the immediate child, and there
    # are no orphan grandchildren to reap because the child is in
    # our session, not its own.
    try:
        own_pgid = os.getpgid(0)
    except OSError:
        own_pgid = None
    if own_pgid is not None and pgid == own_pgid:
        return

    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(pgid, signal.SIGTERM)

    loop = asyncio.get_event_loop()
    deadline = loop.time() + max(0.0, float(timeout))
    while loop.time() < deadline:
        try:
            os.killpg(pgid, 0)  # signal 0 = existence probe
        except ProcessLookupError:
            return
        except (PermissionError, OSError):
            return
        await asyncio.sleep(0.05)

    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(pgid, signal.SIGKILL)


__all__ = [
    "AsyncPopenProcess",
    "create_subprocess_exec_compat",
    "create_subprocess_shell_compat",
    "resolve_subprocess_argv",
    "terminate_process_group",
]
