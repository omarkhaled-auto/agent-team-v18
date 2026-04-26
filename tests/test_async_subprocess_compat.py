from __future__ import annotations

import asyncio
import io
from pathlib import Path
import sys
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_create_subprocess_exec_compat_runs_piped_process() -> None:
    from agent_team_v15.async_subprocess_compat import create_subprocess_exec_compat

    proc = await create_subprocess_exec_compat(
        sys.executable,
        "-c",
        "print('compat-ok')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

    assert proc.returncode == 0
    assert stdout.decode("utf-8").strip() == "compat-ok"
    assert stderr == b""


@pytest.mark.asyncio
async def test_windows_compat_uses_sync_popen_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_team_v15 import async_subprocess_compat as compat

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class FakePopen:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO(b"ready\n")
            self.stderr = io.BytesIO()
            self.pid = 1234
            self._returncode: int | None = None

        def poll(self) -> int | None:
            return self._returncode

        def wait(self) -> int:
            self._returncode = 0
            return 0

        def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            if input:
                self.stdin.write(input)
            self._returncode = 0
            return b"stdout", b"stderr"

        def terminate(self) -> None:
            self._returncode = -15

        def kill(self) -> None:
            self._returncode = -9

    monkeypatch.setattr(compat.sys, "platform", "win32")
    monkeypatch.setattr(compat.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(compat.shutil, "which", lambda name: "C:/npm/tool.cmd" if name == "tool.cmd" else None)

    proc = await compat.create_subprocess_exec_compat(
        "tool.cmd",
        "--flag",
        cwd="C:/work",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"A": "B"},
    )

    stdout, stderr = await proc.communicate(b"input")

    assert stdout == b"stdout"
    assert stderr == b"stderr"
    assert proc.pid == 1234
    assert proc.returncode == 0
    assert calls[0][0][0] == ["C:/npm/tool.cmd", "--flag"]
    assert calls[0][1]["cwd"] == "C:/work"
    assert calls[0][1]["env"] == {"A": "B"}


@pytest.mark.asyncio
async def test_windows_compat_resolves_ps1_through_powershell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_team_v15 import async_subprocess_compat as compat

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class FakePopen:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()
            self.pid = 2222
            self._returncode: int | None = None

        def poll(self) -> int | None:
            return self._returncode

        def wait(self) -> int:
            self._returncode = 0
            return 0

        def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            self._returncode = 0
            return b"", b""

        def terminate(self) -> None:
            self._returncode = -15

        def kill(self) -> None:
            self._returncode = -9

    monkeypatch.setattr(compat.sys, "platform", "win32")
    monkeypatch.setattr(compat.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(compat.shutil, "which", lambda name: "C:/npm/tool.ps1" if name == "tool.ps1" else None)

    proc = await compat.create_subprocess_exec_compat(
        "tool",
        "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.wait()

    assert calls[0][0][0] == [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "C:/npm/tool.ps1",
        "--version",
    ]


@pytest.mark.asyncio
async def test_windows_shell_compat_uses_popen_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_team_v15 import async_subprocess_compat as compat

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class FakePopen:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()
            self.pid = 5678
            self._returncode: int | None = None

        def poll(self) -> int | None:
            return self._returncode

        def wait(self) -> int:
            self._returncode = 0
            return 0

        def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            self._returncode = 0
            return b"", b""

        def terminate(self) -> None:
            self._returncode = -15

        def kill(self) -> None:
            self._returncode = -9

    monkeypatch.setattr(compat.sys, "platform", "win32")
    monkeypatch.setattr(compat.subprocess, "Popen", FakePopen)

    proc = await compat.create_subprocess_shell_compat(
        '"tool.cmd" app-server --listen stdio://',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.wait()

    assert proc.pid == 5678
    assert calls[0][0][0] == '"tool.cmd" app-server --listen stdio://'
    assert calls[0][1]["shell"] is True


def test_production_code_uses_subprocess_compat_for_asyncio_spawns() -> None:
    root = Path("src/agent_team_v15")
    offenders: list[str] = []

    for path in root.rglob("*.py"):
        if path.name == "async_subprocess_compat.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "create_subprocess_exec(" in text or "create_subprocess_shell(" in text:
            offenders.append(str(path))

    assert offenders == []
