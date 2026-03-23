"""Windows SDK patch for claude_agent_sdk WinError 206.

The claude_agent_sdk's SubprocessCLITransport._build_command() can pass
very large flag values (--system-prompt ~44K chars, --agents ~110K chars)
as CLI arguments, exceeding Windows' 32,767-char CreateProcess limit.

This module monkey-patches the SDK transport so that any flag value
exceeding 4K chars is written to a temporary file and referenced via
the @filepath convention.  The patch is idempotent and only activates
on Windows.

Applying this patch at import time means it survives across sessions
without needing to edit site-packages directly.
"""

from __future__ import annotations

import logging
import platform

logger = logging.getLogger(__name__)

_PATCHED = False


def apply_windows_sdk_patch() -> None:
    """Apply the temp-file optimization to claude_agent_sdk on Windows.

    This is idempotent — calling it multiple times is safe.
    """
    global _PATCHED  # noqa: PLW0603
    if _PATCHED:
        return

    if platform.system() != "Windows":
        _PATCHED = True
        return

    try:
        from claude_agent_sdk._internal.transport.subprocess_cli import (
            SubprocessCLITransport,
        )
    except ImportError:
        logger.debug("claude_agent_sdk not installed — SDK patch not needed")
        _PATCHED = True
        return

    # Check if the SDK already has the temp file optimization
    # by looking for the _temp_files attribute or the _CMD_LENGTH_LIMIT constant
    import claude_agent_sdk._internal.transport.subprocess_cli as transport_mod

    if hasattr(transport_mod, "_CMD_LENGTH_LIMIT"):
        logger.debug("SDK already has temp file optimization — patch not needed")
        _PATCHED = True
        return

    # Apply the patch: override _build_command to use temp files for large values
    import json
    import tempfile
    from pathlib import Path

    _LARGE_VALUE_THRESHOLD = 4000
    _CMD_LENGTH_LIMIT = 8000  # Windows cmd.exe safety limit

    original_build_command = SubprocessCLITransport._build_command

    def _patched_build_command(self) -> list[str]:
        cmd = original_build_command(self)

        # Check total command line length
        cmd_str = " ".join(cmd)
        if len(cmd_str) <= _CMD_LENGTH_LIMIT:
            return cmd

        # Move large flag values to temp files
        large_flags = [
            "--agents",
            "--system-prompt",
            "--append-system-prompt",
            "--mcp-config",
        ]
        for flag in large_flags:
            if flag not in cmd:
                continue
            try:
                flag_idx = cmd.index(flag)
                flag_value = cmd[flag_idx + 1]
                if len(flag_value) > _LARGE_VALUE_THRESHOLD:
                    suffix = (
                        ".json"
                        if flag in ("--agents", "--mcp-config")
                        else ".txt"
                    )
                    temp_file = tempfile.NamedTemporaryFile(
                        mode="w",
                        suffix=suffix,
                        delete=False,
                        encoding="utf-8",
                    )
                    temp_file.write(flag_value)
                    temp_file.close()
                    if not hasattr(self, "_temp_files"):
                        self._temp_files = []
                    self._temp_files.append(temp_file.name)
                    cmd[flag_idx + 1] = f"@{temp_file.name}"
                    logger.info(
                        "SDK patch: moved %s (%d chars) to temp file: %s",
                        flag,
                        len(flag_value),
                        temp_file.name,
                    )
            except (ValueError, IndexError):
                pass

        return cmd

    SubprocessCLITransport._build_command = _patched_build_command
    logger.info("Applied Windows SDK patch for WinError 206 prevention")
    _PATCHED = True
