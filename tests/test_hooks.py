"""Tests for agent_team_v15.hooks — self-learning hook system (Feature #4)."""

from __future__ import annotations

import logging
import pytest

from agent_team_v15.hooks import (
    HookRegistry,
    _post_build_pattern_capture,
    _pre_build_pattern_retrieval,
    setup_default_hooks,
)


# ---------------------------------------------------------------------------
# HookRegistry basics
# ---------------------------------------------------------------------------

class TestHookRegistry:
    """Core registry behavior."""

    def test_register_and_emit(self):
        """Registered handlers fire when event is emitted."""
        results = []
        registry = HookRegistry()
        registry.register("pre_build", lambda **kw: results.append("fired"))
        registry.emit("pre_build")
        assert results == ["fired"]

    def test_multiple_handlers_fire_in_order(self):
        """Multiple handlers for the same event fire in registration order."""
        order = []
        registry = HookRegistry()
        registry.register("post_build", lambda **kw: order.append("first"))
        registry.register("post_build", lambda **kw: order.append("second"))
        registry.emit("post_build", state=None)
        assert order == ["first", "second"]

    def test_kwargs_forwarded(self):
        """Keyword arguments from emit() are forwarded to handlers."""
        captured = {}
        def handler(**kw):
            captured.update(kw)
        registry = HookRegistry()
        registry.register("post_audit", handler)
        registry.emit("post_audit", state="s", config="c", extra=42)
        assert captured == {"state": "s", "config": "c", "extra": 42}

    def test_unknown_event_register_raises(self):
        """Registering on an unknown event raises ValueError."""
        registry = HookRegistry()
        with pytest.raises(ValueError, match="Unknown hook event"):
            registry.register("not_a_real_event", lambda **kw: None)

    def test_unknown_event_emit_does_not_raise(self):
        """Emitting an unknown event logs a warning but does not raise."""
        registry = HookRegistry()
        # Should not raise
        registry.emit("bogus_event")

    def test_handler_exception_swallowed(self, caplog):
        """An exception in a handler does not propagate or block others."""
        results = []

        def bad_handler(**kw):
            raise RuntimeError("intentional failure")

        def good_handler(**kw):
            results.append("ok")

        registry = HookRegistry()
        registry.register("post_review", bad_handler)
        registry.register("post_review", good_handler)

        with caplog.at_level(logging.WARNING):
            registry.emit("post_review")

        # Good handler still ran
        assert results == ["ok"]
        # Warning was logged
        assert any("intentional failure" in r.message for r in caplog.records)

    def test_clear_single_event(self):
        """clear(event) removes handlers for that event only."""
        registry = HookRegistry()
        registry.register("pre_build", lambda **kw: None)
        registry.register("post_build", lambda **kw: None)
        registry.clear("pre_build")
        assert registry.registered_events["pre_build"] == 0
        assert registry.registered_events["post_build"] == 1

    def test_clear_all(self):
        """clear() with no argument removes all handlers."""
        registry = HookRegistry()
        registry.register("pre_build", lambda **kw: None)
        registry.register("post_build", lambda **kw: None)
        registry.clear()
        assert all(v == 0 for v in registry.registered_events.values())

    def test_registered_events_property(self):
        """registered_events returns a dict of event -> handler count."""
        registry = HookRegistry()
        registry.register("pre_milestone", lambda **kw: None)
        registry.register("pre_milestone", lambda **kw: None)
        assert registry.registered_events["pre_milestone"] == 2
        assert registry.registered_events["pre_build"] == 0

    def test_all_six_events_supported(self):
        """All 6 documented events can be registered and emitted."""
        events = [
            "pre_build", "post_orchestration", "post_audit",
            "post_review", "post_build", "pre_milestone",
        ]
        registry = HookRegistry()
        for event in events:
            registry.register(event, lambda **kw: None)
            registry.emit(event)  # Should not raise


# ---------------------------------------------------------------------------
# setup_default_hooks
# ---------------------------------------------------------------------------

