"""Claude-path orphan tool detection.

Tracks ToolUseBlock starts and ToolResultBlock completions from Claude SDK
streaming responses.  Detects orphan tools (started but never completed within
a configurable timeout).

Mirror of the codex-path item/started + item/completed tracking in
codex_appserver.py.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class OrphanToolEvent:
    """A single detected orphan tool start that was never completed."""

    tool_use_id: str
    tool_name: str
    started_at: float  # monotonic time
    age_seconds: float
    provider: str = "claude"


@dataclass
class OrphanToolDetector:
    """Track tool use / result pairs; surface orphans past *timeout_seconds*.

    Usage::

        detector = OrphanToolDetector(timeout_seconds=600)

        # In response iteration loop:
        detector.on_tool_use(block.id, block.name)
        detector.on_tool_result(block.tool_use_id)

        # Periodically:
        orphans = detector.check_orphans()
    """

    timeout_seconds: float = 600.0  # 10 min default for Claude path
    _pending_tools: dict[str, dict[str, float | str]] = field(default_factory=dict)

    def on_tool_use(self, tool_use_id: str, tool_name: str) -> None:
        """Record a ToolUseBlock start."""
        self._pending_tools[tool_use_id] = {
            "tool_name": tool_name,
            "started_monotonic": time.monotonic(),
        }

    def on_tool_result(self, tool_use_id: str) -> None:
        """Record a ToolResultBlock completion.  Clears the pending entry."""
        self._pending_tools.pop(tool_use_id, None)

    def check_orphans(self) -> list[OrphanToolEvent]:
        """Returns list of tool starts that have exceeded timeout without completion."""
        now = time.monotonic()
        orphans: list[OrphanToolEvent] = []
        for tid, info in self._pending_tools.items():
            started = float(info["started_monotonic"])
            age = now - started
            if age > self.timeout_seconds:
                orphans.append(
                    OrphanToolEvent(
                        tool_use_id=tid,
                        tool_name=str(info["tool_name"]),
                        started_at=started,
                        age_seconds=age,
                    )
                )
        return orphans

    def clear(self) -> None:
        """Reset all pending tool tracking."""
        self._pending_tools.clear()
