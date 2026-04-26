"""Tests for D-03 — OpenAPI launcher Windows resolution.

Before D-03, ``_script_command`` returned bare ``["npx", ...]`` /
``["node", ...]`` lists and ``subprocess.run`` raised
``[WinError 2] The system cannot find the file specified`` on Windows
because ``npx`` is actually ``npx.cmd`` and Python's subprocess cannot
resolve ``.cmd`` extensions without ``shell=True``. After D-03 the
launcher is resolved via ``shutil.which`` with explicit
``.cmd`` / ``.exe`` / ``.bat`` fallback, and unresolvable launchers
surface as ``OpenAPILauncherNotFound`` — a structured exception the
caller catches and marks as degraded regex extraction with a legible log.

All ``shutil.which`` and ``subprocess.run`` calls are mocked — no
real ``npx`` / ``node`` invocation.
"""

from __future__ import annotations

import json
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
    """TS scripts must invoke the resolved ``npx`` + ``ts-node`` when no
    project-local ts-node is installed. (Bare ``npx`` historically
    produced WinError 2; D-03 v1 fixed that. The workspace walk in v2
    prefers a local binary when one exists.)"""
    ts_script = tmp_path / "scripts" / "generate-openapi.ts"
    ts_script.parent.mkdir(parents=True, exist_ok=True)
    ts_script.write_text("// ts", encoding="utf-8")

    # No project-local ts-node — falls through to npx.
    with patch.object(oag.shutil, "which", side_effect=lambda c: f"/resolved/{c}"):
        cmd = _script_command(ts_script, tmp_path)
    assert cmd[0] == "/resolved/npx"
    assert cmd[1] == "ts-node"
    # ts-node flags (--transpile-only + -O compiler options) now wedge
    # between the launcher and the script path for canonical Wave C
    # behavior on Node 22+.
    assert "--transpile-only" in cmd
    assert "-O" in cmd
    options_index = cmd.index("-O") + 1
    options_blob = cmd[options_index]
    for token in (
        '"module":"commonjs"',
        '"experimentalDecorators":true',
        '"emitDecoratorMetadata":true',
    ):
        assert token in options_blob, (
            f"ts-node -O compiler options must include {token}: {options_blob}"
        )
    assert cmd[-1] == str(ts_script)


