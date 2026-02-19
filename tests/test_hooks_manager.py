"""Tests for agent_team.hooks_manager module.

Covers HookConfig / HookInput dataclasses, the four individual hook
generators (TaskCompleted, TeammateIdle, Stop, PostToolUse), the
top-level generate_hooks_config() assembler, and write_hooks_to_project()
disk-persistence logic including merge and error-recovery paths.
"""

from __future__ import annotations

import json
import os
import stat
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from agent_team_v15.hooks_manager import (
    HookConfig,
    HookInput,
    generate_task_completed_hook,
    generate_teammate_idle_hook,
    generate_stop_hook,
    generate_post_tool_use_hook,
    generate_hooks_config,
    write_hooks_to_project,
)
from agent_team_v15.config import AgentTeamConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> AgentTeamConfig:
    """Create a minimal AgentTeamConfig suitable for testing hooks."""
    return AgentTeamConfig(**overrides)


# ---------------------------------------------------------------------------
# TEST-001 – TEST-005: Dataclass defaults
# ---------------------------------------------------------------------------

class TestHookConfigDefaults:
    """HookConfig should initialise with empty dicts."""

    def test_hooks_default_is_empty_dict(self):
        cfg = HookConfig()
        assert cfg.hooks == {}

    def test_scripts_default_is_empty_dict(self):
        cfg = HookConfig()
        assert cfg.scripts == {}

    def test_hooks_and_scripts_are_independent_instances(self):
        a = HookConfig()
        b = HookConfig()
        a.hooks["Stop"] = [{"type": "command"}]
        assert b.hooks == {}


class TestHookInputDefaults:
    """HookInput should initialise every field with a sensible default."""

    def test_all_string_fields_default_empty(self):
        hi = HookInput()
        for attr in (
            "session_id", "transcript_path", "cwd", "permission_mode",
            "hook_event_name", "tool_name", "task_id", "task_subject",
            "task_description", "teammate_name", "team_name",
        ):
            assert getattr(hi, attr) == "", f"{attr} should default to ''"

    def test_tool_input_default_empty_dict(self):
        hi = HookInput()
        assert hi.tool_input == {}

    def test_event_specific_fields(self):
        hi = HookInput(
            task_id="t-1",
            task_subject="implement feature",
            teammate_name="researcher",
            team_name="alpha",
        )
        assert hi.task_id == "t-1"
        assert hi.task_subject == "implement feature"
        assert hi.teammate_name == "researcher"
        assert hi.team_name == "alpha"


# ---------------------------------------------------------------------------
# TEST-006: generate_task_completed_hook()
# ---------------------------------------------------------------------------

class TestTaskCompletedHook:
    """generate_task_completed_hook() produces a matcher-group with an agent-type hook."""

    def test_task_completed_hook_type_and_timeout(self):
        group = generate_task_completed_hook()
        assert "hooks" in group
        hook = group["hooks"][0]
        assert hook["type"] == "agent"
        assert hook["timeout"] == 120
        assert "prompt" in hook

    def test_task_completed_hook_prompt_mentions_requirements(self):
        group = generate_task_completed_hook()
        hook = group["hooks"][0]
        assert "REQUIREMENTS.md" in hook["prompt"]


# ---------------------------------------------------------------------------
# TEST-007: generate_teammate_idle_hook()
# ---------------------------------------------------------------------------

class TestTeammateIdleHook:
    """generate_teammate_idle_hook() produces a matcher-group with a command-type hook."""

    def test_teammate_idle_hook_type_and_timeout(self):
        group, script = generate_teammate_idle_hook()
        assert "hooks" in group
        hook = group["hooks"][0]
        assert hook["type"] == "command"
        assert hook["timeout"] == 30
        assert "teammate-idle-check.sh" in hook["command"]
        assert script.startswith("#!/")

    def test_teammate_idle_script_has_shebang(self):
        _, script = generate_teammate_idle_hook()
        assert script.startswith("#!/usr/bin/env bash")


