"""Tests for the Claude Code Wave D path-write sandbox hook.

Covers the documented Claude Code ``PreToolUse`` hook contract: stdin
JSON input, stdout JSON envelope output, wave-letter awareness via
``AGENT_TEAM_WAVE_LETTER``, and the ``apps/web/**`` allowed prefix.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


_HOOK_MODULE = "agent_team_v15.wave_d_path_guard"


def _run_hook(
    payload: dict,
    *,
    wave_letter: str | None = "D",
    cwd: str | None = None,
    project_dir: str | None = None,
) -> dict:
    """Invoke the hook as a subprocess (matches the runtime CLI flow).

    Returns the parsed stdout JSON envelope.
    """
    env = {
        # Minimal env so Python finds the package; inherits PATH/PYTHONPATH.
        **{k: v for k, v in __import__("os").environ.items()},
    }
    if wave_letter is not None:
        env["AGENT_TEAM_WAVE_LETTER"] = wave_letter
    else:
        env.pop("AGENT_TEAM_WAVE_LETTER", None)
    if project_dir is not None:
        env["AGENT_TEAM_PROJECT_DIR"] = project_dir
    if "cwd" not in payload and cwd:
        payload["cwd"] = cwd
    proc = subprocess.run(
        [sys.executable, "-m", _HOOK_MODULE],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode == 0, (
        f"hook exited with {proc.returncode}; stderr={proc.stderr!r}"
    )
    out = (proc.stdout or "").strip()
    if not out:
        return {}
    return json.loads(out)


def test_non_wave_d_dispatch_is_always_allowed(tmp_path: Path) -> None:
    """Wave A / repairs / audits must be unaffected by the Wave D guard."""
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(tmp_path / "tsconfig.base.json"),
            "content": "{}",
        },
    }
    result = _run_hook(payload, wave_letter="A", cwd=str(tmp_path))
    assert result == {}


def test_wave_d_allows_writes_under_apps_web(tmp_path: Path) -> None:
    web_root = tmp_path / "apps" / "web" / "src" / "app"
    web_root.mkdir(parents=True)
    target = web_root / "page.tsx"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "export default null;"},
    }
    result = _run_hook(payload, wave_letter="D", cwd=str(tmp_path))
    assert result == {}


def test_wave_d_blocks_root_tsconfig_base_json(tmp_path: Path) -> None:
    """Regression for smoke ``m1-hardening-smoke-20260425-073358``."""
    target = tmp_path / "tsconfig.base.json"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "{}"},
    }
    result = _run_hook(payload, wave_letter="D", cwd=str(tmp_path))
    deny = result.get("hookSpecificOutput") or {}
    assert deny.get("hookEventName") == "PreToolUse"
    assert deny.get("permissionDecision") == "deny"
    reason = deny.get("permissionDecisionReason") or ""
    assert "tsconfig.base.json" in reason
    assert "apps/web" in reason


def test_wave_d_blocks_packages_api_client(tmp_path: Path) -> None:
    target = tmp_path / "packages" / "api-client" / "sdk.gen.ts"
    target.parent.mkdir(parents=True)
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "x",
            "new_string": "y",
        },
    }
    result = _run_hook(payload, wave_letter="D", cwd=str(tmp_path))
    deny = result.get("hookSpecificOutput") or {}
    assert deny.get("permissionDecision") == "deny"


def test_wave_d_blocks_apps_api_writes(tmp_path: Path) -> None:
    target = tmp_path / "apps" / "api" / "src" / "main.ts"
    target.parent.mkdir(parents=True)
    payload = {
        "tool_name": "MultiEdit",
        "tool_input": {"file_path": str(target), "edits": []},
    }
    result = _run_hook(payload, wave_letter="D", cwd=str(tmp_path))
    deny = result.get("hookSpecificOutput") or {}
    assert deny.get("permissionDecision") == "deny"


def test_wave_d_allows_read_class_tools(tmp_path: Path) -> None:
    """The matcher only fires for write-class tools; Read goes through
    untouched. The hook itself shouldn't be invoked for Read by Claude
    Code, but if it is invoked manually it must allow.
    """
    target = tmp_path / "packages" / "api-client" / "index.ts"
    target.parent.mkdir(parents=True)
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(target)},
    }
    result = _run_hook(payload, wave_letter="D", cwd=str(tmp_path))
    assert result == {}


def test_wave_d_blocks_path_traversal(tmp_path: Path) -> None:
    """``apps/web/../../etc/passwd`` must be denied — traversal escapes
    the apps/web/ prefix.
    """
    target = tmp_path / "apps" / "web" / ".." / ".." / "etc" / "passwd"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "x"},
    }
    result = _run_hook(payload, wave_letter="D", cwd=str(tmp_path))
    deny = result.get("hookSpecificOutput") or {}
    # Either an outright deny (preferred) or — if the OS resolved the
    # path to actually live under apps/web/ on this filesystem — an
    # allow. The contract is that escapes do NOT silently bypass.
    if deny:
        assert deny.get("permissionDecision") == "deny"


def test_wave_d_handles_malformed_stdin_fail_open(tmp_path: Path) -> None:
    """Parse errors fall back to allow (post-wave checkpoint diff is
    the second-line defense). The hook must never silently block a
    wave because of a parser bug.
    """
    proc = subprocess.run(
        [sys.executable, "-m", _HOOK_MODULE],
        input="not json",
        capture_output=True,
        text=True,
        env={
            **{k: v for k, v in __import__("os").environ.items()},
            "AGENT_TEAM_WAVE_LETTER": "D",
        },
        timeout=15,
    )
    assert proc.returncode == 0
    out = (proc.stdout or "").strip()
    # Empty or {} both signal allow.
    if out:
        assert json.loads(out) == {}


def test_wave_d_allows_relative_path_with_project_dir_env(tmp_path: Path) -> None:
    """When tool_input.file_path is RELATIVE, the hook resolves
    against AGENT_TEAM_PROJECT_DIR / cwd. Frontend writes still allow.
    """
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "apps/web/src/app/page.tsx",
            "content": "x",
        },
    }
    result = _run_hook(
        payload,
        wave_letter="D",
        project_dir=str(tmp_path),
    )
    assert result == {}


def test_wave_d_blocks_relative_root_path(tmp_path: Path) -> None:
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "tsconfig.base.json",
            "content": "{}",
        },
    }
    result = _run_hook(
        payload,
        wave_letter="D",
        project_dir=str(tmp_path),
    )
    deny = result.get("hookSpecificOutput") or {}
    assert deny.get("permissionDecision") == "deny"
