"""Agent Team v15 — Convergence-driven multi-agent orchestration system."""

__version__ = "15.0.0"

from .cli import main
from . import milestone_manager, quality_checks, wiring

__all__ = [
    "main",
    "__version__",
    "milestone_manager",
    "quality_checks",
    "wiring",
    # Build 2 modules
    "agent_teams_backend",
    "contract_client",
    "codebase_client",
    "hooks_manager",
    "claude_md_generator",
    "contract_scanner",
    "mcp_clients",
    "contracts",
]
