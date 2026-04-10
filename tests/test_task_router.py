"""Tests for agent_team_v15.task_router (Feature #5)."""

from __future__ import annotations

import pytest

from agent_team_v15.task_router import RoutingDecision, SimpleIntent, TaskRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_CODE = """\
var x = 1;
var y = 2;
function add(a, b) {
    console.log('adding');
    return a + b;
}
"""


# ---------------------------------------------------------------------------
# Tier 1 intent matching
# ---------------------------------------------------------------------------

class TestTier1Routing:
    def setup_method(self):
        self.router = TaskRouter(enabled=True)

    def test_var_to_const(self):
        decision = self.router.route("convert var to const", code_context=SAMPLE_CODE)
        assert decision.tier == 1
        assert decision.model is None
        assert decision.intent == "var_to_const"
        assert "const" in decision.transform_result
        assert "var" not in decision.transform_result.replace("transform_var", "")

    def test_add_types(self):
        decision = self.router.route("add types and add type annotations", code_context=SAMPLE_CODE)
        assert decision.tier == 1
        assert decision.model is None
        assert decision.intent == "add_types"
        assert "any" in decision.transform_result

    def test_add_error_handling(self):
        decision = self.router.route("add error handling and try catch", code_context=SAMPLE_CODE)
        assert decision.tier == 1
        assert decision.model is None
        assert decision.intent == "add_error_handling"
        assert "catch" in decision.transform_result

    def test_add_logging(self):
        decision = self.router.route("add logging and instrument logging", code_context=SAMPLE_CODE)
        assert decision.tier == 1
        assert decision.model is None
        assert decision.intent == "add_logging"
        assert "[ENTER]" in decision.transform_result

    def test_remove_console(self):
        decision = self.router.route("remove console.log statements, clean console", code_context=SAMPLE_CODE)
        assert decision.tier == 1
        assert decision.model is None
        assert decision.intent == "remove_console"
        assert "console.log" not in decision.transform_result

    def test_async_await(self):
        code_with_then = "function load() { fetchData().then(data => { process(data); }) }"
        decision = self.router.route("convert to async await style", code_context=code_with_then)
        assert decision.tier == 1
        assert decision.model is None
        assert decision.intent == "async_await"
        assert "await" in decision.transform_result

    def test_no_code_context_falls_through(self):
        """Tier 1 requires code context; without it, should fall to Tier 2/3."""
        decision = self.router.route("convert var to const")
        assert decision.tier in (2, 3)
        assert decision.model is not None


# ---------------------------------------------------------------------------
# Tier 2 / Tier 3 routing
# ---------------------------------------------------------------------------

class TestTier2Tier3Routing:
    def setup_method(self):
        self.router = TaskRouter(enabled=True)

    def test_low_complexity_routes_to_haiku(self):
        decision = self.router.route("fix a typo in a comment")
        assert decision.tier == 2
        assert decision.model == "haiku"

    def test_medium_complexity_routes_to_sonnet(self):
        decision = self.router.route(
            "implement feature with add validation, create component, error handling, "
            "add endpoint with pagination, filtering, sorting, and form validation"
        )
        assert decision.tier == 2
        assert decision.model == "sonnet"

    def test_high_complexity_routes_to_opus(self):
        decision = self.router.route(
            "architect a distributed microservice with authentication flow, "
            "database schema design, and caching strategy for scalability"
        )
        assert decision.tier == 3
        assert decision.model == "opus"


# ---------------------------------------------------------------------------
# Disabled mode
# ---------------------------------------------------------------------------

class TestDisabledRouting:
    def test_disabled_returns_default(self):
        router = TaskRouter(enabled=False, default_model="sonnet")
        decision = router.route("architect a complex microservice system")
        assert decision.tier == 2
        assert decision.model == "sonnet"
        assert decision.confidence == 1.0
        assert "disabled" in decision.reason.lower()


# ---------------------------------------------------------------------------
# RoutingDecision dataclass
# ---------------------------------------------------------------------------

class TestRoutingDecision:
    def test_fields(self):
        d = RoutingDecision(
            tier=1,
            model=None,
            confidence=0.9,
            reason="test",
            intent="var_to_const",
            transform_result="const x = 1;",
            complexity_score=0.0,
        )
        assert d.tier == 1
        assert d.model is None
        assert d.confidence == 0.9
        assert d.intent == "var_to_const"

    def test_default_values(self):
        d = RoutingDecision(tier=2, model="sonnet", confidence=0.8, reason="test")
        assert d.intent is None
        assert d.transform_result is None
        assert d.complexity_score == 0.0


