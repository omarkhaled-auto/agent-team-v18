"""Async subprocess helpers with a Windows ``subprocess.Popen`` fallback.

Some Windows hosts reject ``asyncio.create_subprocess_*`` with piped stdio
(``WinError 5``), while the standard synchronous ``subprocess`` APIs work on
the same commands.  These helpers keep the async-facing process contract used
by the orchestrator while avoiding that Windows-specific launch failure.
"""

from __future__ import annotations

import asyncio
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
) -> Any:
    """Create an async process, using ``Popen`` on Windows for piped stdio."""

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
            )
        )

    return await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        env=env,
    )


async def create_subprocess_shell_compat(
    cmd: str,
    *,
    cwd: str | None = None,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
    env: dict[str, str] | None = None,
) -> Any:
    """Create an async shell process, using ``Popen`` on Windows."""

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
            )
        )

    return await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        env=env,
    )


__all__ = [
    "AsyncPopenProcess",
    "create_subprocess_exec_compat",
    "create_subprocess_shell_compat",
    "resolve_subprocess_argv",
]