def test_script_command_uses_resolved_launcher_for_js(tmp_path: Path) -> None:
    js_script = tmp_path / "scripts" / "generate-openapi.js"
    js_script.parent.mkdir(parents=True, exist_ok=True)
    js_script.write_text("// js", encoding="utf-8")

    with patch.object(oag.shutil, "which", side_effect=lambda c: f"/resolved/{c}"):
        cmd = _script_command(js_script, tmp_path)
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
    (``generate_openapi_contracts``) can then write degraded regex artifacts
    while failing Wave C."""

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


def test_generate_client_package_uses_resolved_npx_for_orval(tmp_path: Path) -> None:
    spec_path = tmp_path / "contracts" / "openapi" / "current.json"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        '{"openapi":"3.0.0","paths":{"/orders":{"get":{"operationId":"listOrders","responses":{"200":{"description":"ok"}}}}}}',
        encoding="utf-8",
    )
    (tmp_path / "orval.config.ts").write_text("export default {};\n", encoding="utf-8")
    captured_cmds: list[list[str]] = []

    class _CompletedProc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_which(name: str) -> str | None:
        if name == "npx":
            return None
        if name == "npx.cmd":
            return r"C:\npm\npx.cmd"
        return None

    def _fake_run(command: list[str], **_kwargs):
        captured_cmds.append(list(command))
        client_dir = tmp_path / "packages" / "api-client"
        client_dir.mkdir(parents=True, exist_ok=True)
        (client_dir / "index.ts").write_text(
            "export async function listOrders() { return []; }\n",
            encoding="utf-8",
        )
        return _CompletedProc()

    with patch.object(oag.shutil, "which", side_effect=_fake_which), \
         patch.object(oag.subprocess, "run", side_effect=_fake_run):
        result = oag._generate_client_package(tmp_path, spec_path)

    assert result["success"] is True
    assert result["generator"] == "orval"
    assert result["exports"] == ["listOrders"]
    assert captured_cmds
    assert captured_cmds[0][:3] == [r"C:\npm\npx.cmd", "orval", "--config"]


def test_generate_client_package_prefers_scaffolded_openapi_ts(tmp_path: Path) -> None:
    spec_path = tmp_path / "contracts" / "openapi" / "current.json"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        '{"openapi":"3.0.0","info":{"title":"Demo","version":"1.0.0"},"paths":{"/orders":{"get":{"operationId":"listOrders","responses":{"200":{"description":"ok"}}}}}}',
        encoding="utf-8",
    )
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "openapi-ts.config.ts").write_text(
        "export default {};\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    launcher = bin_dir / ("openapi-ts.cmd" if oag.os.name == "nt" else "openapi-ts")
    launcher.write_text("@echo off\n", encoding="utf-8")
    captured_cmds: list[list[str]] = []

    class _CompletedProc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(command: list[str], **_kwargs):
        captured_cmds.append(list(command))
        client_dir = tmp_path / "packages" / "api-client"
        client_dir.mkdir(parents=True, exist_ok=True)
        (client_dir / "index.ts").write_text(
            "export async function listOrders() { return []; }\n",
            encoding="utf-8",
        )
        return _CompletedProc()

    with patch.object(oag.subprocess, "run", side_effect=_fake_run):
        result = oag._generate_client_package(tmp_path, spec_path)

    assert result["success"] is True
    assert result["generator"] == "openapi-ts"
    assert result["fidelity"] == "canonical"
    assert result["exports"] == ["listOrders"]
    assert captured_cmds
    assert Path(captured_cmds[0][0]).name.startswith("openapi-ts")
    assert "-i" in captured_cmds[0]
    assert "-o" in captured_cmds[0]
    assert "-c" in captured_cmds[0]
    assert "@hey-api/client-fetch" in captured_cmds[0]
    package_json = (tmp_path / "packages" / "api-client" / "package.json").read_text(
        encoding="utf-8"
    )
    assert '"name": "@taskflow/api-client"' in package_json
    # Wave D smoke ``m1-hardening-smoke-20260425-192650`` had Wave D
    # compile-fix exhaust 3 attempts because ``packages/api-client``'s
    # generated files import ``@hey-api/client-fetch`` but the package's
    # own ``package.json`` did not declare it as a dep, so pnpm did not
    # install it under ``packages/api-client/node_modules`` and TS2307
    # blocked the api-client (and therefore Wave D) from compiling.
    pkg_data = json.loads(package_json)
    assert "@hey-api/client-fetch" in pkg_data.get("dependencies", {}), (
        f"api-client/package.json must declare @hey-api/client-fetch; got {pkg_data}"
    )


def test_api_client_package_json_pins_hey_api_version_from_web_when_available(
    tmp_path: Path,
) -> None:
    """The api-client's pinned ``@hey-api/client-fetch`` version should
    follow ``apps/web/package.json`` so the two never drift."""
    spec_path = tmp_path / "contracts" / "openapi" / "current.json"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        '{"openapi":"3.0.0","info":{"title":"X","version":"1"},"paths":{}}',
        encoding="utf-8",
    )
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "package.json").write_text(
        json.dumps({
            "name": "web",
            "dependencies": {"@hey-api/client-fetch": "^0.9.42"},
        }),
        encoding="utf-8",
    )
    client_dir = tmp_path / "packages" / "api-client"
    oag._write_api_client_package_json(tmp_path, client_dir)
    pkg = json.loads((client_dir / "package.json").read_text(encoding="utf-8"))
    assert pkg["dependencies"]["@hey-api/client-fetch"] == "^0.9.42"


def test_api_client_package_json_falls_back_to_default_when_web_missing(
    tmp_path: Path,
) -> None:
    """If apps/web/package.json is absent or unreadable, fall back to
    ``_DEFAULT_HEY_API_CLIENT_FETCH_VERSION``."""
    client_dir = tmp_path / "packages" / "api-client"
    oag._write_api_client_package_json(tmp_path, client_dir)
    pkg = json.loads((client_dir / "package.json").read_text(encoding="utf-8"))
    assert (
        pkg["dependencies"]["@hey-api/client-fetch"]
        == oag._DEFAULT_HEY_API_CLIENT_FETCH_VERSION
    )


def test_generate_client_package_does_not_use_npx_for_openapi_ts(tmp_path: Path) -> None:
    spec_path = tmp_path / "contracts" / "openapi" / "current.json"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        '{"openapi":"3.0.0","info":{"title":"Demo","version":"1.0.0"},"paths":{"/orders":{"get":{"operationId":"listOrders","responses":{"200":{"description":"ok"}}}}}}',
        encoding="utf-8",
    )
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "openapi-ts.config.ts").write_text(
        "export default {};\n",
        encoding="utf-8",
    )

    def _fail_run(command: list[str], **_kwargs):
        raise AssertionError(f"unexpected subprocess: {command}")

    with patch.object(oag.shutil, "which", return_value=r"C:\npm\npx.cmd"), \
         patch.object(oag.subprocess, "run", side_effect=_fail_run):
        result = oag._generate_client_package(tmp_path, spec_path)

    assert result["success"] is True
    assert result["fidelity"] == "degraded"
    assert "project-local openapi-ts launcher not found" in result["degradation_reason"]


# ---------------------------------------------------------------------------
# 5. D-03 v2: workspace-walk local-bin resolution (build-k root cause)
# ---------------------------------------------------------------------------


from agent_team_v15.openapi_generator import _resolve_local_bin


def test_resolve_local_bin_finds_root_node_modules(tmp_path: Path) -> None:
    """Plain layout: ``node_modules/.bin/ts-node`` at project root."""
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    target = bin_dir / "ts-node"
    target.write_text("#!/usr/bin/env node\n", encoding="utf-8")

    with patch.object(oag.os, "name", "posix"):
        resolved = _resolve_local_bin(tmp_path, "ts-node")
    assert resolved == str(target)


def test_resolve_local_bin_finds_workspace_node_modules(tmp_path: Path) -> None:
    """pnpm-workspace layout: ``apps/api/node_modules/.bin/ts-node.cmd``.
    This is the exact build-k scenario — root node_modules/.bin had no
    ts-node because pnpm scoped it to the workspace package."""
    bin_dir = tmp_path / "apps" / "api" / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    target = bin_dir / "ts-node.cmd"
    target.write_text("@echo off\r\n", encoding="utf-8")

    with patch.object(oag.os, "name", "nt"):
        resolved = _resolve_local_bin(tmp_path, "ts-node")
    assert resolved == str(target)


def test_resolve_local_bin_finds_packages_workspace(tmp_path: Path) -> None:
    """Walk into ``packages/<pkg>/node_modules/.bin`` too — pnpm puts
    library workspaces there."""
    bin_dir = tmp_path / "packages" / "shared" / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    target = bin_dir / "ts-node"
    target.write_text("#!/usr/bin/env node\n", encoding="utf-8")

    with patch.object(oag.os, "name", "posix"):
        resolved = _resolve_local_bin(tmp_path, "ts-node")
    assert resolved == str(target)


def test_resolve_local_bin_prefers_root_over_workspace(tmp_path: Path) -> None:
    """When both root and workspace have the binary, prefer root —
    that's the conventional resolution order and avoids picking an
    arbitrary workspace child."""
    root_bin = tmp_path / "node_modules" / ".bin"
    root_bin.mkdir(parents=True)
    root_target = root_bin / "ts-node"
    root_target.write_text("// root", encoding="utf-8")

    ws_bin = tmp_path / "apps" / "api" / "node_modules" / ".bin"
    ws_bin.mkdir(parents=True)
    (ws_bin / "ts-node").write_text("// ws", encoding="utf-8")

    with patch.object(oag.os, "name", "posix"):
        resolved = _resolve_local_bin(tmp_path, "ts-node")
    assert resolved == str(root_target)


def test_resolve_local_bin_returns_none_when_missing(tmp_path: Path) -> None:
    """No ts-node anywhere — returns None so caller can fall back to npx."""
    assert _resolve_local_bin(tmp_path, "ts-node") is None


def test_resolve_local_bin_returns_none_for_empty_name(tmp_path: Path) -> None:
    assert _resolve_local_bin(tmp_path, "") is None


def test_resolve_local_bin_tries_windows_extensions_in_order(tmp_path: Path) -> None:
    """Bare name first, then .cmd, then .exe, then .bat — same order
    as ``_resolve_launcher`` for consistency."""
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    # Only .exe exists — must still resolve.
    exe_target = bin_dir / "ts-node.exe"
    exe_target.write_text("MZ", encoding="utf-8")

    with patch.object(oag.os, "name", "nt"):
        resolved = _resolve_local_bin(tmp_path, "ts-node")
    assert resolved == str(exe_target)


def test_resolve_local_bin_skips_posix_shim_on_windows(tmp_path: Path) -> None:
    """Windows must prefer ``.cmd`` over the extensionless POSIX shim.

    pnpm writes both files. The bare ``ts-node`` starts with ``#!/bin/sh``
    and is not directly executable via ``subprocess.run`` on Windows,
    which produces the live ``WinError 193`` fallback path we saw in smoke.
    """
    bin_dir = tmp_path / "apps" / "api" / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    bare_target = bin_dir / "ts-node"
    bare_target.write_text("#!/bin/sh\n", encoding="utf-8")
    cmd_target = bin_dir / "ts-node.cmd"
    cmd_target.write_text("@echo off\r\n", encoding="utf-8")

    with patch.object(oag.os, "name", "nt"):
        resolved = _resolve_local_bin(tmp_path, "ts-node")

    assert resolved == str(cmd_target)


def test_script_command_prefers_local_bin_over_npx(tmp_path: Path) -> None:
    """When local ts-node exists, _script_command must use it directly
    — NOT route through npx. The build-k failure was npx-mediated
    lookup failing to walk into the workspace's node_modules/.bin."""
    ts_script = tmp_path / "scripts" / "generate-openapi.ts"
    ts_script.parent.mkdir(parents=True)
    ts_script.write_text("// ts", encoding="utf-8")

    # Local ts-node in workspace bin (build-k scenario)
    ws_bin = tmp_path / "apps" / "api" / "node_modules" / ".bin"
    ws_bin.mkdir(parents=True)
    local_ts_node = ws_bin / "ts-node.cmd"
    local_ts_node.write_text("@echo off\r\n", encoding="utf-8")

    # shutil.which would have resolved npx — must NOT be invoked when
    # local resolution succeeds.
    which_calls: list[str] = []

    def _fake_which(name: str) -> str | None:
        which_calls.append(name)
        return f"/resolved/{name}"

    with patch.object(oag.os, "name", "nt"), \
         patch.object(oag.shutil, "which", side_effect=_fake_which):
        cmd = _script_command(ts_script, tmp_path)

    assert cmd[0] == str(local_ts_node)
    assert cmd[-1] == str(ts_script)
    # ts-node CJS + decorator compiler option override is mandatory for
    # canonical Wave C on Node 22+ where the default module system
    # interprets .ts as ESM and drops decorator metadata.
    assert "--transpile-only" in cmd
    assert "-O" in cmd
    # npx was NOT consulted — we bypassed it entirely.
    assert "npx" not in which_calls


