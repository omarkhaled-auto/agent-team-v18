"""Self-learning hook system (Feature #4).

Provides a lightweight event bus for build lifecycle events.
Handlers are registered per event name and executed in order.
All handlers are wrapped in try/except so a misbehaving hook
can never break the build pipeline.

Supported events:
    pre_build          — before orchestrator starts
    post_orchestration — after orchestrator completes
    post_audit         — after each audit cycle
    post_review        — after code review
    post_build         — after full build completes
    pre_milestone      — before each milestone starts
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

_logger = logging.getLogger(__name__)

# Type alias for hook handler functions
HookHandler = Callable[..., None]

_SUPPORTED_EVENTS = frozenset({
    "pre_build",
    "post_orchestration",
    "post_audit",
    "post_review",
    "post_build",
    "pre_milestone",
})


class HookRegistry:
    """Central registry for build lifecycle hooks.

    Usage::

        registry = HookRegistry()
        registry.register("post_build", my_handler)
        registry.emit("post_build", state=run_state, config=config)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[HookHandler]] = {
            event: [] for event in _SUPPORTED_EVENTS
        }

    def register(self, event: str, handler: HookHandler) -> None:
        """Register a handler for *event*.

        Raises ``ValueError`` if *event* is not in the supported set.
        """
        if event not in _SUPPORTED_EVENTS:
            raise ValueError(
                f"Unknown hook event {event!r}. "
                f"Supported: {sorted(_SUPPORTED_EVENTS)}"
            )
        self._handlers[event].append(handler)
        _logger.debug("Registered hook handler %s for event %s", handler.__name__, event)

    def emit(self, event: str, **kwargs: Any) -> None:
        """Fire all handlers for *event*, swallowing exceptions.

        Each handler receives the same keyword arguments.  If a handler
        raises, the exception is logged and the next handler runs.
        """
        if event not in _SUPPORTED_EVENTS:
            _logger.warning("Attempted to emit unknown event: %s", event)
            return
        for handler in self._handlers[event]:
            try:
                handler(**kwargs)
            except Exception as exc:
                _logger.warning(
                    "[HOOK] Handler %s for event %s failed: %s",
                    handler.__name__,
                    event,
                    exc,
                )

    def clear(self, event: str | None = None) -> None:
        """Remove handlers.  If *event* is ``None``, clear all."""
        if event is None:
            for key in self._handlers:
                self._handlers[key] = []
        elif event in self._handlers:
            self._handlers[event] = []

    @property
    def registered_events(self) -> dict[str, int]:
        """Return mapping of event names to handler counts."""
        return {e: len(h) for e, h in self._handlers.items()}


# ------------------------------------------------------------------
# Default hook handlers
# ------------------------------------------------------------------

def _post_build_pattern_capture(**kwargs: Any) -> None:
    """Capture build pattern and findings into pattern memory (post_build)."""
    state = kwargs.get("state")
    config = kwargs.get("config")
    cwd = kwargs.get("cwd", ".")
    if state is None:
        return
    try:
        from .pattern_memory import BuildPattern, FindingPattern, PatternMemory

        db_path = Path(cwd) / ".agent-team" / "pattern_memory.db"
        memory = PatternMemory(db_path=db_path)
        try:
            # Build pattern
            build_id = getattr(state, "run_id", "") or "unknown"
            truth_scores = getattr(state, "truth_scores", {})
            overall_truth = truth_scores.get("overall", 0.0) if isinstance(truth_scores, dict) else 0.0
            audit_score_data = getattr(state, "audit_score", {})
            audit_score_val = 0.0
            if isinstance(audit_score_data, dict):
                audit_score_val = audit_score_data.get("score", 0.0)

            # Derive weak/top dimensions from truth scores
            _weak_dims = []
            _top_dims = []
            if isinstance(truth_scores, dict):
                for dim, score in truth_scores.items():
                    if dim == "overall":
                        continue
                    if isinstance(score, (int, float)):
                        if score < 0.7:
                            _weak_dims.append(dim)
                        elif score >= 0.9:
                            _top_dims.append(dim)

            bp = BuildPattern(
                build_id=build_id,
                task_summary=getattr(state, "task", "")[:500],
                depth=getattr(state, "depth", "standard"),
                total_cost=getattr(state, "total_cost", 0.0),
                convergence_ratio=getattr(state, "completion_ratio", 0.0),
                truth_score=overall_truth,
                audit_score=audit_score_val,
                weak_dimensions=_weak_dims,
                top_dimensions=_top_dims,
            )
            memory.store_build_pattern(bp)

            # Increment state counter
            if hasattr(state, "patterns_captured"):
                state.patterns_captured += 1
        finally:
            memory.close()
    except Exception as exc:
        _logger.warning("[HOOK] Pattern capture failed: %s", exc)

    # Delegate to skills update
    try:
        from .skills import update_skills_from_build
        skills_dir = Path(cwd) / ".agent-team" / "skills"
        audit_path = Path(cwd) / ".agent-team" / "AUDIT_REPORT.json"
        gate_log = Path(cwd) / ".agent-team" / "GATE_AUDIT.log"
        # Use config to find requirements dir if available
        if config and hasattr(config, "convergence"):
            req_dir = getattr(config.convergence, "requirements_dir", ".agent-team")
            audit_path = Path(cwd) / req_dir / "AUDIT_REPORT.json"
            gate_log = Path(cwd) / req_dir / "GATE_AUDIT.log"
        update_skills_from_build(
            skills_dir=skills_dir,
            state=state,
            audit_report_path=audit_path,
            gate_log_path=gate_log,
        )
        print("[HOOK] post_build skill update completed successfully")
    except Exception as exc:
        _logger.warning("[HOOK] Skill update from post_build hook failed: %s", exc)
        print(f"[HOOK] WARNING: Skill update from post_build hook failed: {exc}")