class TestSetupDefaultHooks:
    """Default hook wiring."""

    def test_registers_post_build_and_pre_build(self):
        """setup_default_hooks registers handlers for post_build and pre_build."""
        registry = HookRegistry()
        setup_default_hooks(registry)
        assert registry.registered_events["post_build"] >= 1
        assert registry.registered_events["pre_build"] >= 1

    def test_post_build_handler_calls_skill_update(self, monkeypatch, tmp_path):
        """The post_build handler delegates to update_skills_from_build."""
        called = []

        def mock_update(**kwargs):
            called.append(kwargs)

        # Monkeypatch the skills import inside hooks module
        import agent_team_v15.hooks as hooks_mod
        import agent_team_v15.skills as skills_mod
        monkeypatch.setattr(skills_mod, "update_skills_from_build", mock_update)

        # Build a minimal state-like object
        class FakeState:
            run_id = "test123"
            truth_scores = {"overall": 0.85}
            audit_score = {"score": 0.9}
            task_summary = "test task"
            depth = "standard"
            total_cost = 1.0
            convergence_ratio = 0.8
            patterns_captured = 0

        state = FakeState()
        _post_build_pattern_capture(
            state=state,
            config=None,
            cwd=str(tmp_path),
        )
        # Skill update was called
        assert len(called) == 1

    def test_pre_build_handler_no_crash_without_db(self, tmp_path):
        """Pre-build handler does not crash when no pattern_memory.db exists."""
        _pre_build_pattern_retrieval(
            state=None,
            task="build something",
            cwd=str(tmp_path),
        )
        # No exception = pass


# ---------------------------------------------------------------------------
# Pipeline wiring verification
# ---------------------------------------------------------------------------

class TestPipelineWiring:
    """Verify hooks are mentioned in CLI and coordinated_builder source."""

    def test_cli_references_hook_registry(self):
        """cli.py creates _hook_registry when hooks.enabled."""
        import inspect
        from agent_team_v15 import cli
        source = inspect.getsource(cli)
        assert "_hook_registry" in source
        assert "hooks.enabled" in source or "config.hooks.enabled" in source

    def test_cli_emits_pre_build(self):
        """cli.py emits pre_build hook."""
        import inspect
        from agent_team_v15 import cli
        source = inspect.getsource(cli)
        assert '"pre_build"' in source or "'pre_build'" in source

    def test_cli_emits_post_orchestration(self):
        """cli.py emits post_orchestration hook."""
        import inspect
        from agent_team_v15 import cli
        source = inspect.getsource(cli)
        assert '"post_orchestration"' in source or "'post_orchestration'" in source

    def test_cli_emits_post_audit(self):
        """cli.py emits post_audit hook."""
        import inspect
        from agent_team_v15 import cli
        source = inspect.getsource(cli)
        assert '"post_audit"' in source or "'post_audit'" in source

    def test_cli_emits_post_build(self):
        """cli.py emits post_build hook."""
        import inspect
        from agent_team_v15 import cli
        source = inspect.getsource(cli)
        assert '"post_build"' in source

    def test_coordinated_builder_emits_post_audit(self):
        """coordinated_builder.py emits post_audit hook."""
        import inspect
        from agent_team_v15 import coordinated_builder
        source = inspect.getsource(coordinated_builder)
        assert '"post_audit"' in source or "'post_audit'" in source

    def test_config_has_hooks_config(self):
        """AgentTeamConfig includes hooks field."""
        from agent_team_v15.config import AgentTeamConfig, HooksConfig
        cfg = AgentTeamConfig()
        assert isinstance(cfg.hooks, HooksConfig)
        assert cfg.hooks.enabled is False  # Default

    def test_state_has_pattern_fields(self):
        """RunState includes pattern tracking fields."""
        from agent_team_v15.state import RunState
        state = RunState()
        assert state.patterns_captured == 0
        assert state.patterns_retrieved == 0