# ---------------------------------------------------------------------------
# TEST-008: generate_stop_hook()
# ---------------------------------------------------------------------------

class TestStopHook:
    """generate_stop_hook() produces a matcher-group with a command-type hook with quality gate."""

    def test_stop_hook_type_and_timeout(self):
        group, script = generate_stop_hook()
        assert "hooks" in group
        hook = group["hooks"][0]
        assert hook["type"] == "command"
        assert hook["timeout"] == 30
        assert "quality-gate.sh" in hook["command"]
        assert "0.8" in script  # threshold check

    def test_stop_hook_script_includes_python3_json_parsing(self):
        _, script = generate_stop_hook()
        assert "python3" in script
        assert "json.load" in script

    def test_stop_hook_script_exits_2_below_threshold(self):
        _, script = generate_stop_hook()
        assert "exit 2" in script


# ---------------------------------------------------------------------------
# TEST-009: generate_post_tool_use_hook()
# ---------------------------------------------------------------------------

class TestPostToolUseHook:
    """generate_post_tool_use_hook() produces a matcher-group with an async command hook."""

    def test_post_tool_use_hook_async_and_matcher(self):
        group, script = generate_post_tool_use_hook()
        # matcher lives on the group level, not inside the hook dict
        assert "Write|Edit" in group.get("matcher", "")
        assert "hooks" in group
        hook = group["hooks"][0]
        assert hook["type"] == "command"
        assert hook.get("async") is True
        assert "matcher" not in hook  # matcher must NOT be on the hook itself

    def test_post_tool_use_script_logs_to_file_changes(self):
        _, script = generate_post_tool_use_hook()
        assert "file-changes.log" in script


# ---------------------------------------------------------------------------
# TEST-010 – TEST-011: write_hooks_to_project()
# ---------------------------------------------------------------------------