def _pre_build_pattern_retrieval(**kwargs: Any) -> None:
    """Retrieve relevant patterns and inject into build context (pre_build)."""
    state = kwargs.get("state")
    task = kwargs.get("task", "")
    cwd = kwargs.get("cwd", ".")
    if not task:
        return
    try:
        from .pattern_memory import PatternMemory

        db_path = Path(cwd) / ".agent-team" / "pattern_memory.db"
        if not db_path.exists():
            return
        memory = PatternMemory(db_path=db_path)
        try:
            similar = memory.search_similar_builds(task, limit=3)
            top_findings = memory.get_top_findings(limit=5)
            weak_dims = memory.get_weak_dimensions(limit=3)

            if similar or top_findings or weak_dims:
                _logger.info(
                    "[HOOK] Pattern retrieval: %d similar builds, %d top findings, %d weak dims",
                    len(similar),
                    len(top_findings),
                    len(weak_dims),
                )
                if state and hasattr(state, "patterns_retrieved"):
                    state.patterns_retrieved += (
                        len(similar) + len(top_findings) + len(weak_dims)
                    )

                # Build injection text for orchestrator prompt
                injection_lines = ["## Lessons from Previous Builds\n"]
                if similar:
                    injection_lines.append(f"### {len(similar)} Similar Build(s) Found")
                    for s in similar[:3]:
                        injection_lines.append(
                            f"- {s.depth} build: truth={s.truth_score:.2f}, "
                            f"cost=${s.total_cost:.2f}"
                        )
                if top_findings:
                    injection_lines.append("\n### Top Recurring Issues to Prevent")
                    for f in top_findings[:5]:
                        injection_lines.append(
                            f"- **{f.description or f.finding_id}** "
                            f"(occurred {f.occurrence_count}x, {f.severity})"
                        )
                if weak_dims:
                    injection_lines.append("\n### Historically Weak Quality Dimensions")
                    for d in weak_dims[:3]:
                        injection_lines.append(
                            f"- {d['dimension']}: weak in {d['count']} build(s)"
                        )
                # Store in state.artifacts for prompt builder to pick up
                if state and hasattr(state, "artifacts"):
                    state.artifacts["pattern_context"] = "\n".join(injection_lines)

                # Load fix recipes for top recurring findings (Feature #4.1)
                if top_findings:
                    try:
                        finding_dicts = [
                            {"finding_id": f.finding_id, "description": f.description}
                            for f in top_findings
                        ]
                        recipe_text = memory.format_recipes_for_prompt(finding_dicts)
                        if recipe_text and state and hasattr(state, "artifacts"):
                            state.artifacts["fix_recipes"] = recipe_text
                            _logger.info(
                                "[HOOK] Loaded fix recipes for %d recurring findings",
                                len(finding_dicts),
                            )
                    except Exception as exc:
                        _logger.warning("[HOOK] Fix recipe loading failed: %s", exc)
        finally:
            memory.close()
    except Exception as exc:
        _logger.warning("[HOOK] Pattern retrieval failed: %s", exc)


# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------

def setup_default_hooks(registry: HookRegistry) -> None:
    """Register the default self-learning hooks.

    - ``post_build``: capture build pattern + trigger skill update
    - ``pre_build``: retrieve relevant past patterns
    """
    registry.register("post_build", _post_build_pattern_capture)
    registry.register("pre_build", _pre_build_pattern_retrieval)
