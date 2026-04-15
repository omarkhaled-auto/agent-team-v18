"""Tests for D-03 — OpenAPI launcher Windows resolution.

Before D-03, ``_script_command`` returned bare ``["npx", ...]`` /
``["node", ...]`` lists and ``subprocess.run`` raised
``[WinError 2] The system cannot find the file specified`` on Windows
because ``npx`` is actually ``npx.cmd`` and Python's subprocess cannot
resolve ``.cmd`` extensions without ``shell=True``. After D-03 the
launcher is resolved via ``shutil.which`` with explicit
``.cmd`` / ``.exe`` / ``.bat`` fallback, and unresolvable launchers
surface as ``OpenAPILauncherNotFound`` — a structured exception the
caller catches and falls back to regex extraction with a legible log.

All ``shutil.which`` and ``subprocess.run`` calls are mocked — no
real ``npx`` / ``node`` invocation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_team_v15 import openapi_generator as oag
from agent_team_v15.openapi_generator import (
    OpenAPILauncherNotFound,
    _generate_openapi_specs,
    _resolve_launcher,
    _script_command,
)


# ---------------------------------------------------------------------------
# 1. shutil.which resolves the bare command → subprocess uses that path
# ---------------------------------------------------------------------------


def test_resolve_launcher_returns_base_which_path() -> None:
    """POSIX-style: ``shutil.which("npx")`` returns an absolute path
    directly; no extension fallback needed."""
    with patch.object(oag.shutil, "which", return_value="/usr/local/bin/npx") as mock:
        resolved = _resolve_launcher("npx")
    assert resolved == "/usr/local/bin/npx"
    mock.assert_called_with("npx")


def test_script_command_uses_resolved_launcher_for_ts(tmp_path: Path) -> None:
    """TS scripts must invoke the resolved ``npx`` + ``ts-node``, not the
    bare ``npx`` that historically produced WinError 2."""
    ts_script = tmp_path / "scripts" / "generate-openapi.ts"
    ts_script.parent.mkdir(parents=True, exist_ok=True)
    ts_script.write_text("// ts", encoding="utf-8")

    with patch.object(oag.shutil, "which", side_effect=lambda c: f"/resolved/{c}"):
        cmd = _script_command(ts_script)
    assert cmd[0] == "/resolved/npx"
    assert cmd[1] == "ts-node"
    assert cmd[2] == str(ts_script)


def test_script_command_uses_resolved_launcher_for_js(tmp_path: Path) -> None:
    js_script = tmp_path / "scripts" / "generate-openapi.js"
    js_script.parent.mkdir(parents=True, exist_ok=True)
    js_script.write_text("// js", encoding="utf-8")

    with patch.object(oag.shutil, "which", side_effect=lambda c: f"/resolved/{c}"):
        cmd = _script_command(js_script)
    assert cmd[0] == "/resolved/node"
    assert cmd[1] == str(js_script)


# ---------------------------------------------------------------------------
# 2. Windows: bare which returns None, .cmd variant resolves
# ---------------------------------------------------------------------------


def test_resolve_launcher_falls_through_to_cmd_extension() -> None:
    """Windows-style: ``shutil.which("npx")`` returns ``None``; the
    ``.cmd`` fallback resolves to ``C:\\npm\\npx.cmd``."""
    calls: list[str] = []

    def _fake_which(name: str) -> str | None:
        calls.append(name)
        if name == "npx":
            return None
        if name == "npx.cmd":
            return r"C:\npm\npx.cmd"
        return None

    with patch.object(oag.shutil, "which", side_effect=_fake_which):
        resolved = _resolve_launcher("npx")
    assert resolved == r"C:\npm\npx.cmd"
    # Bare name tried first, then the .cmd suffix.
    assert calls[0] == "npx"
    assert "npx.cmd" in calls


def test_resolve_launcher_tries_exe_after_cmd() -> None:
    """Order matters: ``.cmd`` comes before ``.exe`` / ``.bat``.
    When only ``.exe`` resolves, the helper returns that path."""

    def _fake_which(name: str) -> str | None:
        if name == "node":
            return None
        if name == "node.cmd":
            return None
        if name == "node.exe":
            return r"C:\node\node.exe"
        return None

    with patch.object(oag.shutil, "which", side_effect=_fake_which):
        resolved = _resolve_launcher("node")
    assert resolved == r"C:\node\node.exe"


# ---------------------------------------------------------------------------
# 3. All extensions miss → OpenAPILauncherNotFound with trail recorded
# ---------------------------------------------------------------------------


def test_resolve_launcher_raises_when_nothing_resolves() -> None:
    with patch.object(oag.shutil, "which", return_value=None):
        with pytest.raises(OpenAPILauncherNotFound) as excinfo:
            _resolve_launcher("npx")
    exc = excinfo.value
    assert exc.command == "npx"
    # Every Windows extension must appear in the trail so the error
    # message tells operators exactly what was attempted.
    assert ".cmd" in exc.extensions_tried
    assert ".exe" in exc.extensions_tried
    assert ".bat" in exc.extensions_tried
    # Human-readable message includes the command name.
    assert "npx" in str(exc)
    assert "not found on PATH" in str(exc)


def test_resolve_launcher_empty_command_raises() -> None:
    with pytest.raises(OpenAPILauncherNotFound) as excinfo:
        _resolve_launcher("")
    assert excinfo.value.command == ""


# ---------------------------------------------------------------------------
# 4. Caller catches exception and logs legible fallback (not WinError 2)
# ---------------------------------------------------------------------------


def test_generate_specs_returns_legible_error_on_missing_launcher(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """When the launcher cannot be resolved, ``_generate_openapi_specs``
    must return a structured error dict with a legible message — NOT
    the raw ``WinError 2`` that surfaced in build-j. The caller
    (``generate_openapi_contracts``) then falls through to regex
    extraction as before."""

    # Build a minimal project layout with a discoverable script.
    ts_script = tmp_path / "scripts" / "generate-openapi.ts"
    ts_script.parent.mkdir(parents=True, exist_ok=True)
    ts_script.write_text("// unused", encoding="utf-8")

    contracts_dir = tmp_path / "contracts" / "openapi"

    class _Milestone:
        id = "milestone-1"

    # Launcher cannot be resolved.
    with caplog.at_level(logging.WARNING, logger=oag.logger.name), \
         patch.object(oag.shutil, "which", return_value=None):
        result = _generate_openapi_specs(tmp_path, _Milestone(), contracts_dir)

    assert result["success"] is False
    error = result["error"]
    assert "WinError" not in error  # legible — not the cryptic Windows form
    assert "npx" in error  # names the command that went missing
    assert "not found on PATH" in error
    # The structured warning log names the fallback AND the command.
    legible = [rec.getMessage() for rec in caplog.records]
    assert any(
        "OpenAPI launcher unavailable" in msg and "regex" in msg for msg in legible
    )


def test_generate_specs_happy_path_still_invokes_subprocess(
    tmp_path: Path,
) -> None:
    """Regression guard: the happy path (launcher resolves + subprocess
    succeeds) continues to write the expected spec files. Ensures D-03
    did not regress the normal code path."""

    ts_script = tmp_path / "scripts" / "generate-openapi.ts"
    ts_script.parent.mkdir(parents=True, exist_ok=True)
    ts_script.write_text("// unused", encoding="utf-8")
    contracts_dir = tmp_path / "contracts" / "openapi"
    contracts_dir.mkdir(parents=True, exist_ok=True)

    class _CompletedProc:
        returncode = 0
        stdout = ""
        stderr = ""

    class _Milestone:
        id = "milestone-1"

    def _fake_which(name: str) -> str | None:
        # Resolve both npx and node to deterministic absolute paths.
        return f"/resolved/{name}"

    captured_cmds: list[list[str]] = []

    def _fake_run(command: list[str], **kwargs):
        captured_cmds.append(list(command))
        # Simulate a successful run that writes the expected current.json.
        (contracts_dir / "current.json").write_text("{}", encoding="utf-8")
        return _CompletedProc()

    with patch.object(oag.shutil, "which", side_effect=_fake_which), \
         patch.object(oag.subprocess, "run", side_effect=_fake_run):
        result = _generate_openapi_specs(tmp_path, _Milestone(), contracts_dir)

    assert result["success"] is True
    assert captured_cmds, "subprocess.run must have been called"
    # argv[0] is the resolved absolute path, not the bare name.
    invoked = captured_cmds[0]
    assert invoked[0] == "/resolved/npx"
    assert invoked[1] == "ts-node"