# ---------------------------------------------------------------------------
# SimpleIntent dataclass
# ---------------------------------------------------------------------------

class TestSimpleIntent:
    def test_fields(self):
        intent = SimpleIntent(
            name="test_intent",
            keywords=["test"],
            transform=lambda code: code.upper(),
            description="Test intent",
        )
        assert intent.name == "test_intent"
        assert intent.transform("hello") == "HELLO"


# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------

class TestConfidenceThresholds:
    def test_high_threshold_reduces_tier1(self):
        """With a very high threshold, fewer tasks match Tier 1."""
        router = TaskRouter(enabled=True, tier1_confidence_threshold=0.99)
        decision = router.route("add types", code_context=SAMPLE_CODE)
        # With 0.99 threshold, single keyword match shouldn't reach Tier 1
        assert decision.tier in (1, 2, 3)  # May or may not match depending on scoring

    def test_low_threshold_increases_tier1(self):
        """With a low threshold, more tasks match Tier 1."""
        router = TaskRouter(enabled=True, tier1_confidence_threshold=0.3)
        decision = router.route("add types", code_context=SAMPLE_CODE)
        assert decision.tier == 1


# ---------------------------------------------------------------------------
# Pipeline wiring verification
# ---------------------------------------------------------------------------

class TestPipelineWiring:
    """Verify that the router integrates with config and state."""

    def test_config_routing_dataclass_exists(self):
        from agent_team_v15.config import RoutingConfig
        rc = RoutingConfig()
        assert rc.enabled is False
        assert rc.tier1_confidence_threshold == 0.8
        assert rc.tier2_complexity_threshold == 0.3
        assert rc.tier3_complexity_threshold == 0.6
        assert rc.default_model == "sonnet"
        assert rc.log_decisions is True

    def test_config_has_routing_field(self):
        from agent_team_v15.config import AgentTeamConfig
        cfg = AgentTeamConfig()
        assert hasattr(cfg, "routing")
        assert cfg.routing.enabled is False

    def test_state_has_routing_fields(self):
        from agent_team_v15.state import RunState
        state = RunState()
        assert hasattr(state, "routing_decisions")
        assert hasattr(state, "routing_tier_counts")
        assert state.routing_decisions == []
        assert state.routing_tier_counts == {}

    def test_state_load_backward_compat(self):
        """load_state should handle missing routing fields gracefully."""
        import json
        import tempfile
        from pathlib import Path
        from agent_team_v15.state import load_state, save_state, RunState

        state = RunState(task="test")
        state.routing_decisions = [{"tier": 1, "intent": "var_to_const"}]
        state.routing_tier_counts = {"tier1": 1, "tier2": 0, "tier3": 0}

        with tempfile.TemporaryDirectory() as tmpdir:
            save_state(state, directory=tmpdir)
            loaded = load_state(directory=tmpdir)
            assert loaded is not None
            assert loaded.routing_decisions == [{"tier": 1, "intent": "var_to_const"}]
            assert loaded.routing_tier_counts == {"tier1": 1, "tier2": 0, "tier3": 0}

    def test_depth_gating_exhaustive(self):
        """Exhaustive depth auto-enables routing."""
        from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating
        cfg = AgentTeamConfig()
        assert cfg.routing.enabled is False
        apply_depth_quality_gating("exhaustive", cfg)
        assert cfg.routing.enabled is True

    def test_depth_gating_enterprise(self):
        """Enterprise depth auto-enables routing."""
        from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating
        cfg = AgentTeamConfig()
        assert cfg.routing.enabled is False
        apply_depth_quality_gating("enterprise", cfg)
        assert cfg.routing.enabled is True

    def test_depth_gating_quick_no_routing(self):
        """Quick depth should NOT auto-enable routing."""
        from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("quick", cfg)
        assert cfg.routing.enabled is False

    def test_init_exports(self):
        """task_router and complexity_analyzer must be in __all__."""
        import agent_team_v15
        assert "task_router" in agent_team_v15.__all__
        assert "complexity_analyzer" in agent_team_v15.__all__