class TestWriteHooksToProject:
    """Disk-persistence: directory creation, file writing, merge, and chmod."""

    def test_write_hooks_creates_files(self, tmp_path: Path):
        config = HookConfig(
            hooks={"Stop": [{"type": "command", "command": ".claude/hooks/test.sh"}]},
            scripts={"test.sh": "#!/bin/bash\necho hello"},
        )
        result = write_hooks_to_project(config, tmp_path)
        assert (tmp_path / ".claude" / "settings.local.json").exists()
        assert (tmp_path / ".claude" / "hooks" / "test.sh").exists()

    def test_write_hooks_merges_existing(self, tmp_path: Path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        existing = {"allowedTools": ["Read", "Write"], "customKey": 42}
        (claude_dir / "settings.local.json").write_text(json.dumps(existing))

        config = HookConfig(hooks={"Stop": [{"type": "command"}]}, scripts={})
        write_hooks_to_project(config, tmp_path)

        result = json.loads((claude_dir / "settings.local.json").read_text())
        assert result["allowedTools"] == ["Read", "Write"]
        assert result["customKey"] == 42
        assert "hooks" in result

    def test_write_hooks_returns_path_to_settings(self, tmp_path: Path):
        config = HookConfig(hooks={}, scripts={})
        result = write_hooks_to_project(config, tmp_path)
        assert isinstance(result, Path)
        assert result.name == "settings.local.json"
        assert result.exists()

    def test_write_hooks_handles_missing_claude_directory(self, tmp_path: Path):
        """write_hooks_to_project must create .claude/ and .claude/hooks/ from scratch."""
        assert not (tmp_path / ".claude").exists()
        config = HookConfig(
            hooks={"Stop": [{"type": "command"}]},
            scripts={"gate.sh": "#!/bin/bash\necho ok"},
        )
        result = write_hooks_to_project(config, tmp_path)
        assert result.exists()
        assert (tmp_path / ".claude" / "hooks" / "gate.sh").exists()

    def test_write_hooks_handles_corrupt_existing_settings(self, tmp_path: Path):
        """If settings.local.json contains invalid JSON it should be overwritten."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.local.json").write_text("{bad json!!!")

        config = HookConfig(hooks={"Stop": [{"type": "command"}]}, scripts={})
        result = write_hooks_to_project(config, tmp_path)

        parsed = json.loads(result.read_text())
        assert "hooks" in parsed
        assert parsed["hooks"]["Stop"] == [{"type": "command"}]

    def test_script_content_written_correctly(self, tmp_path: Path):
        script_body = "#!/bin/bash\nset -e\necho 'running quality gate'"
        config = HookConfig(
            hooks={},
            scripts={"my-hook.sh": script_body},
        )
        write_hooks_to_project(config, tmp_path)
        written = (tmp_path / ".claude" / "hooks" / "my-hook.sh").read_text()
        assert written == script_body


# ---------------------------------------------------------------------------
# TEST-017: chmod graceful degradation on Windows
# ---------------------------------------------------------------------------

class TestChmodGracefulDegradation:
    """write_hooks_to_project succeeds even when chmod raises OSError."""

    def test_chmod_oserror_is_silently_caught(self, tmp_path: Path):
        config = HookConfig(
            hooks={},
            scripts={"fragile.sh": "#!/bin/bash\ntrue"},
        )
        with patch("pathlib.Path.chmod", side_effect=OSError("chmod not supported")):
            # Must not raise
            result = write_hooks_to_project(config, tmp_path)

        assert result.exists()
        assert (tmp_path / ".claude" / "hooks" / "fragile.sh").exists()


# ---------------------------------------------------------------------------
# generate_hooks_config() assembly tests
# ---------------------------------------------------------------------------

class TestGenerateHooksConfig:
    """generate_hooks_config() should assemble all four event types."""

    def test_returns_hook_config_with_all_four_event_types(self):
        cfg = _make_config()
        hc = generate_hooks_config(cfg, Path("/fake/project"))
        expected_events = {"TaskCompleted", "TeammateIdle", "Stop", "PostToolUse"}
        assert set(hc.hooks.keys()) == expected_events

    def test_includes_scripts_for_shell_based_hooks(self):
        cfg = _make_config()
        hc = generate_hooks_config(cfg, Path("/fake/project"))
        # Three shell-based hooks: teammate-idle-check.sh, quality-gate.sh, track-file-change.sh
        assert "teammate-idle-check.sh" in hc.scripts
        assert "quality-gate.sh" in hc.scripts
        assert "track-file-change.sh" in hc.scripts
        assert len(hc.scripts) == 3

    def test_with_requirements_path(self):
        cfg = _make_config()
        req_path = Path("/project/REQUIREMENTS.md")
        hc = generate_hooks_config(cfg, Path("/project"), requirements_path=req_path)
        # Should still produce all events
        assert "Stop" in hc.hooks
        assert len(hc.hooks["Stop"]) == 1

    def test_without_requirements_path(self):
        cfg = _make_config()
        hc = generate_hooks_config(cfg, Path("/project"), requirements_path=None)
        assert "Stop" in hc.hooks

    def test_task_completed_is_agent_type(self):
        cfg = _make_config()
        hc = generate_hooks_config(cfg, Path("/project"))
        tc_groups = hc.hooks["TaskCompleted"]
        assert len(tc_groups) == 1
        # Nested structure: group -> hooks -> [hook_dict]
        assert tc_groups[0]["hooks"][0]["type"] == "agent"

    def test_post_tool_use_is_async(self):
        cfg = _make_config()
        hc = generate_hooks_config(cfg, Path("/project"))
        pt_groups = hc.hooks["PostToolUse"]
        assert len(pt_groups) == 1
        # matcher lives on the group level
        assert "Write|Edit" in pt_groups[0].get("matcher", "")
        # async lives on the hook inside the group
        assert pt_groups[0]["hooks"][0].get("async") is True
