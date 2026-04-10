"""3-Tier Model Routing — task-aware router for agent model selection (Feature #5).

Tier 1: Simple deterministic transforms (no LLM call).
Tier 2: Medium complexity — use a cheaper model (e.g., Haiku/Sonnet).
Tier 3: High complexity — use the most capable model (e.g., Opus).

The router examines the task description and optional code context,
determines the appropriate tier, and returns a ``RoutingDecision``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .complexity_analyzer import (
    ComplexityAnalyzer,
    transform_add_error_handling,
    transform_add_logging,
    transform_add_types,
    transform_async_await,
    transform_remove_console,
    transform_var_to_const,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SimpleIntent:
    """A Tier-1 intent that can be handled without an LLM call."""

    name: str
    keywords: list[str]
    transform: Callable[[str], str]
    description: str = ""


@dataclass
class RoutingDecision:
    """Result of the task router's analysis."""

    tier: int  # 1, 2, or 3
    model: str | None  # None for Tier 1 (no LLM), "haiku"/"sonnet"/"opus" for Tier 2/3
    confidence: float  # 0.0-1.0 confidence in the routing decision
    reason: str  # Human-readable explanation
    intent: str | None = None  # Tier 1 intent name, if applicable
    transform_result: str | None = None  # Tier 1 transform output, if applicable
    complexity_score: float = 0.0  # Raw complexity score from analyzer


# ---------------------------------------------------------------------------
# Built-in Tier-1 intents
# ---------------------------------------------------------------------------

_TIER1_INTENTS: list[SimpleIntent] = [
    SimpleIntent(
        name="add_types",
        keywords=["add types", "add type annotations", "typescript types", "annotate types"],
        transform=transform_add_types,
        description="Add TypeScript type annotations to function parameters",
    ),
    SimpleIntent(
        name="add_error_handling",
        keywords=["add error handling", "add try catch", "wrap in try", "error handling"],
        transform=transform_add_error_handling,
        description="Wrap function bodies in try/catch blocks",
    ),
    SimpleIntent(
        name="add_logging",
        keywords=["add logging", "add console.log", "add log statements", "instrument logging"],
        transform=transform_add_logging,
        description="Add entry/exit logging to functions",
    ),
    SimpleIntent(
        name="remove_console",
        keywords=["remove console", "strip console.log", "remove logging", "clean console"],
        transform=transform_remove_console,
        description="Remove console.log statements",
    ),
    SimpleIntent(
        name="var_to_const",
        keywords=["var to const", "replace var", "convert var to const", "var2const"],
        transform=transform_var_to_const,
        description="Replace var declarations with const",
    ),
    SimpleIntent(
        name="async_await",
        keywords=["convert to async", "then to await", "async await", "promise to async"],
        transform=transform_async_await,
        description="Convert .then() chains to async/await",
    ),
]


class TaskRouter:
    """Routes tasks to the appropriate tier and model.

    Parameters
    ----------
    enabled : bool
        When False, ``route()`` always returns a Tier-2 decision with the
        default model — effectively a pass-through.
    tier1_confidence_threshold : float
        Minimum confidence for a Tier-1 (no-LLM) match.
    tier2_complexity_threshold : float
        Complexity scores below this use Tier 2 (cheaper model).
    tier3_complexity_threshold : float
        Complexity scores at or above this use Tier 3 (most capable model).
    default_model : str
        Fallback model name when routing is disabled.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        tier1_confidence_threshold: float = 0.8,
        tier2_complexity_threshold: float = 0.3,
        tier3_complexity_threshold: float = 0.6,
        default_model: str = "sonnet",
        log_decisions: bool = True,
    ) -> None:
        self.enabled = enabled
        self.tier1_confidence_threshold = tier1_confidence_threshold
        self.tier2_complexity_threshold = tier2_complexity_threshold
        self.tier3_complexity_threshold = tier3_complexity_threshold
        self.default_model = default_model
        self.log_decisions = log_decisions
        self._analyzer = ComplexityAnalyzer()
        self._intents = list(_TIER1_INTENTS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(
        self,
        task_description: str,
        code_context: str | None = None,
    ) -> RoutingDecision:
        """Determine the routing tier and model for a task.

        Returns a ``RoutingDecision`` with tier, model, confidence, and
        reason.  Tier 1 decisions include the transform result directly
        (no LLM call needed).
        """
        if not self.enabled:
            return RoutingDecision(
                tier=2,
                model=self.default_model,
                confidence=1.0,
                reason="Routing disabled — using default model",
                complexity_score=0.0,
            )

        # Try Tier 1: keyword-based intent matching
        tier1 = self._try_tier1(task_description, code_context)
        if tier1 is not None:
            return tier1

        # Compute complexity score for Tier 2/3 decision
        complexity = self._analyzer.analyze(task_description, code_context)

        if complexity >= self.tier3_complexity_threshold:
            return RoutingDecision(
                tier=3,
                model="opus",
                confidence=min(1.0, 0.6 + complexity * 0.4),
                reason=f"High complexity ({complexity:.2f}) — routing to opus",
                complexity_score=complexity,
            )
        elif complexity >= self.tier2_complexity_threshold:
            return RoutingDecision(
                tier=2,
                model="sonnet",
                confidence=min(1.0, 0.7 + complexity * 0.3),
                reason=f"Medium complexity ({complexity:.2f}) — routing to sonnet",
                complexity_score=complexity,
            )
        else:
            return RoutingDecision(
                tier=2,
                model="haiku",
                confidence=min(1.0, 0.8 + (1.0 - complexity) * 0.2),
                reason=f"Low complexity ({complexity:.2f}) — routing to haiku",
                complexity_score=complexity,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _try_tier1(
        self,
        task_description: str,
        code_context: str | None,
    ) -> RoutingDecision | None:
        """Attempt to match a Tier-1 intent.

        Returns a ``RoutingDecision`` if a confident match is found,
        otherwise ``None``.
        """
        if not code_context:
            return None  # Tier 1 requires code to transform

        task_lower = task_description.lower()
        best_intent: SimpleIntent | None = None
        best_score = 0.0

        for intent in self._intents:
            hits = sum(1 for kw in intent.keywords if kw in task_lower)
            if hits > 0:
                confidence = min(1.0, hits / len(intent.keywords) + 0.3)
                if confidence > best_score:
                    best_score = confidence
                    best_intent = intent

        if best_intent is not None and best_score >= self.tier1_confidence_threshold:
            try:
                result = best_intent.transform(code_context)
            except Exception:
                return None  # Fall through to Tier 2/3

            return RoutingDecision(
                tier=1,
                model=None,  # No LLM needed
                confidence=best_score,
                reason=f"Tier 1 match: {best_intent.name} ({best_score:.2f} confidence)",
                intent=best_intent.name,
                transform_result=result,
                complexity_score=0.0,
            )

        return None