def test_generate_specs_uses_local_bin_when_workspace_has_it(
    tmp_path: Path,
) -> None:
    """End-to-end: build-k scenario. Workspace has ts-node, npx is on
    PATH but unusable. _generate_openapi_specs must succeed by using
    the workspace binary."""
    ts_script = tmp_path / "scripts" / "generate-openapi.ts"
    ts_script.parent.mkdir(parents=True)
    ts_script.write_text("// unused", encoding="utf-8")
    contracts_dir = tmp_path / "contracts" / "openapi"
    contracts_dir.mkdir(parents=True)

    ws_bin = tmp_path / "apps" / "api" / "node_modules" / ".bin"
    ws_bin.mkdir(parents=True)
    local_ts_node = ws_bin / "ts-node.cmd"
    local_ts_node.write_text("@echo off\r\n", encoding="utf-8")

    class _CompletedProc:
        returncode = 0
        stdout = ""
        stderr = ""

    class _Milestone:
        id = "milestone-1"

    captured_cmds: list[list[str]] = []

    def _fake_run(command: list[str], **kwargs):
        captured_cmds.append(list(command))
        (contracts_dir / "current.json").write_text("{}", encoding="utf-8")
        return _CompletedProc()

    # which() is left un-patched on purpose — it must not even be
    # consulted for ts-node when local resolution wins.
    with patch.object(oag.os, "name", "nt"), \
         patch.object(oag.subprocess, "run", side_effect=_fake_run):
        result = _generate_openapi_specs(tmp_path, _Milestone(), contracts_dir)

    assert result["success"] is True
    # First subprocess call may now be prisma generate; the ts-node
    # invocation is the one that includes the script path.
    ts_cmd = next((c for c in captured_cmds if str(ts_script) in c), None)
    assert ts_cmd is not None, f"ts-node invocation not seen in {captured_cmds}"
    assert ts_cmd[0] == str(local_ts_node)
    assert ts_cmd[-1] == str(ts_script)
    assert "--transpile-only" in ts_cmd
